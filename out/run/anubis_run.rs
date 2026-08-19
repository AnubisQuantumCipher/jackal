#![allow(dead_code, unused_mut, unused_variables, unused_assignments, unreachable_code, unused_parens, unused_imports, non_snake_case, unused_braces)]
const __ANB_STACK_BUDGET: usize = 805306368;


#[derive(Clone)]
enum AnubisValue {
    Int(i64),
    Float(f64),
    Bool(bool),
    // The three heap-backed kinds share their payload through `Rc`, so cloning an AnubisValue
    // (which the generated code does on every variable read and argument pass) is an O(1) refcount
    // bump rather than a deep copy. Mutation goes through `Rc::make_mut` (copy-on-write): a uniquely
    // held payload is edited in place, a shared one is cloned first. Observable semantics are
    // identical to owning `String`/`Vec` directly; only the cost of clone changes.
    Str(std::rc::Rc<String>),
    List(std::rc::Rc<Vec<AnubisValue>>),
    /// Algebraic data: unit/tuple/struct variants.
    /// `field_names` non-empty only for struct-like variants (parallel to `fields`).
    Enum {
        ty: String,
        tag: String,
        fields: Vec<AnubisValue>,
        field_names: Vec<String>,
    },
    /// A nominal struct value with ordered, named fields.
    Struct {
        ty: String,
        fields: Vec<(String, AnubisValue)>,
    },
    /// Dictionary: string keys (via display_string) -> values, insertion-ordered.
    Map(std::rc::Rc<Vec<(String, AnubisValue)>>),
    /// A first-class function value (lambda), callable with a positional argument vector.
    Closure(std::rc::Rc<dyn Fn(Vec<AnubisValue>) -> AnubisValue>),
}

/// Construct the Rc-backed heap kinds. Named with an `anubis_` prefix (never `anb_<ident>`, the
/// shape reserved for lowered user functions) so they cannot collide with a user-defined function.
#[inline]
fn anubis_mk_str(s: String) -> AnubisValue { AnubisValue::Str(std::rc::Rc::new(s)) }
#[inline]
fn anubis_mk_list(v: Vec<AnubisValue>) -> AnubisValue { AnubisValue::List(std::rc::Rc::new(v)) }
#[inline]
fn anubis_mk_map(v: Vec<(String, AnubisValue)>) -> AnubisValue { AnubisValue::Map(std::rc::Rc::new(v)) }
/// Move the contents out of an `Rc` without cloning when it is uniquely held; clone only when the
/// payload is still shared (copy-on-write for the by-value consuming builtins).
#[inline]
fn anubis_rc_take<T: Clone>(rc: std::rc::Rc<T>) -> T {
    std::rc::Rc::try_unwrap(rc).unwrap_or_else(|rc| (*rc).clone())
}

impl std::fmt::Debug for AnubisValue {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.display_string())
    }
}

impl AnubisValue {
    fn call_closure(&self, args: Vec<AnubisValue>) -> AnubisValue {
        match self {
            AnubisValue::Closure(f) => f(args),
            _ => panic!("ANUBIS_TYPE_ERROR: expected closure, got {}", self.type_name()),
        }
    }

    fn try_call_closure(&self, args: Vec<AnubisValue>) -> AnubisValue {
        match self {
            AnubisValue::Closure(f) => f(args),
            _ => AnubisValue::Int(0),
        }
    }

    #[inline]
    fn is_closure(&self) -> bool {
        matches!(self, AnubisValue::Closure(_))
    }

    fn as_i64(&self) -> i64 {
        match self {
            AnubisValue::Int(v) => *v,
            AnubisValue::Float(v) => *v as i64,
            AnubisValue::Bool(v) => i64::from(*v),
            AnubisValue::Str(v) => v.trim().parse::<i64>().unwrap_or_else(|_| v.trim().parse::<f64>().map(|f| f as i64).unwrap_or(0)),
            AnubisValue::List(v) => v.len() as i64,
            AnubisValue::Enum { fields, .. } => fields.first().map(|f| f.as_i64()).unwrap_or(0),
            AnubisValue::Struct { fields, .. } => fields.len() as i64,
            AnubisValue::Map(m) => m.len() as i64,
            AnubisValue::Closure(_) => 0,
        }
    }

    fn as_f64(&self) -> f64 {
        match self {
            AnubisValue::Float(v) => *v,
            AnubisValue::Int(v) => *v as f64,
            AnubisValue::Bool(v) => if *v { 1.0 } else { 0.0 },
            AnubisValue::Str(v) => v.trim().parse::<f64>().unwrap_or(0.0),
            other => other.as_i64() as f64,
        }
    }

    fn is_numeric(&self) -> bool {
        matches!(self, AnubisValue::Int(_) | AnubisValue::Float(_) | AnubisValue::Bool(_))
    }

    fn is_float(&self) -> bool {
        matches!(self, AnubisValue::Float(_))
    }

    fn as_bool(&self) -> bool {
        match self {
            AnubisValue::Bool(v) => *v,
            AnubisValue::Int(v) => *v != 0,
            AnubisValue::Float(v) => *v != 0.0,
            AnubisValue::Str(v) => !v.is_empty(),
            AnubisValue::List(v) => !v.is_empty(),
            AnubisValue::Enum { .. } => true,
            AnubisValue::Struct { .. } => true,
            AnubisValue::Map(m) => !m.is_empty(),
            AnubisValue::Closure(_) => true,
        }
    }

    fn type_name(&self) -> &'static str {
        match self {
            AnubisValue::Int(_) => "int",
            AnubisValue::Float(_) => "float",
            AnubisValue::Bool(_) => "bool",
            AnubisValue::Str(_) => "string",
            AnubisValue::List(_) => "list",
            AnubisValue::Enum { .. } => "enum",
            AnubisValue::Struct { .. } => "struct",
            AnubisValue::Map(_) => "map",
            AnubisValue::Closure(_) => "closure",
        }
    }

    fn display_string(&self) -> String {
        match self {
            AnubisValue::Int(v) => v.to_string(),
            AnubisValue::Float(v) => anubis_float_str(*v),
            AnubisValue::Bool(v) => v.to_string(),
            AnubisValue::Str(v) => v.to_string(),
            AnubisValue::List(v) => {
                let parts: Vec<String> = v.iter().map(|x| x.display_string()).collect();
                format!("[{}]", parts.join(", "))
            }
            AnubisValue::Enum { ty, tag, fields, field_names } => {
                // The built-in Option/Result prelude variants are written and matched bare
                // (`Some(x)`, `None`, `Ok(x)`, `Err(e)`), so they render bare too; user enums
                // render as `Type::Variant`, the form you construct them with.
                let prefix = if ty.as_str() == "Option" || ty.as_str() == "Result" {
                    String::new()
                } else {
                    format!("{}::", ty)
                };
                if fields.is_empty() {
                    format!("{}{}", prefix, tag)
                } else if !field_names.is_empty() {
                    let parts: Vec<String> = field_names.iter().zip(fields.iter())
                        .map(|(n, v)| format!("{}: {}", n, v.display_string()))
                        .collect();
                    format!("{}{} {{ {} }}", prefix, tag, parts.join(", "))
                } else {
                    let parts: Vec<String> = fields.iter().map(|x| x.display_string()).collect();
                    format!("{}{}({})", prefix, tag, parts.join(", "))
                }
            }
            AnubisValue::Struct { ty, fields } => {
                let parts: Vec<String> = fields.iter()
                    .map(|(n, v)| format!("{}: {}", n, v.display_string()))
                    .collect();
                format!("{} {{ {} }}", ty, parts.join(", "))
            }
            AnubisValue::Map(m) => {
                // Quote keys so the printed form matches the map literal you'd write: {"a": 1}.
                let parts: Vec<String> = m.iter()
                    .map(|(k, v)| format!("{:?}: {}", k, v.display_string()))
                    .collect();
                format!("{{{}}}", parts.join(", "))
            }
            AnubisValue::Closure(_) => "<closure>".to_string(),
        }
    }

    /// Positional element access for list/tuple destructuring: only lists yield elements.
    /// Any non-list value, or an out-of-range index, yields the default `0` — this is the
    /// irrefutable "not-a-list -> 0" contract, and (unlike `index_get`) never char-slices a string.
    fn list_elem(&self, i: i64) -> AnubisValue {
        match self {
            AnubisValue::List(v) if i >= 0 && (i as usize) < v.len() => v[i as usize].clone(),
            _ => AnubisValue::Int(0),
        }
    }

    fn index_get(&self, i: AnubisValue) -> AnubisValue {
        match self {
            // Fail-closed: an explicit `xs[i]` on a list asserts `i` is in range.
            // Out-of-bounds is a bug, not a silent 0. Use get(xs, i, default) for optional access.
            AnubisValue::List(v) => {
                match anubis_norm_index(i.as_i64(), v.len()) {
                    Some(k) => v[k].clone(),
                    None => panic!(
                        "ANUBIS_INDEX_OUT_OF_BOUNDS: index {} is out of bounds for a list of length {} (use get(xs, i, default) for optional access)",
                        i.as_i64(), v.len()
                    ),
                }
            }
            // Fail-closed: `s[i]` / char_at(s, i) asserts `i` is a valid character position.
            AnubisValue::Str(s) => {
                let chars: Vec<char> = s.chars().collect();
                match anubis_norm_index(i.as_i64(), chars.len()) {
                    Some(k) => anubis_mk_str(chars[k].to_string()),
                    None => panic!(
                        "ANUBIS_INDEX_OUT_OF_BOUNDS: index {} is out of bounds for a string of length {}",
                        i.as_i64(), chars.len()
                    ),
                }
            }
            // Fail-closed: `m[k]` asserts key `k` is present. Missing key is a bug, not a silent 0.
            // Use get(m, k, default) or has_key(m, k) for optional access.
            AnubisValue::Map(m) => {
                let key = i.display_string();
                match m.iter().find(|(k, _)| k == &key) {
                    Some((_, v)) => v.clone(),
                    None => panic!(
                        "ANUBIS_MISSING_KEY: map has no key {:?} (use get(m, k, default) or has_key(m, k) for optional access)",
                        key
                    ),
                }
            }
            // A+: struct field order supports list-style r[0] (TargetRun and friends).
            // Kept as a compat accessor: a missing struct index/key stays 0 (documented list-view semantics).
            AnubisValue::Struct { fields, .. } => {
                let idx = i.as_i64();
                if idx >= 0 && (idx as usize) < fields.len() {
                    fields[idx as usize].1.clone()
                } else {
                    let key = i.display_string();
                    fields.iter().find(|(k, _)| k == &key).map(|(_, v)| v.clone()).unwrap_or(AnubisValue::Int(0))
                }
            }
            // Fail-closed: indexing a value that is not a collection is a type error, not a silent 0.
            other => panic!(
                "ANUBIS_NOT_INDEXABLE: cannot index a value of type {} with []",
                other.type_name()
            ),
        }
    }

    fn index_set(&mut self, i: AnubisValue, val: AnubisValue) {
        match self {
            AnubisValue::List(v) => {
                if let Some(k) = anubis_norm_index(i.as_i64(), v.len()) {
                    std::rc::Rc::make_mut(v)[k] = val;
                }
            }
            AnubisValue::Map(m) => {
                let key = i.display_string();
                let m = std::rc::Rc::make_mut(m);
                if let Some(slot) = m.iter_mut().find(|(k, _)| k == &key) {
                    slot.1 = val;
                } else {
                    m.push((key, val));
                }
            }
            _ => {}
        }
    }

    /// Read a named field of a struct, struct-enum variant, or map.
    fn field_get(&self, name: &str) -> AnubisValue {
        match self {
            AnubisValue::Struct { fields, .. } =>
                fields.iter().find(|(k, _)| k == name).map(|(_, v)| v.clone()).unwrap_or(AnubisValue::Int(0)),
            AnubisValue::Enum { fields, field_names, .. } =>
                field_names.iter().position(|n| n == name).and_then(|i| fields.get(i)).cloned().unwrap_or(AnubisValue::Int(0)),
            AnubisValue::Map(m) =>
                m.iter().find(|(k, _)| k == name).map(|(_, v)| v.clone()).unwrap_or(AnubisValue::Int(0)),
            _ => AnubisValue::Int(0),
        }
    }

    /// Mutate a named field of a struct (or map). No-op on other kinds.
    fn field_set(&mut self, name: &str, val: AnubisValue) {
        match self {
            AnubisValue::Struct { fields, .. } => {
                if let Some(slot) = fields.iter_mut().find(|(k, _)| k == name) { slot.1 = val; }
                else { fields.push((name.to_string(), val)); }
            }
            AnubisValue::Map(m) => {
                let m = std::rc::Rc::make_mut(m);
                if let Some(slot) = m.iter_mut().find(|(k, _)| k == name) { slot.1 = val; }
                else { m.push((name.to_string(), val)); }
            }
            _ => {}
        }
    }

    fn push_val(&mut self, val: AnubisValue) {
        match self {
            AnubisValue::List(v) => { std::rc::Rc::make_mut(v).push(val); }
            other => panic!("ANUBIS_TYPE_ERROR: push expects a list, got {}", other.type_name()),
        }
    }

    fn len_val(&self) -> AnubisValue {
        match self {
            AnubisValue::List(v) => AnubisValue::Int(v.len() as i64),
            AnubisValue::Str(s) => AnubisValue::Int(s.chars().count() as i64),
            AnubisValue::Map(m) => AnubisValue::Int(m.len() as i64),
            AnubisValue::Struct { fields, .. } => AnubisValue::Int(fields.len() as i64),
            AnubisValue::Enum { fields, .. } => AnubisValue::Int(fields.len() as i64),
            // Was `Int(0)` — `len(42)` / `len(true)` silently reported empty (Phase-5 SILENT_WRONG).
            other => panic!(
                "ANUBIS_TYPE_ERROR: len expects a list, string, map, struct, or enum, got {}",
                other.type_name()
            ),
        }
    }

    /// Keys of a map as a list of strings (for `for k in m`).
    fn map_keys(&self) -> AnubisValue {
        match self {
            AnubisValue::Map(m) => anubis_mk_list(
                m.iter().map(|(k, _)| anubis_mk_str(k.clone())).collect()
            ),
            other => panic!("ANUBIS_TYPE_ERROR: keys expects a map, got {}", other.type_name()),
        }
    }
}

/// Render an f64 so it always reads back as a float (whole values keep a trailing `.0`).
fn anubis_float_str(v: f64) -> String {
    if v.is_nan() { return "NaN".to_string(); }
    if v.is_infinite() { return if v < 0.0 { "-inf".to_string() } else { "inf".to_string() }; }
    let s = format!("{}", v);
    if s.contains('.') || s.contains('e') || s.contains('E') { s } else { format!("{}.0", s) }
}

/// Normalize an index against a length: supports negative indexing from the end.
/// Returns None when out of range.
fn anubis_norm_index(idx: i64, len: usize) -> Option<usize> {
    let k = if idx < 0 { idx + len as i64 } else { idx };
    if k >= 0 && (k as usize) < len { Some(k as usize) } else { None }
}

fn anubis_add(lhs: AnubisValue, rhs: AnubisValue) -> AnubisValue {
    match (lhs, rhs) {
        (AnubisValue::List(a), AnubisValue::List(b)) => { let mut a = anubis_rc_take(a); a.extend(anubis_rc_take(b)); anubis_mk_list(a) }
        (AnubisValue::List(a), b) => { let mut a = anubis_rc_take(a); a.push(b); anubis_mk_list(a) }
        (AnubisValue::Str(a), b) => anubis_mk_str(format!("{}{}", a, b.display_string())),
        (a, AnubisValue::Str(b)) => anubis_mk_str(format!("{}{}", a.display_string(), b)),
        (a, b) => {
            if a.is_float() || b.is_float() {
                AnubisValue::Float(a.as_f64() + b.as_f64())
            } else {
                AnubisValue::Int(a.as_i64().wrapping_add(b.as_i64()))
            }
        }
    }
}

fn anubis_sub(lhs: AnubisValue, rhs: AnubisValue) -> AnubisValue {
    if lhs.is_float() || rhs.is_float() {
        AnubisValue::Float(lhs.as_f64() - rhs.as_f64())
    } else {
        AnubisValue::Int(lhs.as_i64().wrapping_sub(rhs.as_i64()))
    }
}

fn anubis_mul(lhs: AnubisValue, rhs: AnubisValue) -> AnubisValue {
    if lhs.is_float() || rhs.is_float() {
        AnubisValue::Float(lhs.as_f64() * rhs.as_f64())
    } else {
        AnubisValue::Int(lhs.as_i64().wrapping_mul(rhs.as_i64()))
    }
}

fn anubis_div(lhs: AnubisValue, rhs: AnubisValue) -> AnubisValue {
    if lhs.is_float() || rhs.is_float() {
        AnubisValue::Float(lhs.as_f64() / rhs.as_f64())
    } else {
        let d = rhs.as_i64();
        if d == 0 { panic!("ANUBIS_DIV_BY_ZERO: integer division by zero"); }
        AnubisValue::Int(lhs.as_i64().wrapping_div(d))
    }
}

fn anubis_mod(lhs: AnubisValue, rhs: AnubisValue) -> AnubisValue {
    if lhs.is_float() || rhs.is_float() {
        AnubisValue::Float(lhs.as_f64() % rhs.as_f64())
    } else {
        let d = rhs.as_i64();
        if d == 0 { panic!("ANUBIS_MOD_BY_ZERO: integer remainder by zero"); }
        AnubisValue::Int(lhs.as_i64().wrapping_rem(d))
    }
}

fn anubis_band(lhs: AnubisValue, rhs: AnubisValue) -> AnubisValue {
    AnubisValue::Int(lhs.as_i64() & rhs.as_i64())
}
fn anubis_bor(lhs: AnubisValue, rhs: AnubisValue) -> AnubisValue {
    AnubisValue::Int(lhs.as_i64() | rhs.as_i64())
}
fn anubis_bxor(lhs: AnubisValue, rhs: AnubisValue) -> AnubisValue {
    AnubisValue::Int(lhs.as_i64() ^ rhs.as_i64())
}
fn anubis_shl(lhs: AnubisValue, rhs: AnubisValue) -> AnubisValue {
    let s = rhs.as_i64().rem_euclid(64) as u32;
    AnubisValue::Int(lhs.as_i64().wrapping_shl(s))
}
fn anubis_shr(lhs: AnubisValue, rhs: AnubisValue) -> AnubisValue {
    let s = rhs.as_i64().rem_euclid(64) as u32;
    AnubisValue::Int(lhs.as_i64().wrapping_shr(s))
}
fn anubis_bnot(v: AnubisValue) -> AnubisValue {
    AnubisValue::Int(!v.as_i64())
}

fn anubis_neg(v: AnubisValue) -> AnubisValue {
    if v.is_float() { AnubisValue::Float(-v.as_f64()) }
    else { AnubisValue::Int(v.as_i64().wrapping_neg()) }
}

fn anubis_is_int(v: &AnubisValue) -> bool {
    matches!(v, AnubisValue::Int(_) | AnubisValue::Bool(_))
}

/// Total order over two values. Integer/integer stays exact (no f64 precision loss above 2^53);
/// mixed numeric uses f64; two lists compare element-wise (lexicographic over element order, each
/// element by this same order — consistent with structural equality, so a tuple/list sort key
/// like `[grp, val]` orders as expected); everything else compares by display form.
fn anubis_value_cmp(a: &AnubisValue, b: &AnubisValue) -> std::cmp::Ordering {
    use std::cmp::Ordering;
    if anubis_is_int(a) && anubis_is_int(b) {
        a.as_i64().cmp(&b.as_i64())
    } else if a.is_numeric() && b.is_numeric() {
        a.as_f64().partial_cmp(&b.as_f64()).unwrap_or(Ordering::Equal)
    } else if let (AnubisValue::List(x), AnubisValue::List(y)) = (a, b) {
        for (p, q) in x.iter().zip(y.iter()) {
            match anubis_value_cmp(p, q) {
                Ordering::Equal => continue,
                ord => return ord,
            }
        }
        x.len().cmp(&y.len())
    } else {
        a.display_string().cmp(&b.display_string())
    }
}

/// Structural, type-aware equality (backs `==`/`!=`). Unlike the ordering used for `< > <= >=`
/// (which falls back to display form to give a total order), equality does NOT collapse across
/// types: a string never equals a number, a bool never equals an int, and compound values are
/// compared element-by-element. Int and float remain equal when numerically equal (`5 == 5.0`).
fn anubis_value_eq(a: &AnubisValue, b: &AnubisValue) -> bool {
    match (a, b) {
        (AnubisValue::Int(x), AnubisValue::Int(y)) => x == y,
        (AnubisValue::Bool(x), AnubisValue::Bool(y)) => x == y,
        (AnubisValue::Float(_), AnubisValue::Float(_))
        | (AnubisValue::Int(_), AnubisValue::Float(_))
        | (AnubisValue::Float(_), AnubisValue::Int(_)) => a.as_f64() == b.as_f64(),
        (AnubisValue::Str(x), AnubisValue::Str(y)) => x == y,
        (AnubisValue::List(x), AnubisValue::List(y)) => {
            x.len() == y.len() && x.iter().zip(y.iter()).all(|(p, q)| anubis_value_eq(p, q))
        }
        (AnubisValue::Map(x), AnubisValue::Map(y)) => {
            x.len() == y.len()
                && x.iter().all(|(k, v)| {
                    y.iter().any(|(k2, v2)| k == k2 && anubis_value_eq(v, v2))
                })
        }
        (
            AnubisValue::Enum { ty, tag, fields, .. },
            AnubisValue::Enum { ty: ty2, tag: tag2, fields: f2, .. },
        ) => {
            ty == ty2
                && tag == tag2
                && fields.len() == f2.len()
                && fields.iter().zip(f2.iter()).all(|(p, q)| anubis_value_eq(p, q))
        }
        (
            AnubisValue::Struct { ty, fields },
            AnubisValue::Struct { ty: ty2, fields: f2 },
        ) => {
            // Structs have named fields, so equality is by name — order-independent — matching
            // field access, struct patterns, and let-destructuring (all name-based). Field names
            // are unique per struct, so a name-match with equal values on every field is exact.
            ty == ty2
                && fields.len() == f2.len()
                && fields.iter().all(|(n, v)| {
                    f2.iter().any(|(n2, v2)| n == n2 && anubis_value_eq(v, v2))
                })
        }
        // Closures are never equal; mismatched kinds (string vs int, bool vs int, …) are not equal.
        _ => false,
    }
}

fn anubis_cmp(op: &str, lhs: AnubisValue, rhs: AnubisValue) -> AnubisValue {
    use std::cmp::Ordering;
    let result = match op {
        "==" => anubis_value_eq(&lhs, &rhs),
        "!=" => !anubis_value_eq(&lhs, &rhs),
        _ => {
            let ord = anubis_value_cmp(&lhs, &rhs);
            match op {
                "<" => ord == Ordering::Less,
                "<=" => ord != Ordering::Greater,
                ">" => ord == Ordering::Greater,
                ">=" => ord != Ordering::Less,
                _ => false,
            }
        }
    };
    AnubisValue::Bool(result)
}

/// One step of an lvalue path: a named field or an index.
enum AnubisPathSeg {
    Field(String),
    Index(AnubisValue),
}

impl AnubisValue {
    /// Assign `val` at the given path, descending through structs, maps, lists, and strings,
    /// mutating in place. An empty path replaces the whole value.
    fn set_at(&mut self, path: &[AnubisPathSeg], val: AnubisValue) {
        match path.split_first() {
            None => {
                *self = val;
            }
            Some((AnubisPathSeg::Field(name), rest)) => match self {
                AnubisValue::Struct { fields, .. } => {
                    if let Some(slot) = fields.iter_mut().find(|(k, _)| k == name) {
                        slot.1.set_at(rest, val);
                    } else if rest.is_empty() {
                        fields.push((name.clone(), val));
                    }
                }
                AnubisValue::Map(m) => {
                    let m = std::rc::Rc::make_mut(m);
                    if let Some(slot) = m.iter_mut().find(|(k, _)| k == name) {
                        slot.1.set_at(rest, val);
                    } else if rest.is_empty() {
                        m.push((name.clone(), val));
                    }
                }
                _ => {}
            },
            Some((AnubisPathSeg::Index(i), rest)) => match self {
                AnubisValue::List(v) => {
                    if let Some(k) = anubis_norm_index(i.as_i64(), v.len()) {
                        std::rc::Rc::make_mut(v)[k].set_at(rest, val);
                    }
                }
                AnubisValue::Map(m) => {
                    let key = i.display_string();
                    let m = std::rc::Rc::make_mut(m);
                    if let Some(slot) = m.iter_mut().find(|(k, _)| k == &key) {
                        slot.1.set_at(rest, val);
                    } else if rest.is_empty() {
                        m.push((key, val));
                    }
                }
                AnubisValue::Str(s) if rest.is_empty() => {
                    let mut chars: Vec<char> = s.chars().collect();
                    if let Some(k) = anubis_norm_index(i.as_i64(), chars.len()) {
                        if let Some(c) = val.display_string().chars().next() {
                            chars[k] = c;
                            *std::rc::Rc::make_mut(s) = chars.into_iter().collect();
                        }
                    }
                }
                _ => {}
            },
        }
    }
}

// ---- Anubis standard library runtime (shared by native run + guest) ----

fn anubis_str(v: AnubisValue) -> AnubisValue { anubis_mk_str(v.display_string()) }
fn anubis_int(v: AnubisValue) -> AnubisValue { AnubisValue::Int(v.as_i64()) }
fn anubis_float(v: AnubisValue) -> AnubisValue { AnubisValue::Float(v.as_f64()) }
fn anubis_bool_of(v: AnubisValue) -> AnubisValue { AnubisValue::Bool(v.as_bool()) }
fn anubis_type_of(v: AnubisValue) -> AnubisValue { anubis_mk_str(v.type_name().to_string()) }

/// Fail closed when a math builtin is given a non-numeric value. Soft `as_f64`/`as_i64` would
/// coerce strings/lists/maps to 0 and let contracts discharge on the wrong input.
fn anubis_require_numeric(v: &AnubisValue, name: &str) {
    if !v.is_numeric() {
        panic!(
            "ANUBIS_TYPE_ERROR: {} expects a numeric argument, got {}",
            name,
            v.type_name()
        );
    }
}

fn anubis_abs(v: AnubisValue) -> AnubisValue {
    if !v.is_numeric() {
        panic!("ANUBIS_TYPE_ERROR: abs expects a numeric argument, got {}", v.type_name());
    }
    if v.is_float() { AnubisValue::Float(v.as_f64().abs()) } else { AnubisValue::Int(v.as_i64().wrapping_abs()) }
}
// Ordered via `anubis_value_cmp` — the same comparator `sort`/`min_by` use — so Int/Int compares
// exactly as i64 (an f64 round-trip loses distinctions above 2^53) and strings order lexically.
fn anubis_min2(a: AnubisValue, b: AnubisValue) -> AnubisValue { if anubis_value_cmp(&a, &b) != std::cmp::Ordering::Greater { a } else { b } }
fn anubis_max2(a: AnubisValue, b: AnubisValue) -> AnubisValue { if anubis_value_cmp(&a, &b) != std::cmp::Ordering::Less { a } else { b } }
fn anubis_seq(items: Vec<AnubisValue>) -> Vec<AnubisValue> {
    if items.len() == 1 { if let AnubisValue::List(l) = &items[0] { return (**l).clone(); } }
    items
}
fn anubis_min(items: Vec<AnubisValue>) -> AnubisValue {
    anubis_seq(items).into_iter().reduce(anubis_min2).unwrap_or_else(|| {
        panic!("ANUBIS_EMPTY_COLLECTION: min has no element — the collection is empty (use is_empty(xs) to guard)")
    })
}
fn anubis_max(items: Vec<AnubisValue>) -> AnubisValue {
    anubis_seq(items).into_iter().reduce(anubis_max2).unwrap_or_else(|| {
        panic!("ANUBIS_EMPTY_COLLECTION: max has no element — the collection is empty (use is_empty(xs) to guard)")
    })
}
fn anubis_pow(base: AnubisValue, exp: AnubisValue) -> AnubisValue {
    anubis_require_numeric(&base, "pow");
    anubis_require_numeric(&exp, "pow");
    if base.is_float() || exp.is_float() {
        AnubisValue::Float(base.as_f64().powf(exp.as_f64()))
    } else {
        let e = exp.as_i64();
        if e < 0 { AnubisValue::Float(base.as_f64().powi(e as i32)) }
        else { AnubisValue::Int(base.as_i64().wrapping_pow(e as u32)) }
    }
}
fn anubis_sqrt(v: AnubisValue) -> AnubisValue { anubis_require_numeric(&v, "sqrt"); AnubisValue::Float(v.as_f64().sqrt()) }
// floor/ceil/round/trunc are the identity on an integer (an i64 has no fractional part, and
// routing it through f64 would corrupt magnitudes above 2^53). Only floats are rounded.
fn anubis_floor(v: AnubisValue) -> AnubisValue { anubis_require_numeric(&v, "floor"); match v { AnubisValue::Int(n) => AnubisValue::Int(n), _ => AnubisValue::Int(v.as_f64().floor() as i64) } }
fn anubis_ceil(v: AnubisValue) -> AnubisValue { anubis_require_numeric(&v, "ceil"); match v { AnubisValue::Int(n) => AnubisValue::Int(n), _ => AnubisValue::Int(v.as_f64().ceil() as i64) } }
fn anubis_round(v: AnubisValue) -> AnubisValue { anubis_require_numeric(&v, "round"); match v { AnubisValue::Int(n) => AnubisValue::Int(n), _ => AnubisValue::Int(v.as_f64().round() as i64) } }
fn anubis_gcd(a: AnubisValue, b: AnubisValue) -> AnubisValue {
    anubis_require_numeric(&a, "gcd");
    anubis_require_numeric(&b, "gcd");
    let (mut x, mut y) = (a.as_i64().wrapping_abs(), b.as_i64().wrapping_abs());
    while y != 0 { let t = y; y = x % y; x = t; }
    AnubisValue::Int(x)
}

fn anubis_upper(v: AnubisValue) -> AnubisValue { anubis_mk_str(v.display_string().to_uppercase()) }
fn anubis_lower(v: AnubisValue) -> AnubisValue { anubis_mk_str(v.display_string().to_lowercase()) }
fn anubis_trim(v: AnubisValue) -> AnubisValue { anubis_mk_str(v.display_string().trim().to_string()) }
fn anubis_split(s: AnubisValue, sep: AnubisValue) -> AnubisValue {
    let hay = s.display_string();
    let sp = sep.display_string();
    let parts: Vec<AnubisValue> = if sp.is_empty() {
        hay.chars().map(|c| anubis_mk_str(c.to_string())).collect()
    } else {
        hay.split(sp.as_str()).map(|p| anubis_mk_str(p.to_string())).collect()
    };
    anubis_mk_list(parts)
}
fn anubis_join(list: AnubisValue, sep: AnubisValue) -> AnubisValue {
    let sp = sep.display_string();
    match list {
        AnubisValue::List(items) => anubis_mk_str(
            items.iter().map(|x| x.display_string()).collect::<Vec<_>>().join(sp.as_str())
        ),
        other => panic!(
            "ANUBIS_TYPE_ERROR: join expects a list as its first argument, got {}",
            other.type_name()
        ),
    }
}
fn anubis_contains(hay: AnubisValue, needle: AnubisValue) -> AnubisValue {
    let result = match &hay {
        // Substring test for strings; structural (`==`) membership for a list, so `2 != "2"`.
        AnubisValue::Str(s) => s.contains(needle.display_string().as_str()),
        AnubisValue::List(items) => items.iter().any(|x| anubis_value_eq(x, &needle)),
        AnubisValue::Map(m) => {
            let n = needle.display_string();
            m.iter().any(|(k, _)| k == &n)
        }
        other => panic!(
            "ANUBIS_TYPE_ERROR: contains expects a list, string, or map, got {}",
            other.type_name()
        ),
    };
    AnubisValue::Bool(result)
}
fn anubis_starts_with(s: AnubisValue, p: AnubisValue) -> AnubisValue {
    AnubisValue::Bool(s.display_string().starts_with(p.display_string().as_str()))
}
fn anubis_ends_with(s: AnubisValue, p: AnubisValue) -> AnubisValue {
    AnubisValue::Bool(s.display_string().ends_with(p.display_string().as_str()))
}
fn anubis_replace(s: AnubisValue, from: AnubisValue, to: AnubisValue) -> AnubisValue {
    anubis_mk_str(s.display_string().replace(from.display_string().as_str(), to.display_string().as_str()))
}
fn anubis_index_of(hay: AnubisValue, needle: AnubisValue) -> AnubisValue {
    match &hay {
        AnubisValue::Str(s) => {
            let n = needle.display_string();
            match s.find(n.as_str()) {
                Some(byte) => AnubisValue::Int(s[..byte].chars().count() as i64),
                None => AnubisValue::Int(-1),
            }
        }
        AnubisValue::List(items) => {
            match items.iter().position(|x| anubis_value_eq(x, &needle)) {
                Some(i) => AnubisValue::Int(i as i64),
                None => AnubisValue::Int(-1),
            }
        }
        other => panic!(
            "ANUBIS_TYPE_ERROR: index_of expects a list or string, got {} (do not confuse with not-found which is -1)",
            other.type_name()
        ),
    }
}
fn anubis_ord(v: AnubisValue) -> AnubisValue {
    match v.display_string().chars().next() {
        Some(c) => AnubisValue::Int(c as i64),
        None => panic!("ANUBIS_EMPTY_COLLECTION: ord(\"\") — the empty string has no first character"),
    }
}
fn anubis_chr(v: AnubisValue) -> AnubisValue {
    let n = v.as_i64();
    match char::from_u32(n as u32) {
        Some(c) => anubis_mk_str(c.to_string()),
        None => panic!("ANUBIS_INVALID_CODEPOINT: {} is not a valid Unicode scalar value (surrogate range D800-DFFF, negative, or > 0x10FFFF)", n),
    }
}
fn anubis_repeat(s: AnubisValue, n: AnubisValue) -> AnubisValue {
    let count_raw = n.as_i64();
    if count_raw < 0 {
        panic!("ANUBIS_INVALID_ARGUMENT: repeat count must be non-negative, got {}", count_raw);
    }
    let count = count_raw as usize;
    match s {
        AnubisValue::List(items) => {
            let mut out = Vec::new();
            for _ in 0..count { out.extend(items.iter().cloned()); }
            anubis_mk_list(out)
        }
        other => anubis_mk_str(other.display_string().repeat(count)),
    }
}
fn anubis_substr(s: AnubisValue, start: AnubisValue, len: AnubisValue) -> AnubisValue {
    let chars: Vec<char> = s.display_string().chars().collect();
    // Was `.max(0)` — negative start/len silently became empty-prefix (Phase-5 M–Z SILENT_WRONG).
    let st_raw = start.as_i64();
    if st_raw < 0 {
        panic!("ANUBIS_INVALID_ARGUMENT: substr start must be non-negative, got {}", st_raw);
    }
    let ln_raw = len.as_i64();
    if ln_raw < 0 {
        panic!("ANUBIS_INVALID_ARGUMENT: substr length must be non-negative, got {}", ln_raw);
    }
    let st = st_raw as usize;
    let ln = ln_raw as usize;
    anubis_mk_str(chars.into_iter().skip(st).take(ln).collect())
}
fn anubis_slice(x: AnubisValue, a: AnubisValue, b: AnubisValue) -> AnubisValue {
    let (ai, bi) = (a.as_i64(), b.as_i64());
    let bound = |i: i64, n: i64| -> usize { (if i < 0 { (i + n).max(0) } else { i.min(n) }) as usize };
    match x {
        AnubisValue::List(items) => {
            let n = items.len() as i64;
            let (lo, hi) = (bound(ai, n), bound(bi, n));
            anubis_mk_list(if lo <= hi { items[lo..hi].to_vec() } else { vec![] })
        }
        AnubisValue::Str(s) => {
            let chars: Vec<char> = s.chars().collect();
            let n = chars.len() as i64;
            let (lo, hi) = (bound(ai, n), bound(bi, n));
            anubis_mk_str(if lo <= hi { chars[lo..hi].iter().collect() } else { String::new() })
        }
        other => panic!(
            "ANUBIS_TYPE_ERROR: slice expects a list or string, got {}",
            other.type_name()
        ),
    }
}
fn anubis_parse_int(v: AnubisValue) -> AnubisValue {
    AnubisValue::Int(v.display_string().trim().parse::<i64>().unwrap_or(0))
}
/// Cast to an integer type of the given bit width: truncate floats toward zero, then wrap into the
/// unsigned range of `bits` (so `300 as u8` == 44, `-1 as u8` == 255). `bits >= 64` = no wrap.
fn anubis_cast_int(v: AnubisValue, bits: u32, signed: bool) -> AnubisValue {
    let n = v.as_i64();
    if bits == 0 || bits >= 64 {
        return AnubisValue::Int(n);
    }
    let mask: i64 = (1i64 << bits) - 1;
    let masked = n & mask;
    // A signed target reinterprets the top bit as the sign (two's complement), so `255 as i8` is
    // -1; an unsigned target keeps the plain masked value, so `300 as u8` is 44.
    if signed && (masked & (1i64 << (bits - 1))) != 0 {
        AnubisValue::Int(masked - (1i64 << bits))
    } else {
        AnubisValue::Int(masked)
    }
}
fn anubis_parse_float(v: AnubisValue) -> AnubisValue {
    AnubisValue::Float(v.display_string().trim().parse::<f64>().unwrap_or(0.0))
}
/// Fail-closed parse: `Some(n)` on success, `None` on malformed input (unlike lenient `parse_int`,
/// which returns 0). Lets a program distinguish "the number 0" from "not a number".
fn anubis_parse_int_opt(v: AnubisValue) -> AnubisValue {
    match v.display_string().trim().parse::<i64>() {
        Ok(n) => AnubisValue::Enum {
            ty: "Option".to_string(),
            tag: "Some".to_string(),
            fields: vec![AnubisValue::Int(n)],
            field_names: vec![],
        },
        Err(_) => AnubisValue::Enum {
            ty: "Option".to_string(),
            tag: "None".to_string(),
            fields: vec![],
            field_names: vec![],
        },
    }
}
fn anubis_parse_float_opt(v: AnubisValue) -> AnubisValue {
    match v.display_string().trim().parse::<f64>() {
        Ok(f) => AnubisValue::Enum {
            ty: "Option".to_string(),
            tag: "Some".to_string(),
            fields: vec![AnubisValue::Float(f)],
            field_names: vec![],
        },
        Err(_) => AnubisValue::Enum {
            ty: "Option".to_string(),
            tag: "None".to_string(),
            fields: vec![],
            field_names: vec![],
        },
    }
}

fn anubis_range(a: AnubisValue, b: AnubisValue) -> AnubisValue {
    anubis_require_numeric(&a, "range");
    anubis_require_numeric(&b, "range");
    let (mut i, hi) = (a.as_i64(), b.as_i64());
    let mut out = Vec::new();
    while i < hi { out.push(AnubisValue::Int(i)); i += 1; }
    anubis_mk_list(out)
}
fn anubis_range_step(a: AnubisValue, b: AnubisValue, step: AnubisValue) -> AnubisValue {
    anubis_require_numeric(&a, "range");
    anubis_require_numeric(&b, "range");
    anubis_require_numeric(&step, "range");
    let (mut i, hi, st) = (a.as_i64(), b.as_i64(), step.as_i64());
    if st == 0 {
        panic!("ANUBIS_INVALID_ARGUMENT: range step must be non-zero, got 0");
    }
    let mut out = Vec::new();
    if st > 0 { while i < hi { out.push(AnubisValue::Int(i)); i += st; } }
    else { while i > hi { out.push(AnubisValue::Int(i)); i += st; } }
    anubis_mk_list(out)
}
fn anubis_reverse(x: AnubisValue) -> AnubisValue {
    match x {
        AnubisValue::List(items) => { let mut items = anubis_rc_take(items); items.reverse(); anubis_mk_list(items) }
        AnubisValue::Str(s) => anubis_mk_str(s.chars().rev().collect()),
        other => panic!(
            "ANUBIS_TYPE_ERROR: reverse expects a list or string, got {}",
            other.type_name()
        ),
    }
}
fn anubis_sort(x: AnubisValue) -> AnubisValue {
    match x {
        AnubisValue::List(items) => {
            let mut items = anubis_rc_take(items);
            items.sort_by(anubis_value_cmp);
            anubis_mk_list(items)
        }
        other => panic!("ANUBIS_TYPE_ERROR: sort expects a list, got {}", other.type_name()),
    }
}
fn anubis_sum(x: AnubisValue) -> AnubisValue {
    match x {
        AnubisValue::List(items) => {
            if items.iter().any(|v| v.is_float()) {
                AnubisValue::Float(items.iter().map(|v| v.as_f64()).sum())
            } else {
                AnubisValue::Int(items.iter().map(|v| v.as_i64()).sum())
            }
        }
        other => panic!("ANUBIS_TYPE_ERROR: sum expects a list, got {}", other.type_name()),
    }
}
fn anubis_keys(m: AnubisValue) -> AnubisValue { m.map_keys() }
fn anubis_values(m: AnubisValue) -> AnubisValue {
    match m {
        AnubisValue::Map(e) => anubis_mk_list(anubis_rc_take(e).into_iter().map(|(_, v)| v).collect()),
        other => panic!("ANUBIS_TYPE_ERROR: values expects a map, got {}", other.type_name()),
    }
}
fn anubis_has_key(m: AnubisValue, k: AnubisValue) -> AnubisValue {
    let key = k.display_string();
    match m {
        AnubisValue::Map(e) => AnubisValue::Bool(e.iter().any(|(kk, _)| kk == &key)),
        other => panic!("ANUBIS_TYPE_ERROR: has_key expects a map, got {}", other.type_name()),
    }
}

fn anubis_pop(v: &mut AnubisValue) -> AnubisValue {
    match v {
        AnubisValue::List(l) => std::rc::Rc::make_mut(l).pop().unwrap_or_else(|| {
            panic!("ANUBIS_EMPTY_COLLECTION: pop on an empty list (use is_empty(xs) to guard)")
        }),
        other => panic!("ANUBIS_TYPE_ERROR: pop expects a list, got {}", other.type_name()),
    }
}
fn anubis_insert(v: &mut AnubisValue, i: AnubisValue, val: AnubisValue) -> AnubisValue {
    match v {
        AnubisValue::List(l) => {
            let raw = i.as_i64();
            let len = l.len() as i64;
            // Negative indices count from the end (consistent with element indexing).
            let idx = if raw < 0 { (raw + len).max(0) } else { raw.min(len) } as usize;
            std::rc::Rc::make_mut(l).insert(idx, val);
        }
        other => panic!("ANUBIS_TYPE_ERROR: insert expects a list, got {}", other.type_name()),
    }
    AnubisValue::Int(0)
}
fn anubis_remove(v: &mut AnubisValue, key: AnubisValue) -> AnubisValue {
    match v {
        AnubisValue::List(l) => {
            match anubis_norm_index(key.as_i64(), l.len()) {
                Some(k) => std::rc::Rc::make_mut(l).remove(k),
                None => panic!(
                    "ANUBIS_INDEX_OUT_OF_BOUNDS: index {} is out of bounds for a list of length {} (use get(xs, i, default) for optional access)",
                    key.as_i64(), l.len()
                ),
            }
        }
        AnubisValue::Map(m) => {
            let k = key.display_string();
            match m.iter().position(|(kk, _)| kk == &k) {
                Some(pos) => std::rc::Rc::make_mut(m).remove(pos).1,
                None => panic!(
                    "ANUBIS_MISSING_KEY: key `{}` is not present in the map (use get(m, k, default) for optional access)",
                    k
                ),
            }
        }
        other => panic!("ANUBIS_TYPE_ERROR: remove expects a list or map, got {}", other.type_name()),
    }
}

fn anubis_assert(cond: AnubisValue) -> AnubisValue {
    if !cond.as_bool() { panic!("ANUBIS_ASSERT_FAILED"); }
    AnubisValue::Bool(true)
}
// The checker adds every `assume(cond)` to the solver as a trusted axiom. For that trust to be SOUND
// the runtime must guarantee the assumption actually holds — otherwise a satisfiable-but-false
// `assume` (e.g. `assume(x < 100)` reached with x = i64::MAX) silently certifies a violated contract.
// So `assume` fails closed at runtime, exactly like `assert`; it still yields `true` for value use.
fn anubis_assume(cond: AnubisValue) -> AnubisValue {
    if !cond.as_bool() { panic!("ANUBIS_ASSUME_VIOLATED: an `assume(...)` was false at runtime; the checker trusts assumptions, so this fails closed rather than silently certify a false contract"); }
    AnubisValue::Bool(true)
}
// A parameter the checker models as an integer (u8/u16/u32/u64) is proved over a pure i64 bit-vector.
// The runtime is dynamically typed, so a float/string/list argument would take a DIVERGENT arithmetic
// path (float remainder, `+` concatenation/append) and violate the proven integer contract. Enforce
// the model at entry: an integer-typed parameter must hold an integer, else fail closed.
fn anubis_require_int(v: &AnubisValue, name: &str) {
    if !matches!(v, AnubisValue::Int(_)) {
        panic!("ANUBIS_TYPE_VIOLATION: integer parameter `{}` received a non-integer value at runtime; the checker models it as an i64, so a float/string/other argument is fail-closed rather than silently mis-proved", name);
    }
}
// Unbounded recursion must fail CLOSED like every other runtime trap, not abort the process.
//
// The whole trap design rests on one sentence in `lower_program_to_rust`: a fail-closed trap panics
// the worker, the hook prints the ANUBIS_* code, `join()` returns Err, we exit non-zero. That is
// true of panics. It is NOT true of a stack overflow: Rust's overflow handler ABORTS immediately
// without unwinding, so the process dies with `fatal runtime error: stack overflow` and none of the
// diagnostic path runs. The one failure that most needs an attributable message is exactly the one
// that bypasses it -- measured on a mutual-return cycle `check` accepts (CLAIMS item 13).
//
// So guard the resource itself. The stack grows DOWN on every target this runs on, so
// `base - here` is the bytes consumed; comparing against a budget below the real ceiling traps
// while there is still room to panic, unwind, and print. Guarding BYTES rather than a frame COUNT
// is what makes this correct regardless of frame size: a function with large locals trips after
// fewer calls, which is the right answer, and a shallow-frame function still gets its full depth.
//
// The base is captured lazily on the first user-function entry rather than injected by the entry
// stub, so no lowering can silently opt out by forgetting to initialize it.
thread_local! {
    static __ANB_STACK_BASE: std::cell::Cell<usize> = const { std::cell::Cell::new(0) };
}
#[inline]
fn __anb_stack_guard() {
    if __ANB_STACK_BUDGET == 0 {
        return;
    }
    // `&0u8` would NOT work here: Rust const-promotes it to a 'static reference, so it reports a
    // rodata address and the guard silently never fires. It must be a real stack local, kept from
    // being optimized away.
    let here_marker: u8 = 0;
    let here = std::hint::black_box(&here_marker) as *const u8 as usize;
    __ANB_STACK_BASE.with(|b| {
        let base = b.get();
        if base == 0 {
            b.set(here);
        } else if base.saturating_sub(here) > __ANB_STACK_BUDGET {
            panic!("ANUBIS_RECURSION_LIMIT: recursion consumed more than {} MiB of stack without returning; `anubis check` does not prove termination, so a non-terminating program can pass the checker and this trap is how it fails closed rather than aborting the process", __ANB_STACK_BUDGET / (1024 * 1024));
        }
    });
}
// Same guard on a function's RETURN value (the model is only sound if an integer-typed function
// actually yields an integer). Returns the value through so it can wrap any return path.
fn anubis_require_int_ret(v: AnubisValue, name: &str) -> AnubisValue {
    if !matches!(v, AnubisValue::Int(_)) {
        panic!("ANUBIS_TYPE_VIOLATION: function `{}` declares an integer return type but returned a non-integer at runtime; the checker models its result as an i64, so this is fail-closed rather than silently mis-proved", name);
    }
    v
}
// The FLOAT dual of anubis_require_int (operator policy, task #34): a float-typed parameter is modeled by
// the checker as an f64, but the dynamically-typed runtime would otherwise let `f(7)` bind an Int(7),
// making `x / 2` INTEGER division (3) instead of float (3.5) — a checker/runtime divergence. COERCE an Int
// argument to a Float at the boundary (lossless for |n| < 2^53), so the param genuinely holds a float and
// the model is sound. A non-numeric argument (string/list/…) fails closed, exactly like the int guard.
fn anubis_coerce_float_param(v: AnubisValue, name: &str) -> AnubisValue {
    match v {
        AnubisValue::Int(n) => AnubisValue::Float(n as f64),
        AnubisValue::Float(_) => v,
        _ => panic!("ANUBIS_TYPE_VIOLATION: float parameter `{}` received a non-numeric value at runtime; the checker models it as an f64, so a string/list/other argument is fail-closed rather than silently mis-proved", name),
    }
}
// Same coercion on a float-typed function's RETURN value (the model is only sound if a float-returning
// function actually yields a float): coerce an Int return to a Float, fail closed on a non-numeric.
fn anubis_coerce_float_ret(v: AnubisValue, name: &str) -> AnubisValue {
    match v {
        AnubisValue::Int(n) => AnubisValue::Float(n as f64),
        AnubisValue::Float(_) => v,
        _ => panic!("ANUBIS_TYPE_VIOLATION: function `{}` declares a float return type but returned a non-numeric value at runtime; the checker models its result as an f64, so this is fail-closed rather than silently mis-proved", name),
    }
}
// A1 (task #50) — UNSIGNED fixed-width PARAM boundary coercion. An `u8`/`u16`/`u32` parameter is made
// a GENUINE [0, 2^w) value at entry, so the checker may soundly assume that range (dropping the
// `requires(x >= 0)` tax). The mask `n & (2^w - 1)` is exactly the low-`w` bits: −1 → 2^w−1, an
// oversized value → its value mod 2^w — always landing in [0, 2^w) ⊂ [0, 2^63), the non-negative
// signed range the solver's `bvsge`/`bvsle` model. `width` is 8/16/32 (never 64: masking a u64 into
// an i64 slot cannot represent [2^63, 2^64), so u64 keeps unbounded-i64 semantics). Fails closed on
// a non-integer, exactly like `anubis_require_int`. The int→f64 boundary coercion (task #34) is the
// float twin of this. Only PARAMS are masked (not returns/locals): that is where the tax lives, and
// `u32` is Anubis's default integer spelling, so masking returns would change every program that
// returns a negative/overflowing value from a `-> u32` function. A caller passing an out-of-range
// argument is handled in the checker by masking the arg when it is substituted into the callee's
// `requires`/`ensures` (so the composed contract matches this runtime mask — see mod.rs).
fn anubis_coerce_uint_param(v: AnubisValue, name: &str, width: u32) -> AnubisValue {
    match v {
        AnubisValue::Int(n) => {
            let mask: i64 = (1i64 << width) - 1;
            AnubisValue::Int(n & mask)
        }
        _ => panic!("ANUBIS_TYPE_VIOLATION: unsigned parameter `{}` received a non-integer value at runtime; the checker models it as a [0, 2^{}) integer, so a float/string/other argument is fail-closed rather than silently mis-proved", name, width),
    }
}
// STRUCT-FIELD numeric-kind guards (task #34 dual, extended to the construction boundary). They are
// deliberately GENTLER than the param/return guards above, because a struct field's declared type is
// unreliable: the parser stores a list type `[int]` as its element `int` (the brackets are dropped), so a
// genuine LIST field looks integer-typed. We therefore act on the VALUE and enforce ONLY the confirmed
// numeric-kind smuggle — a Float in an INTEGER field (float→int: the solver's QF_BV `bvsdiv` model would
// diverge from the runtime's float `/`) fails closed; every other value (Int, List, String, Bool, Struct)
// passes UNCHANGED, so a list/string/bool in an int-typed field (the parser quirk, or a dynamic value the
// solver does not model as a scalar int) is not spuriously trapped.
fn anubis_field_require_int(v: AnubisValue, name: &str) -> AnubisValue {
    if matches!(v, AnubisValue::Float(_)) {
        panic!("ANUBIS_TYPE_VIOLATION: integer field `{}` received a float value at runtime; the checker models it as an i64, so a float is fail-closed rather than silently mis-proved", name);
    }
    v
}
// The float dual: COERCE an Int value in a FLOAT field to a Float (so the QF_FP model is sound and
// `P{x: 7}` binds 7.0, exactly like a float param `f(7)`); pass every other value UNCHANGED (a list/string
// in a float-typed field is the parser quirk or a dynamic value — not the int→float smuggle).
fn anubis_field_coerce_float(v: AnubisValue, _name: &str) -> AnubisValue {
    match v {
        AnubisValue::Int(n) => AnubisValue::Float(n as f64),
        other => other,
    }
}
fn anubis_panic(msg: AnubisValue) -> AnubisValue { panic!("ANUBIS_PANIC: {}", msg.display_string()); }

fn anubis_input() -> AnubisValue {
    use std::io::BufRead;
    let mut line = String::new();
    let _ = std::io::stdin().lock().read_line(&mut line);
    while line.ends_with('\n') || line.ends_with('\r') { line.pop(); }
    anubis_mk_str(line)
}
fn anubis_args() -> AnubisValue {
    anubis_mk_list(std::env::args().skip(1).map(anubis_mk_str).collect())
}

// ---- Governed capability I/O (Phase-3 C3) — additive builtins; AnubisValue path unchanged ----
fn anubis_read_file(path: AnubisValue) -> AnubisValue {
    match std::fs::read_to_string(path.display_string()) {
        Ok(s) => anubis_mk_str(s),
        Err(e) => panic!("ANUBIS_IO_ERROR: read_file({}): {}", path.display_string(), e),
    }
}
fn anubis_write_file(path: AnubisValue, contents: AnubisValue) -> AnubisValue {
    match std::fs::write(path.display_string(), contents.display_string()) {
        Ok(()) => AnubisValue::Int(0),
        Err(e) => panic!("ANUBIS_IO_ERROR: write_file({}): {}", path.display_string(), e),
    }
}
/// Unlink a path. Shares the `fs.write` capability (filesystem mutation). Missing path is success
/// (idempotent destroy). Returns 0 on success, panics only on hard errors (permission, etc.).
fn anubis_delete_file(path: AnubisValue) -> AnubisValue {
    let p = path.display_string();
    match std::fs::remove_file(&p) {
        Ok(()) => AnubisValue::Int(0),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => AnubisValue::Int(0),
        Err(e) => panic!("ANUBIS_IO_ERROR: delete_file({}): {}", p, e),
    }
}
// Capability mint/export/Keychain-SE bind: see keychain_se_runtime.inc.rs (injected after core).

/// Consume a capability token. Linearity is checked at `check --verified`; runtime is the
/// authorized use-once sink so programs with caps lower and execute.
fn anubis_cap_use(cap: AnubisValue) -> AnubisValue {
    let _ = cap;
    AnubisValue::Int(0)
}
/// Confidentiality label mint (checker-side leg-1). Runtime is identity — the secret type system
/// and egress analysis run at check time.
fn anubis_secret_source(v: AnubisValue) -> AnubisValue {
    v
}
fn anubis_open(path: AnubisValue) -> AnubisValue {
    // `open` is a path-existence / openability probe that returns the path string on success
    // (contents are read via read_file). Fail-closed on missing/unreadable paths.
    match std::fs::File::open(path.display_string()) {
        Ok(_) => anubis_mk_str(path.display_string()),
        Err(e) => panic!("ANUBIS_IO_ERROR: open({}): {}", path.display_string(), e),
    }
}
fn anubis_time_now() -> AnubisValue {
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    AnubisValue::Int(secs)
}
fn anubis_rand_gen() -> AnubisValue {
    // Prefer getrandom when available at compile of the generated binary; fall back to a
    // process-local seed from the clock so the program still runs without the crate.
    let mut buf = [0u8; 8];
    // Seed from clock + pid so successive runs differ without an external dep.
    let t = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0);
    let mixed = t
        ^ ((std::process::id() as u64) << 32)
        ^ 0x9e37_79b9_7f4a_7c15;
    buf.copy_from_slice(&mixed.to_le_bytes());
    AnubisValue::Int(i64::from_le_bytes(buf))
}
fn anubis_net_send(host: AnubisValue, port: AnubisValue, payload: AnubisValue) -> AnubisValue {
    use std::io::Write;
    use std::net::TcpStream;
    let addr = format!("{}:{}", host.display_string(), port.as_i64());
    match TcpStream::connect(&addr) {
        Ok(mut stream) => {
            if let Err(e) = stream.write_all(payload.display_string().as_bytes()) {
                panic!("ANUBIS_IO_ERROR: send({}): {}", addr, e);
            }
            AnubisValue::Int(0)
        }
        Err(e) => panic!("ANUBIS_IO_ERROR: send({}): {}", addr, e),
    }
}
fn anubis_net_connect(host: AnubisValue, port: AnubisValue) -> AnubisValue {
    use std::net::TcpStream;
    let addr = format!("{}:{}", host.display_string(), port.as_i64());
    match TcpStream::connect(&addr) {
        Ok(_) => anubis_mk_str(addr),
        Err(e) => panic!("ANUBIS_IO_ERROR: connect({}): {}", addr, e),
    }
}
// HTTP: cleartext over pure std TCP; HTTPS via host `curl` (system TLS TCB — SecureTransport/
// LibreSSL/OpenSSL depending on host). Same honesty as package-registry HTTPS. No DIY TLS.
// URL shape: http(s)://host[:port]/path[?query]] — path defaults to `/`.
fn anubis_http_parse_url(url: &str) -> (bool, String, u16, String) {
    let (https, rest) = if let Some(r) = url.strip_prefix("https://") {
        (true, r)
    } else if let Some(r) = url.strip_prefix("http://") {
        (false, r)
    } else {
        panic!(
            "ANUBIS_IO_ERROR: http_get/http_post URL must start with http:// or https:// (got {})",
            url
        );
    };
    let (authority, path) = match rest.find('/') {
        Some(i) => (&rest[..i], rest[i..].to_string()),
        None => (rest, "/".to_string()),
    };
    if authority.is_empty() {
        panic!("ANUBIS_IO_ERROR: http URL missing host: {}", url);
    }
    let default_port = if https { 443u16 } else { 80u16 };
    let (host, port) = if let Some(i) = authority.rfind(':') {
        if authority.starts_with('[') {
            panic!(
                "ANUBIS_IO_ERROR: http_get/http_post does not parse IPv6 authorities: {}",
                url
            );
        }
        let (h, p) = authority.split_at(i);
        let pnum: u16 = p[1..].parse().unwrap_or_else(|_| {
            panic!("ANUBIS_IO_ERROR: invalid port in URL: {}", url);
        });
        (h.to_string(), pnum)
    } else {
        (authority.to_string(), default_port)
    };
    let path = if path.is_empty() { "/".to_string() } else { path };
    (https, host, port, path)
}
/// HTTPS via host curl — body only on stdout; fail-closed on non-zero exit.
fn anubis_http_via_curl(method: &str, url: &str, body: Option<&str>) -> AnubisValue {
    use std::io::Write;
    use std::process::{Command, Stdio};
    let mut cmd = Command::new("curl");
    cmd.args(["-fsSL", "--max-time", "30", "-X", method, url]);
    // SECURITY (#75): the request body is written to curl's STDIN and referenced by the FIXED literal
    // `@-`, never passed inline as `--data-binary <body>`. curl interprets a `@`-prefixed data value as
    // a FILENAME, so an inline body that merely BEGINS with `@` made curl read an arbitrary LOCAL FILE
    // and transmit it — escalating the `net.send` capability into arbitrary local file read plus
    // egress, with no fs.read capability and no diagnostic. Because `@-` is a constant, no
    // program-controlled string can reach curl's filename parser at all.
    if body.is_some() {
        cmd.args([
            "-H",
            "Content-Type: application/octet-stream",
            "--data-binary",
            "@-",
        ]);
        cmd.stdin(Stdio::piped());
    } else {
        cmd.stdin(Stdio::null());
    }
    cmd.stdout(Stdio::piped());
    cmd.stderr(Stdio::piped());
    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => panic!(
            "ANUBIS_IO_ERROR: https requires host `curl` on PATH (system TLS TCB): {}",
            e
        ),
    };
    if let Some(b) = body {
        // Dropping the handle closes the pipe so curl sees EOF and stops reading.
        if let Some(mut si) = child.stdin.take() {
            if let Err(e) = si.write_all(b.as_bytes()) {
                panic!("ANUBIS_IO_ERROR: https curl body write failed: {}", e);
            }
        }
    }
    match child.wait_with_output() {
        Ok(out) if out.status.success() => {
            anubis_mk_str(String::from_utf8_lossy(&out.stdout).into_owned())
        }
        Ok(out) => panic!(
            "ANUBIS_IO_ERROR: https curl failed (exit {:?}): {}",
            out.status.code(),
            String::from_utf8_lossy(&out.stderr)
        ),
        Err(e) => panic!(
            "ANUBIS_IO_ERROR: https requires host `curl` on PATH (system TLS TCB): {}",
            e
        ),
    }
}
fn anubis_http_exchange(method: &str, url: AnubisValue, body: Option<AnubisValue>) -> AnubisValue {
    use std::io::{Read, Write};
    use std::net::TcpStream;
    use std::time::Duration;
    let url_s = url.display_string();
    let (https, host, port, path) = anubis_http_parse_url(&url_s);
    let body_s = body.map(|b| b.display_string());
    if https {
        // Rebuild absolute URL for curl (preserves original form).
        return anubis_http_via_curl(method, &url_s, body_s.as_deref());
    }
    let addr = format!("{}:{}", host, port);
    let mut stream = match TcpStream::connect(&addr) {
        Ok(s) => s,
        Err(e) => panic!("ANUBIS_IO_ERROR: http connect({}): {}", addr, e),
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(30)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(30)));
    let body_owned = body_s.unwrap_or_default();
    let req = if method == "POST" {
        format!(
            "POST {} HTTP/1.0\r\nHost: {}\r\nContent-Type: application/octet-stream\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
            path,
            host,
            body_owned.len(),
            body_owned
        )
    } else {
        format!(
            "GET {} HTTP/1.0\r\nHost: {}\r\nConnection: close\r\n\r\n",
            path, host
        )
    };
    if let Err(e) = stream.write_all(req.as_bytes()) {
        panic!("ANUBIS_IO_ERROR: http write({}): {}", addr, e);
    }
    let mut buf = Vec::new();
    if let Err(e) = stream.read_to_end(&mut buf) {
        panic!("ANUBIS_IO_ERROR: http read({}): {}", addr, e);
    }
    let raw = String::from_utf8_lossy(&buf);
    if let Some(idx) = raw.find("\r\n\r\n") {
        anubis_mk_str(raw[idx + 4..].to_string())
    } else if let Some(idx) = raw.find("\n\n") {
        anubis_mk_str(raw[idx + 2..].to_string())
    } else {
        panic!(
            "ANUBIS_IO_ERROR: http response missing header/body separator from {}",
            addr
        );
    }
}
fn anubis_http_get(url: AnubisValue) -> AnubisValue {
    anubis_http_exchange("GET", url, None)
}
fn anubis_http_post(url: AnubisValue, body: AnubisValue) -> AnubisValue {
    anubis_http_exchange("POST", url, Some(body))
}

// ---- Higher-order functions over closures ----

fn anubis_map(list: AnubisValue, f: AnubisValue) -> AnubisValue {
    anubis_mk_list(anubis_iter(list).into_iter().map(|x| f.call_closure(vec![x])).collect())
}
fn anubis_filter(list: AnubisValue, f: AnubisValue) -> AnubisValue {
    anubis_mk_list(anubis_iter(list).into_iter().filter(|x| f.call_closure(vec![x.clone()]).as_bool()).collect())
}
// `reduce(list, closure, seed)` folds `closure(acc, x)` over the list from `seed`. ORDER-AGNOSTIC on the
// two non-list arguments: the closure may be the 2nd arg (Anubis-native `reduce(list, f, seed)`) OR the
// 3rd (the JS/Rust-fold-natural `reduce(list, seed, f)`). Whichever argument IS a closure is the fold
// function; the other is the seed. This fixes the reported crash where the seed-first order sent an int
// where a closure was expected. If NEITHER is a closure it is a genuine type error with a message that
// names both accepted forms (was a bare `expected closure, got int`).
fn anubis_reduce(list: AnubisValue, a: AnubisValue, b: AnubisValue) -> AnubisValue {
    let (f, mut acc) = match (a.is_closure(), b.is_closure()) {
        (true, _) => (a, b),
        (false, true) => (b, a),
        (false, false) => panic!(
            "ANUBIS_TYPE_ERROR: reduce expects a closure argument — reduce(list, closure, seed) or reduce(list, seed, closure)"
        ),
    };
    for x in anubis_iter(list) { acc = f.call_closure(vec![acc, x]); }
    acc
}
// Seedless `reduce(list, closure)`: the FIRST element seeds the accumulator and the closure folds the
// rest (standard seedless reduce, mirroring the semantics used when no initial value is supplied). An
// empty list has no defined seed — fail closed (do not invent Int(0); that is only the additive
// identity for numeric folds and is wrong for non-numeric reduce). Use reduce(list, closure, seed).
fn anubis_reduce2(list: AnubisValue, f: AnubisValue) -> AnubisValue {
    if !f.is_closure() {
        panic!("ANUBIS_TYPE_ERROR: reduce(list, closure) expects a closure as the second argument, got {}", f.type_name());
    }
    let mut it = anubis_iter(list).into_iter();
    let mut acc = match it.next() {
        Some(x) => x,
        None => panic!("ANUBIS_EMPTY_COLLECTION: reduce(list, closure) has no seed — the list is empty; use reduce(list, closure, seed) to supply one"),
    };
    for x in it { acc = f.call_closure(vec![acc, x]); }
    acc
}
fn anubis_each(list: AnubisValue, f: AnubisValue) -> AnubisValue {
    for x in anubis_iter(list) { let _ = f.call_closure(vec![x]); }
    AnubisValue::Int(0)
}
fn anubis_find(list: AnubisValue, f: AnubisValue) -> AnubisValue {
    for x in anubis_iter(list) { if f.call_closure(vec![x.clone()]).as_bool() { return x; } }
    panic!("ANUBIS_NO_MATCH: find() — no element satisfies the predicate (guard with any(xs, pred) first, or use position(xs, pred) if you only need the index)")
}
fn anubis_any(list: AnubisValue, f: AnubisValue) -> AnubisValue {
    AnubisValue::Bool(anubis_iter(list).into_iter().any(|x| f.call_closure(vec![x]).as_bool()))
}
fn anubis_all(list: AnubisValue, f: AnubisValue) -> AnubisValue {
    AnubisValue::Bool(anubis_iter(list).into_iter().all(|x| f.call_closure(vec![x]).as_bool()))
}
fn anubis_count_by(list: AnubisValue, f: AnubisValue) -> AnubisValue {
    AnubisValue::Int(anubis_iter(list).into_iter().filter(|x| f.call_closure(vec![x.clone()]).as_bool()).count() as i64)
}
fn anubis_sort_by(list: AnubisValue, f: AnubisValue) -> AnubisValue {
    match list {
        AnubisValue::List(items) => {
            let mut items = anubis_rc_take(items);
            items.sort_by(|a, b| {
                let ka = f.call_closure(vec![a.clone()]);
                let kb = f.call_closure(vec![b.clone()]);
                anubis_value_cmp(&ka, &kb)
            });
            anubis_mk_list(items)
        }
        // Fail CLOSED on a non-list first argument (was `other => other`, which silently returned the
        // argument unsorted — leaking a `<closure>` on a swapped `sort_by(closure, list)` call, or a
        // string/map unchanged — an HOF-audit silent-wrong-output bug).
        other => panic!("ANUBIS_TYPE_ERROR: sort_by expects a list as its first argument, got {}", other.type_name()),
    }
}
fn anubis_apply(f: AnubisValue, args: AnubisValue) -> AnubisValue {
    match args {
        AnubisValue::List(items) => f.call_closure(anubis_rc_take(items)),
        other => f.call_closure(vec![other]),
    }
}

/// Build a map from literal entries, deduplicating keys (last value wins) so `{ "a": 1, "a": 2 }`
/// is a well-formed single-entry map.
fn anubis_map_lit(pairs: Vec<(String, AnubisValue)>) -> AnubisValue {
    let mut out: Vec<(String, AnubisValue)> = Vec::new();
    for (k, v) in pairs {
        if let Some(slot) = out.iter_mut().find(|(kk, _)| kk == &k) {
            slot.1 = v;
        } else {
            out.push((k, v));
        }
    }
    anubis_mk_map(out)
}

/// Materialize a value's iteration elements: list items, string characters, or map keys.
fn anubis_iter(v: AnubisValue) -> Vec<AnubisValue> {
    match v {
        AnubisValue::List(items) => anubis_rc_take(items),
        AnubisValue::Str(s) => s.chars().map(|c| anubis_mk_str(c.to_string())).collect(),
        AnubisValue::Map(m) => anubis_rc_take(m).into_iter().map(|(k, _)| anubis_mk_str(k)).collect(),
        // A CLOSURE is never iterable — reaching here means a higher-order call was given a closure
        // where the collection was expected (the classic swapped-argument mistake, e.g.
        // `min_by(|x| x, list)`). Fail CLOSED with a message that names the likely cause, instead of
        // the old `other => vec![other]` which silently wrapped the closure as a 1-element sequence and
        // returned it unexamined (a silent-wrong-output bug the HOF audit surfaced).
        AnubisValue::Closure(_) => panic!(
            "ANUBIS_TYPE_ERROR: a closure is not iterable — check the argument order (the collection must come before the closure)"
        ),
        other => panic!(
            "ANUBIS_TYPE_ERROR: expected a list, string, or map, got {} — check the argument order or that this value is actually a collection",
            other.type_name()
        ),
    }
}

// ---- math ----
fn anubis_sin(x: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "sin"); AnubisValue::Float(x.as_f64().sin()) }
fn anubis_cos(x: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "cos"); AnubisValue::Float(x.as_f64().cos()) }
fn anubis_tan(x: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "tan"); AnubisValue::Float(x.as_f64().tan()) }
fn anubis_asin(x: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "asin"); AnubisValue::Float(x.as_f64().asin()) }
fn anubis_acos(x: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "acos"); AnubisValue::Float(x.as_f64().acos()) }
fn anubis_atan(x: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "atan"); AnubisValue::Float(x.as_f64().atan()) }
fn anubis_atan2(y: AnubisValue, x: AnubisValue) -> AnubisValue { anubis_require_numeric(&y, "atan2"); anubis_require_numeric(&x, "atan2"); AnubisValue::Float(y.as_f64().atan2(x.as_f64())) }
fn anubis_exp(x: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "exp"); AnubisValue::Float(x.as_f64().exp()) }
fn anubis_ln(x: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "ln"); AnubisValue::Float(x.as_f64().ln()) }
fn anubis_log10(x: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "log10"); AnubisValue::Float(x.as_f64().log10()) }
fn anubis_log2(x: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "log2"); AnubisValue::Float(x.as_f64().log2()) }
fn anubis_logb(x: AnubisValue, base: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "log"); anubis_require_numeric(&base, "log"); AnubisValue::Float(x.as_f64().log(base.as_f64())) }
fn anubis_cbrt(x: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "cbrt"); AnubisValue::Float(x.as_f64().cbrt()) }
fn anubis_hypot(x: AnubisValue, y: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "hypot"); anubis_require_numeric(&y, "hypot"); AnubisValue::Float(x.as_f64().hypot(y.as_f64())) }
fn anubis_trunc(x: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "trunc"); match x { AnubisValue::Int(n) => AnubisValue::Int(n), _ => AnubisValue::Int(x.as_f64().trunc() as i64) } }
fn anubis_sign(x: AnubisValue) -> AnubisValue { anubis_require_numeric(&x, "sign"); let v = x.as_f64(); AnubisValue::Int(if v > 0.0 { 1 } else if v < 0.0 { -1 } else { 0 }) }
fn anubis_clamp(x: AnubisValue, lo: AnubisValue, hi: AnubisValue) -> AnubisValue {
    anubis_require_numeric(&x, "clamp");
    anubis_require_numeric(&lo, "clamp");
    anubis_require_numeric(&hi, "clamp");
    if x.is_float() || lo.is_float() || hi.is_float() {
        let (lo_f, hi_f) = (lo.as_f64(), hi.as_f64());
        if lo_f > hi_f {
            panic!("ANUBIS_INVALID_ARGUMENT: clamp bounds are inverted — lo ({}) > hi ({})", lo_f, hi_f);
        }
        AnubisValue::Float(x.as_f64().max(lo_f).min(hi_f))
    } else {
        let (lo_i, hi_i) = (lo.as_i64(), hi.as_i64());
        if lo_i > hi_i {
            panic!("ANUBIS_INVALID_ARGUMENT: clamp bounds are inverted — lo ({}) > hi ({})", lo_i, hi_i);
        }
        AnubisValue::Int(x.as_i64().max(lo_i).min(hi_i))
    }
}
fn anubis_pi() -> AnubisValue { AnubisValue::Float(std::f64::consts::PI) }
fn anubis_e() -> AnubisValue { AnubisValue::Float(std::f64::consts::E) }
fn anubis_factorial(n: AnubisValue) -> AnubisValue {
    // Reject soft-coerced strings (`factorial("5")` used to return 120 via as_i64).
    let n_raw = match n {
        AnubisValue::Int(v) => v,
        other => panic!(
            "ANUBIS_TYPE_ERROR: factorial expects an int argument, got {}",
            other.type_name()
        ),
    };
    if n_raw < 0 {
        panic!("ANUBIS_DOMAIN_ERROR: factorial is undefined for negative integers, got {}", n_raw);
    }
    let n = n_raw;
    let mut acc: i64 = 1;
    let mut i: i64 = 2;
    while i <= n {
        acc = match acc.checked_mul(i) {
            Some(v) => v,
            None => panic!("ANUBIS_OVERFLOW: factorial({}) overflows i64 (i64::MAX is 9223372036854775807, reached between 20! and 21!)", n),
        };
        i += 1;
    }
    AnubisValue::Int(acc)
}

// ---- strings ----
fn anubis_chars(s: AnubisValue) -> AnubisValue {
    anubis_mk_list(s.display_string().chars().map(|c| anubis_mk_str(c.to_string())).collect())
}
fn anubis_words(s: AnubisValue) -> AnubisValue {
    anubis_mk_list(s.display_string().split_whitespace().map(|w| anubis_mk_str(w.to_string())).collect())
}
fn anubis_lines(s: AnubisValue) -> AnubisValue {
    anubis_mk_list(s.display_string().lines().map(|l| anubis_mk_str(l.to_string())).collect())
}
fn anubis_capitalize(s: AnubisValue) -> AnubisValue {
    let s = s.display_string();
    let mut ch = s.chars();
    match ch.next() {
        Some(f) => anubis_mk_str(f.to_uppercase().collect::<String>() + &ch.as_str().to_lowercase()),
        None => anubis_mk_str(String::new()),
    }
}
fn anubis_pad(s: AnubisValue, width: AnubisValue, pad: AnubisValue, at_start: bool) -> AnubisValue {
    let s = s.display_string();
    // Was `.max(0)` — negative width silently became a no-op (Phase-5 M–Z SILENT_WRONG).
    let w_raw = width.as_i64();
    if w_raw < 0 {
        panic!("ANUBIS_INVALID_ARGUMENT: pad width must be non-negative, got {}", w_raw);
    }
    let w = w_raw as usize;
    let p = { let ps = pad.display_string(); if ps.is_empty() { " ".to_string() } else { ps } };
    let have = s.chars().count();
    if have >= w { return anubis_mk_str(s); }
    let mut fill = String::new();
    while fill.chars().count() < w - have { fill.push_str(&p); }
    let fill: String = fill.chars().take(w - have).collect();
    anubis_mk_str(if at_start { format!("{}{}", fill, s) } else { format!("{}{}", s, fill) })
}

// ---- lists ----
fn anubis_zip(a: AnubisValue, b: AnubisValue) -> AnubisValue {
    let bv = anubis_iter(b);
    anubis_mk_list(anubis_iter(a).into_iter().zip(bv).map(|(x, y)| anubis_mk_list(vec![x, y])).collect())
}
fn anubis_enumerate(a: AnubisValue) -> AnubisValue {
    anubis_mk_list(anubis_iter(a).into_iter().enumerate().map(|(i, x)| anubis_mk_list(vec![AnubisValue::Int(i as i64), x])).collect())
}
fn anubis_flatten(a: AnubisValue) -> AnubisValue {
    let mut out = Vec::new();
    for x in anubis_iter(a) { for y in anubis_iter(x) { out.push(y); } }
    anubis_mk_list(out)
}
fn anubis_flat_map(a: AnubisValue, f: AnubisValue) -> AnubisValue {
    let mut out = Vec::new();
    for x in anubis_iter(a) { for y in anubis_iter(f.call_closure(vec![x])) { out.push(y); } }
    anubis_mk_list(out)
}
fn anubis_unique(a: AnubisValue) -> AnubisValue {
    let mut out: Vec<AnubisValue> = Vec::new();
    for x in anubis_iter(a) {
        // Deduplicate by structural equality (matching `==`), not display form: `1` and `"1"`
        // are distinct, while `1` and `1.0` are the same.
        if !out.iter().any(|y| anubis_value_eq(y, &x)) { out.push(x); }
    }
    anubis_mk_list(out)
}
fn anubis_take(a: AnubisValue, n: AnubisValue) -> AnubisValue {
    let n_raw = n.as_i64();
    if n_raw < 0 {
        panic!("ANUBIS_INVALID_ARGUMENT: take count must be non-negative, got {}", n_raw);
    }
    let n = n_raw as usize;
    anubis_mk_list(anubis_iter(a).into_iter().take(n).collect())
}
fn anubis_drop(a: AnubisValue, n: AnubisValue) -> AnubisValue {
    let n_raw = n.as_i64();
    if n_raw < 0 {
        panic!("ANUBIS_INVALID_ARGUMENT: drop count must be non-negative, got {}", n_raw);
    }
    let n = n_raw as usize;
    anubis_mk_list(anubis_iter(a).into_iter().skip(n).collect())
}
fn anubis_take_while(a: AnubisValue, f: AnubisValue) -> AnubisValue {
    let mut out = Vec::new();
    for x in anubis_iter(a) {
        if f.call_closure(vec![x.clone()]).as_bool() { out.push(x); } else { break; }
    }
    anubis_mk_list(out)
}
fn anubis_drop_while(a: AnubisValue, f: AnubisValue) -> AnubisValue {
    let items = anubis_iter(a);
    let mut i = 0;
    while i < items.len() && f.call_closure(vec![items[i].clone()]).as_bool() { i += 1; }
    anubis_mk_list(items[i..].to_vec())
}
fn anubis_chunk(a: AnubisValue, n: AnubisValue) -> AnubisValue {
    let n_raw = n.as_i64();
    if n_raw <= 0 {
        panic!("ANUBIS_INVALID_ARGUMENT: chunk size must be positive, got {}", n_raw);
    }
    let n = n_raw as usize;
    anubis_mk_list(anubis_iter(a).chunks(n).map(|c| anubis_mk_list(c.to_vec())).collect())
}
fn anubis_window(a: AnubisValue, n: AnubisValue) -> AnubisValue {
    let n_raw = n.as_i64();
    if n_raw <= 0 {
        panic!("ANUBIS_INVALID_ARGUMENT: window size must be positive, got {}", n_raw);
    }
    let n = n_raw as usize;
    let items = anubis_iter(a);
    if items.len() < n { return anubis_mk_list(vec![]); }
    anubis_mk_list(items.windows(n).map(|w| anubis_mk_list(w.to_vec())).collect())
}
fn anubis_position(a: AnubisValue, f: AnubisValue) -> AnubisValue {
    for (i, x) in anubis_iter(a).into_iter().enumerate() {
        if f.call_closure(vec![x]).as_bool() { return AnubisValue::Int(i as i64); }
    }
    AnubisValue::Int(-1)
}
fn anubis_product(a: AnubisValue) -> AnubisValue {
    let items = anubis_iter(a);
    if items.iter().any(|v| v.is_float()) {
        AnubisValue::Float(items.iter().map(|v| v.as_f64()).product())
    } else {
        AnubisValue::Int(items.iter().map(|v| v.as_i64()).product())
    }
}
fn anubis_first(a: AnubisValue) -> AnubisValue {
    anubis_iter(a).into_iter().next().unwrap_or_else(|| {
        panic!("ANUBIS_EMPTY_COLLECTION: first has no element — the collection is empty (use is_empty(xs) to guard)")
    })
}
fn anubis_last(a: AnubisValue) -> AnubisValue {
    anubis_iter(a).into_iter().last().unwrap_or_else(|| {
        panic!("ANUBIS_EMPTY_COLLECTION: last has no element — the collection is empty (use is_empty(xs) to guard)")
    })
}
/// True when a collection has no elements (empty ⟺ `len == 0`, matching `len`'s type coverage).
/// Lets programs guard `pop`/`last`/index access without hand-writing `len(xs) > 0` everywhere.
fn anubis_is_empty(v: AnubisValue) -> AnubisValue {
    let n = match &v {
        AnubisValue::List(l) => l.len(),
        AnubisValue::Str(s) => s.chars().count(),
        AnubisValue::Map(m) => m.len(),
        AnubisValue::Struct { fields, .. } => fields.len(),
        AnubisValue::Enum { fields, .. } => fields.len(),
        // Was `_ => 0` so `is_empty(42)` / `is_empty(true)` returned true (Phase-5 SILENT_WRONG).
        other => panic!(
            "ANUBIS_TYPE_ERROR: is_empty expects a list, string, map, struct, or enum, got {}",
            other.type_name()
        ),
    };
    AnubisValue::Bool(n == 0)
}
fn anubis_concat(a: AnubisValue, b: AnubisValue) -> AnubisValue {
    let mut out = anubis_iter(a);
    out.extend(anubis_iter(b));
    anubis_mk_list(out)
}
fn anubis_min_by(a: AnubisValue, f: AnubisValue) -> AnubisValue {
    anubis_iter(a).into_iter()
        .min_by(|x, y| anubis_value_cmp(&f.call_closure(vec![x.clone()]), &f.call_closure(vec![y.clone()])))
        .unwrap_or_else(|| panic!("ANUBIS_EMPTY_COLLECTION: min_by has no element — the collection is empty (use is_empty(xs) to guard)"))
}
fn anubis_max_by(a: AnubisValue, f: AnubisValue) -> AnubisValue {
    anubis_iter(a).into_iter()
        .max_by(|x, y| anubis_value_cmp(&f.call_closure(vec![x.clone()]), &f.call_closure(vec![y.clone()])))
        .unwrap_or_else(|| panic!("ANUBIS_EMPTY_COLLECTION: max_by has no element — the collection is empty (use is_empty(xs) to guard)"))
}
fn anubis_partition(a: AnubisValue, f: AnubisValue) -> AnubisValue {
    let mut yes = Vec::new();
    let mut no = Vec::new();
    for x in anubis_iter(a) {
        if f.call_closure(vec![x.clone()]).as_bool() { yes.push(x); } else { no.push(x); }
    }
    anubis_mk_list(vec![anubis_mk_list(yes), anubis_mk_list(no)])
}

// ---- maps ----
fn anubis_entries(m: AnubisValue) -> AnubisValue {
    match m {
        AnubisValue::Map(m) => anubis_mk_list(anubis_rc_take(m).into_iter().map(|(k, v)| anubis_mk_list(vec![anubis_mk_str(k), v])).collect()),
        other => panic!(
            "ANUBIS_TYPE_ERROR: entries expects a map, got {}",
            other.type_name()
        ),
    }
}
// The fail-SOFT counterpart to fail-closed `coll[key]`: returns the element if the key is present
// (map) or the index is in range (list/string, negatives allowed), else the caller's `default`.
fn anubis_get(m: AnubisValue, k: AnubisValue, default: AnubisValue) -> AnubisValue {
    match &m {
        AnubisValue::Map(mm) => {
            let key = k.display_string();
            mm.iter().find(|(kk, _)| kk == &key).map(|(_, v)| v.clone()).unwrap_or(default)
        }
        AnubisValue::List(v) => match anubis_norm_index(k.as_i64(), v.len()) {
            Some(idx) => v[idx].clone(),
            None => default,
        },
        AnubisValue::Str(s) => {
            let chars: Vec<char> = s.chars().collect();
            match anubis_norm_index(k.as_i64(), chars.len()) {
                Some(idx) => anubis_mk_str(chars[idx].to_string()),
                None => default,
            }
        }
        _ => default,
    }
}
fn anubis_merge(a: AnubisValue, b: AnubisValue) -> AnubisValue {
    let mut out = match a {
        AnubisValue::Map(m) => anubis_rc_take(m),
        other => panic!(
            "ANUBIS_TYPE_ERROR: merge expects a map as its first argument, got {}",
            other.type_name()
        ),
    };
    match b {
        AnubisValue::Map(bm) => {
            for (k, v) in anubis_rc_take(bm) {
                if let Some(slot) = out.iter_mut().find(|(kk, _)| kk == &k) { slot.1 = v; } else { out.push((k, v)); }
            }
        }
        other => panic!(
            "ANUBIS_TYPE_ERROR: merge expects a map as its second argument, got {}",
            other.type_name()
        ),
    }
    anubis_mk_map(out)
}
fn anubis_map_values(m: AnubisValue, f: AnubisValue) -> AnubisValue {
    match m {
        AnubisValue::Map(mm) => anubis_mk_map(anubis_rc_take(mm).into_iter().map(|(k, v)| (k, f.call_closure(vec![v]))).collect()),
        // Fail CLOSED on a non-map first argument (was `other => other`, which silently returned e.g. a
        // list unchanged with the closure never applied — an HOF-audit silent-wrong-output bug).
        other => panic!("ANUBIS_TYPE_ERROR: map_values expects a map as its first argument, got {}", other.type_name()),
    }
}

// ---- functional ----
fn anubis_identity(x: AnubisValue) -> AnubisValue { x }
fn anubis_compose(f: AnubisValue, g: AnubisValue) -> AnubisValue {
    AnubisValue::Closure(std::rc::Rc::new(move |args: Vec<AnubisValue>| {
        let gx = g.call_closure(args);
        f.call_closure(vec![gx])
    }))
}
fn anubis_times(n: AnubisValue, f: AnubisValue) -> AnubisValue {
    // Fail CLOSED when the count slot holds a closure — the swapped `times(closure, n)` mistake. Without
    // this, `n.as_i64()` coerced the closure to 0 and returned an empty list at exit 0 (a silent-wrong
    // HOF-audit bug). The canonical order is `times(count, closure)`.
    if n.is_closure() {
        panic!("ANUBIS_TYPE_ERROR: times expects a count as its first argument — times(count, closure), got a closure");
    }
    // Was `n.as_i64().max(0)` — `times(-1, f)` returned `[]` and `times("2", f)` soft-coerced the
    // string to 2 and ran the body (Phase-5 M–Z SILENT_WRONG).
    let n_raw = match n {
        AnubisValue::Int(v) => v,
        other => panic!(
            "ANUBIS_TYPE_ERROR: times expects an int count as its first argument, got {}",
            other.type_name()
        ),
    };
    if n_raw < 0 {
        panic!("ANUBIS_INVALID_ARGUMENT: times count must be non-negative, got {}", n_raw);
    }
    let n = n_raw;
    anubis_mk_list((0..n).map(|i| f.call_closure(vec![AnubisValue::Int(i)])).collect())
}

// CRYPTO_RUNTIME_INJECTED_BELOW — pure (guest) or audited crates (native run)

fn anubis_append_file(path: AnubisValue, contents: AnubisValue) -> AnubisValue {
    use std::io::Write;
    let p = path.display_string();
    let mut f = match std::fs::OpenOptions::new().create(true).append(true).open(&p) {
        Ok(f) => f,
        Err(e) => panic!("ANUBIS_IO_ERROR: append_file({}): {}", p, e),
    };
    if let Err(e) = write!(f, "{}", contents.display_string()) {
        panic!("ANUBIS_IO_ERROR: append_file({}): {}", p, e);
    }
    AnubisValue::Int(0)
}

fn anubis_env(name: AnubisValue) -> AnubisValue {
    match std::env::var(name.display_string()) {
        Ok(v) => anubis_mk_str(v),
        Err(_) => anubis_mk_str(String::new()),
    }
}


// Keychain / Secure Enclave bind for *non-exportable* capability tokens (native `anubis run` only).
//
// HONESTY (load-bearing):
// - Soft path always works: `__anubis_cap_ne_soft:<kind>:<nonce>`.
// - On macOS, mint tries Keychain generic-password storage (`__anubis_cap_ne_kc:…`) and, when
//   `ANUBIS_KEYCHAIN_SE=1`, a Secure Enclave–resident EC key handle (`__anubis_cap_ne_se:…`).
// - Success means "item/key created under the current process identity", NOT "signed app with
//   production SE ACL + attestation". Codesign + App Sandbox + keychain-access-groups still
//   required for host-enforced isolation (`apple_enforced_claim` remains false until signed).
// - Guest / non-macOS: soft only.

// Last NE mint bind mode for this process: "soft" | "kc" | "se" (not secret material).
static ANUBIS_LAST_NE_BIND: std::sync::Mutex<String> = std::sync::Mutex::new(String::new());

fn anubis_keychain_se_note_bind(mode: &str) {
    if let Ok(mut g) = ANUBIS_LAST_NE_BIND.lock() {
        *g = mode.to_string();
    }
}

/// Last `cap_acquire_nonexportable` bind mode for this process (`soft` / `kc` / `se`).
/// Does not take a token argument — not an export of capability material.
fn anubis_keychain_se_last_bind() -> AnubisValue {
    let s = ANUBIS_LAST_NE_BIND
        .lock()
        .map(|g| g.clone())
        .unwrap_or_default();
    if s.is_empty() {
        anubis_mk_str("none".to_string())
    } else {
        anubis_mk_str(s)
    }
}

/// Probe result: 0 = soft-only, 1 = Keychain bind available, 2 = Secure Enclave path available.
fn anubis_keychain_se_probe() -> AnubisValue {
    AnubisValue::Int(anubis_keychain_se_probe_i64())
}

fn anubis_keychain_se_probe_i64() -> i64 {
    #[cfg(target_os = "macos")]
    {
        if anubis_kc_se_available() {
            return 2;
        }
        if anubis_kc_keychain_available() {
            return 1;
        }
    }
    0
}

/// Mint an exportable capability (no Keychain bind — software token only).
fn anubis_cap_acquire(kind: AnubisValue) -> AnubisValue {
    anubis_mk_str(format!("__anubis_cap:{}", kind.display_string()))
}

/// Mint a *non-exportable* capability: prefer Keychain/SE bind on macOS, soft fallback.
fn anubis_cap_acquire_nonexportable(kind: AnubisValue) -> AnubisValue {
    let k = kind.display_string();
    #[cfg(target_os = "macos")]
    {
        if std::env::var_os("ANUBIS_KEYCHAIN_SE")
            .map(|v| v != "0" && v != "false")
            .unwrap_or(false)
        {
            if let Ok(tok) = anubis_kc_mint_se(&k) {
                anubis_keychain_se_note_bind("se");
                return anubis_mk_str(tok);
            }
        }
        // Default on macOS: try Keychain bind (opt out with ANUBIS_KEYCHAIN_CAPS=0).
        let want_kc = std::env::var_os("ANUBIS_KEYCHAIN_CAPS")
            .map(|v| v != "0" && v != "false")
            .unwrap_or(true);
        if want_kc {
            if let Ok(tok) = anubis_kc_mint_keychain(&k) {
                anubis_keychain_se_note_bind("kc");
                return anubis_mk_str(tok);
            }
        }
    }
    let nonce = anubis_kc_nonce();
    anubis_keychain_se_note_bind("soft");
    anubis_mk_str(format!("__anubis_cap_ne_soft:{k}:{nonce}"))
}

/// Language peel is identity on the token value. Optional Keychain delete on export when
/// `ANUBIS_KEYCHAIN_DELETE_ON_EXPORT=1` and the token is a `kc:` / `se:` bind.
fn anubis_cap_export(cap: AnubisValue, _reason: AnubisValue) -> AnubisValue {
    #[cfg(target_os = "macos")]
    {
        if std::env::var_os("ANUBIS_KEYCHAIN_DELETE_ON_EXPORT")
            .map(|v| v == "1" || v == "true")
            .unwrap_or(false)
        {
            let s = cap.display_string();
            let _ = anubis_kc_delete_token(&s);
        }
    }
    cap
}

fn anubis_kc_nonce() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let t = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("{:x}-{}", t, std::process::id())
}

// ── macOS Security.framework FFI ──────────────────────────────────────────────

#[cfg(target_os = "macos")]
#[link(name = "Security", kind = "framework")]
#[link(name = "CoreFoundation", kind = "framework")]
extern "C" {
    fn SecItemAdd(attributes: *const std::ffi::c_void, result: *mut *const std::ffi::c_void) -> i32;
    fn SecItemDelete(query: *const std::ffi::c_void) -> i32;
    fn SecItemCopyMatching(
        query: *const std::ffi::c_void,
        result: *mut *const std::ffi::c_void,
    ) -> i32;
    fn SecKeyCreateRandomKey(
        parameters: *const std::ffi::c_void,
        error: *mut *const std::ffi::c_void,
    ) -> *const std::ffi::c_void;
    fn SecKeyCopyPublicKey(key: *const std::ffi::c_void) -> *const std::ffi::c_void;
    fn SecKeyCopyExternalRepresentation(
        key: *const std::ffi::c_void,
        error: *mut *const std::ffi::c_void,
    ) -> *const std::ffi::c_void;
    fn CFDictionaryCreate(
        allocator: *const std::ffi::c_void,
        keys: *const *const std::ffi::c_void,
        values: *const *const std::ffi::c_void,
        num_values: isize,
        key_callbacks: *const std::ffi::c_void,
        value_callbacks: *const std::ffi::c_void,
    ) -> *const std::ffi::c_void;
    fn CFStringCreateWithCString(
        alloc: *const std::ffi::c_void,
        c_str: *const i8,
        encoding: u32,
    ) -> *const std::ffi::c_void;
    fn CFDataCreate(
        alloc: *const std::ffi::c_void,
        bytes: *const u8,
        length: isize,
    ) -> *const std::ffi::c_void;
    fn CFDataGetLength(data: *const std::ffi::c_void) -> isize;
    fn CFDataGetBytePtr(data: *const std::ffi::c_void) -> *const u8;
    fn CFRelease(cf: *const std::ffi::c_void);
    fn CFBooleanGetValue(boolean: *const std::ffi::c_void) -> u8;
    static kCFBooleanTrue: *const std::ffi::c_void;
    static kCFTypeDictionaryKeyCallBacks: std::ffi::c_void;
    static kCFTypeDictionaryValueCallBacks: std::ffi::c_void;
    // Attribute keys (CFStringRef) — resolved at runtime via dlsym-style externs from Security.
    static kSecClass: *const std::ffi::c_void;
    static kSecClassGenericPassword: *const std::ffi::c_void;
    static kSecClassKey: *const std::ffi::c_void;
    static kSecAttrService: *const std::ffi::c_void;
    static kSecAttrAccount: *const std::ffi::c_void;
    static kSecValueData: *const std::ffi::c_void;
    static kSecReturnData: *const std::ffi::c_void;
    static kSecAttrIsPermanent: *const std::ffi::c_void;
    static kSecAttrApplicationTag: *const std::ffi::c_void;
    static kSecAttrKeyType: *const std::ffi::c_void;
    static kSecAttrKeyTypeECSECPrimeRandom: *const std::ffi::c_void;
    static kSecAttrKeySizeInBits: *const std::ffi::c_void;
    static kSecAttrTokenID: *const std::ffi::c_void;
    static kSecAttrTokenIDSecureEnclave: *const std::ffi::c_void;
    static kSecPrivateKeyAttrs: *const std::ffi::c_void;
    static kSecAttrAccessible: *const std::ffi::c_void;
    static kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly: *const std::ffi::c_void;
    static kSecAttrAccessGroup: *const std::ffi::c_void;
}

#[cfg(target_os = "macos")]
const kCFStringEncodingUTF8: u32 = 0x0800_0100;
#[cfg(target_os = "macos")]
const errSecSuccess: i32 = 0;
#[cfg(target_os = "macos")]
const errSecDuplicateItem: i32 = -25299;
#[cfg(target_os = "macos")]
const errSecItemNotFound: i32 = -25300;

#[cfg(target_os = "macos")]
fn anubis_kc_cfstr(s: &str) -> *const std::ffi::c_void {
    let c = std::ffi::CString::new(s).unwrap_or_default();
    unsafe { CFStringCreateWithCString(std::ptr::null(), c.as_ptr(), kCFStringEncodingUTF8) }
}

#[cfg(target_os = "macos")]
fn anubis_kc_dict(pairs: &[(*const std::ffi::c_void, *const std::ffi::c_void)]) -> *const std::ffi::c_void {
    let keys: Vec<*const std::ffi::c_void> = pairs.iter().map(|(k, _)| *k).collect();
    let vals: Vec<*const std::ffi::c_void> = pairs.iter().map(|(_, v)| *v).collect();
    unsafe {
        CFDictionaryCreate(
            std::ptr::null(),
            keys.as_ptr(),
            vals.as_ptr(),
            pairs.len() as isize,
            &kCFTypeDictionaryKeyCallBacks as *const _ as *const std::ffi::c_void,
            &kCFTypeDictionaryValueCallBacks as *const _ as *const std::ffi::c_void,
        )
    }
}

#[cfg(target_os = "macos")]
fn anubis_kc_keychain_available() -> bool {
    // Smoke: add+delete a tiny probe item under a unique account.
    let acct = format!("anubis-probe-{}", anubis_kc_nonce());
    match anubis_kc_mint_keychain_account("probe", &acct) {
        Ok(tok) => {
            let _ = anubis_kc_delete_token(&tok);
            true
        }
        Err(_) => false,
    }
}

#[cfg(target_os = "macos")]
fn anubis_kc_se_available() -> bool {
    // Attempt SE key gen; delete immediately. Headless CI often fails → false.
    match anubis_kc_mint_se("probe") {
        Ok(tok) => {
            let _ = anubis_kc_delete_token(&tok);
            true
        }
        Err(_) => false,
    }
}

#[cfg(target_os = "macos")]
fn anubis_kc_mint_keychain(kind: &str) -> Result<String, i32> {
    let acct = format!("ne-{}-{}", kind, anubis_kc_nonce());
    anubis_kc_mint_keychain_account(kind, &acct)
}

#[cfg(target_os = "macos")]
fn anubis_kc_mint_keychain_account(kind: &str, account: &str) -> Result<String, i32> {
    unsafe {
        let service = anubis_kc_cfstr("anubis.capability.nonexportable");
        let acct = anubis_kc_cfstr(account);
        let payload = format!("kind={kind};pid={}", std::process::id());
        let data = CFDataCreate(
            std::ptr::null(),
            payload.as_ptr(),
            payload.len() as isize,
        );
        // Optional access group from signed-run path (ANUBIS_KEYCHAIN_ACCESS_GROUP=TEAM.anubis.capability).
        let group_env = std::env::var("ANUBIS_KEYCHAIN_ACCESS_GROUP").ok();
        let group_cf = group_env
            .as_ref()
            .map(|g| anubis_kc_cfstr(g));
        let mut pairs: Vec<(*const std::ffi::c_void, *const std::ffi::c_void)> = vec![
            (kSecClass, kSecClassGenericPassword),
            (kSecAttrService, service),
            (kSecAttrAccount, acct),
            (kSecValueData, data),
            (kSecAttrAccessible, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly),
        ];
        if let Some(g) = group_cf {
            pairs.push((kSecAttrAccessGroup, g));
        }
        let attrs = anubis_kc_dict(&pairs);
        let status = SecItemAdd(attrs, std::ptr::null_mut());
        CFRelease(attrs);
        CFRelease(service);
        CFRelease(acct);
        CFRelease(data);
        if let Some(g) = group_cf {
            CFRelease(g);
        }
        if status == errSecSuccess || status == errSecDuplicateItem {
            Ok(format!("__anubis_cap_ne_kc:{account}"))
        } else {
            Err(status)
        }
    }
}

#[cfg(target_os = "macos")]
fn anubis_kc_mint_se(kind: &str) -> Result<String, i32> {
    unsafe {
        let tag_str = format!("anubis.ne.{kind}.{}", anubis_kc_nonce());
        let tag_data = CFDataCreate(
            std::ptr::null(),
            tag_str.as_ptr(),
            tag_str.len() as isize,
        );
        // bits as CFNumber — use a small helper via CFString for size to avoid CFNumber link complexity:
        // SecKeyCreateRandomKey accepts CFDictionary; kSecAttrKeySizeInBits as CFNumber is required.
        // Use 256-bit EC via integer CFNumber created from bytes — link CoreFoundation CFNumberCreate.
    }
    // Prefer a dedicated CFNumber path:
    anubis_kc_mint_se_inner(kind)
}

#[cfg(target_os = "macos")]
#[link(name = "CoreFoundation", kind = "framework")]
extern "C" {
    fn CFNumberCreate(
        allocator: *const std::ffi::c_void,
        the_type: isize,
        value_ptr: *const std::ffi::c_void,
    ) -> *const std::ffi::c_void;
}

#[cfg(target_os = "macos")]
const kCFNumberSInt32Type: isize = 3;

#[cfg(target_os = "macos")]
fn anubis_kc_mint_se_inner(kind: &str) -> Result<String, i32> {
    unsafe {
        let tag_str = format!("anubis.ne.{kind}.{}", anubis_kc_nonce());
        let tag_data = CFDataCreate(
            std::ptr::null(),
            tag_str.as_ptr(),
            tag_str.len() as isize,
        );
        let bits: i32 = 256;
        let bits_num = CFNumberCreate(
            std::ptr::null(),
            kCFNumberSInt32Type,
            &bits as *const i32 as *const std::ffi::c_void,
        );
        let priv_attrs = anubis_kc_dict(&[
            (kSecAttrIsPermanent, kCFBooleanTrue),
            (kSecAttrApplicationTag, tag_data),
            (kSecAttrAccessible, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly),
        ]);
        let params = anubis_kc_dict(&[
            (kSecAttrKeyType, kSecAttrKeyTypeECSECPrimeRandom),
            (kSecAttrKeySizeInBits, bits_num),
            (kSecAttrTokenID, kSecAttrTokenIDSecureEnclave),
            (kSecPrivateKeyAttrs, priv_attrs),
        ]);
        let mut err: *const std::ffi::c_void = std::ptr::null();
        let key = SecKeyCreateRandomKey(params, &mut err);
        CFRelease(params);
        CFRelease(priv_attrs);
        CFRelease(tag_data);
        CFRelease(bits_num);
        if key.is_null() {
            if !err.is_null() {
                CFRelease(err);
            }
            return Err(-1);
        }
        let pubk = SecKeyCopyPublicKey(key);
        let mut err2: *const std::ffi::c_void = std::ptr::null();
        let ext = if pubk.is_null() {
            std::ptr::null()
        } else {
            SecKeyCopyExternalRepresentation(pubk, &mut err2)
        };
        let mut hash_hex = String::new();
        if !ext.is_null() {
            let len = CFDataGetLength(ext) as usize;
            let ptr = CFDataGetBytePtr(ext);
            if !ptr.is_null() && len > 0 {
                let bytes = std::slice::from_raw_parts(ptr, len);
                // FNV-1a 64-bit fingerprint of public key bytes (not a crypto claim — handle id).
                let mut h: u64 = 0xcbf29ce484222325;
                for b in bytes {
                    h ^= *b as u64;
                    h = h.wrapping_mul(0x100000001b3);
                }
                hash_hex = format!("{h:016x}");
            }
            CFRelease(ext);
        }
        if !err2.is_null() {
            CFRelease(err2);
        }
        if !pubk.is_null() {
            CFRelease(pubk);
        }
        // Keep private key in SE keychain (permanent). Token is a handle, not the key material.
        CFRelease(key);
        if hash_hex.is_empty() {
            hash_hex = anubis_kc_nonce();
        }
        Ok(format!("__anubis_cap_ne_se:{kind}:{hash_hex}"))
    }
}

#[cfg(target_os = "macos")]
fn anubis_kc_delete_token(tok: &str) -> Result<(), i32> {
    if let Some(acct) = tok.strip_prefix("__anubis_cap_ne_kc:") {
        unsafe {
            let service = anubis_kc_cfstr("anubis.capability.nonexportable");
            let account = anubis_kc_cfstr(acct);
            let query = anubis_kc_dict(&[
                (kSecClass, kSecClassGenericPassword),
                (kSecAttrService, service),
                (kSecAttrAccount, account),
            ]);
            let status = SecItemDelete(query);
            CFRelease(query);
            CFRelease(service);
            CFRelease(account);
            if status == errSecSuccess || status == errSecItemNotFound {
                Ok(())
            } else {
                Err(status)
            }
        }
    } else if tok.starts_with("__anubis_cap_ne_se:") {
        // SE keys are permanent; best-effort delete by application tag is residual.
        Ok(())
    } else {
        Ok(())
    }
}

// ---- Cryptography via audited crates (RWC Ch16: don't roll your own) ----
// Native `anubis run` only. Crates: sha2, hmac, hkdf, chacha20poly1305, argon2,
// pbkdf2, getrandom, subtle, ed25519-dalek, x25519-dalek. Same AnubisValue surface
// as pure guest crypto for shared APIs; Ed25519 / X25519 / PHC are host-audited extras.
// Grounding: David Wong, Real-World Cryptography (Manning 2021).

use chacha20poly1305::aead::{Aead, KeyInit, Payload};
use chacha20poly1305::{ChaCha20Poly1305, Nonce};
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use x25519_dalek::{PublicKey as X25519Public, StaticSecret};

type HmacSha256 = Hmac<Sha256>;

fn anubis_hex_encode(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(HEX[(b >> 4) as usize] as char);
        out.push(HEX[(b & 0xf) as usize] as char);
    }
    out
}

/// Canonical crypto bytes. List elements MUST be integers in 0..=255 — fail closed on
/// truncation (silent `as u8` was a real key-corruption footgun).
fn anubis_crypto_bytes(v: &AnubisValue) -> Vec<u8> {
    match v {
        AnubisValue::List(items) => {
            let mut out = Vec::with_capacity(items.len());
            for (i, x) in items.iter().enumerate() {
                let n = x.as_i64();
                if n < 0 || n > 255 {
                    panic!(
                        "ANUBIS_CRYPTO_BYTE_RANGE: list element [{}] = {} not in 0..=255 \
                         (refusing silent truncation of key/nonce/tag material)",
                        i, n
                    );
                }
                out.push(n as u8);
            }
            out
        }
        AnubisValue::Str(s) => s.as_bytes().to_vec(),
        AnubisValue::Int(n) => {
            // Single integer is NOT key material — force callers to use byte lists / strings.
            panic!(
                "ANUBIS_CRYPTO_BYTES_KIND: bare integer {} is not accepted as crypto input; \
                 use a byte list [0..255, ...] or a string",
                n
            );
        }
        AnubisValue::Bool(_) => {
            panic!("ANUBIS_CRYPTO_BYTES_KIND: bool is not accepted as crypto input");
        }
        other => other.display_string().into_bytes(),
    }
}

fn anubis_bytes_list(bytes: &[u8]) -> AnubisValue {
    anubis_mk_list(bytes.iter().map(|b| AnubisValue::Int(*b as i64)).collect())
}

fn anubis_sha256_bytes(msg: Vec<u8>) -> [u8; 32] {
    let d = Sha256::digest(&msg);
    let mut out = [0u8; 32];
    out.copy_from_slice(&d);
    out
}

fn anubis_sha256(v: AnubisValue) -> AnubisValue {
    anubis_mk_str(anubis_hex_encode(&anubis_sha256_bytes(anubis_crypto_bytes(&v))))
}

/// Hex-encode arbitrary crypto bytes (for KATs / debugging — not a secret leak by itself).
fn anubis_bytes_hex(v: AnubisValue) -> AnubisValue {
    anubis_mk_str(anubis_hex_encode(&anubis_crypto_bytes(&v)))
}

fn anubis_sha256_bytes_val(v: AnubisValue) -> AnubisValue {
    anubis_bytes_list(&anubis_sha256_bytes(anubis_crypto_bytes(&v)))
}

fn anubis_hmac_sha256_raw(key: &[u8], msg: &[u8]) -> [u8; 32] {
    // RFC 2104: any key length is valid. Fail closed if the library rejects the key —
    // never silently substitute a zero key (that would authenticate under a known key).
    let mut mac = <HmacSha256 as Mac>::new_from_slice(key).unwrap_or_else(|e| {
        panic!("ANUBIS_CRYPTO_HMAC_KEY: {}", e);
    });
    Mac::update(&mut mac, msg);
    let result = mac.finalize().into_bytes();
    let mut out = [0u8; 32];
    out.copy_from_slice(&result);
    out
}

fn anubis_hmac_sha256(key: AnubisValue, msg: AnubisValue) -> AnubisValue {
    let tag = anubis_hmac_sha256_raw(&anubis_crypto_bytes(&key), &anubis_crypto_bytes(&msg));
    anubis_mk_str(anubis_hex_encode(&tag))
}

fn anubis_hmac_sha256_bytes(key: AnubisValue, msg: AnubisValue) -> AnubisValue {
    let tag = anubis_hmac_sha256_raw(&anubis_crypto_bytes(&key), &anubis_crypto_bytes(&msg));
    anubis_bytes_list(&tag)
}

fn anubis_ct_eq(a: AnubisValue, b: AnubisValue) -> AnubisValue {
    let aa = anubis_crypto_bytes(&a);
    let bb = anubis_crypto_bytes(&b);
    if aa.len() != bb.len() {
        return AnubisValue::Bool(false);
    }
    AnubisValue::Bool(bool::from(aa.ct_eq(&bb)))
}

fn anubis_hmac_sha256_verify(key: AnubisValue, msg: AnubisValue, tag: AnubisValue) -> AnubisValue {
    let expected = anubis_hmac_sha256_raw(&anubis_crypto_bytes(&key), &anubis_crypto_bytes(&msg));
    let got = {
        let t = anubis_crypto_bytes(&tag);
        if t.len() == 32 {
            t
        } else {
            let s = tag.display_string();
            let mut out = Vec::new();
            let chars: Vec<char> = s.chars().filter(|c| !c.is_whitespace()).collect();
            if chars.len() == 64 && chars.iter().all(|c| c.is_ascii_hexdigit()) {
                let mut i = 0;
                while i < 64 {
                    let byte = u8::from_str_radix(&format!("{}{}", chars[i], chars[i + 1]), 16)
                        .unwrap_or(0);
                    out.push(byte);
                    i += 2;
                }
            }
            out
        }
    };
    if got.len() != 32 {
        return AnubisValue::Bool(false);
    }
    AnubisValue::Bool(bool::from(expected.ct_eq(got.as_slice())))
}

fn anubis_hkdf_sha256(
    ikm: AnubisValue,
    salt: AnubisValue,
    info: AnubisValue,
    length: AnubisValue,
) -> AnubisValue {
    use hkdf::Hkdf;
    let ikm_b = anubis_crypto_bytes(&ikm);
    let salt_b = anubis_crypto_bytes(&salt);
    let info_b = anubis_crypto_bytes(&info);
    // RFC 5869 §2.3: L ∈ [1, 255*HashLen]. Prior code silently coerced negative L to 0 via
    // `.max(0)` and returned an empty byte list — a SILENT_WRONG that would feed a downstream
    // `ensures(len(key) == 32)` and let a contract hold "for the wrong reason" (the caller
    // sees an empty vec and never checks). Fail closed on non-positive length, matching
    // `anubis_random_bytes`'s posture. Kept parity with the pure lane so both host runtimes
    // enforce the same domain (a caller that verifies against pure and runs against audited —
    // or vice versa — cannot straddle a boundary at which one side silently accepts).
    let n_raw = length.as_i64();
    if n_raw < 1 {
        panic!(
            "ANUBIS_CRYPTO_HKDF_LENGTH: L must be >= 1 (RFC 5869), got {}",
            n_raw
        );
    }
    let n = n_raw as usize;
    if n > 255 * 32 {
        panic!(
            "ANUBIS_CRYPTO_HKDF_TOO_LONG: requested {} bytes (max {})",
            n,
            255 * 32
        );
    }
    let salt_opt: Option<&[u8]> = if salt_b.is_empty() {
        None
    } else {
        Some(salt_b.as_slice())
    };
    let hk = Hkdf::<Sha256>::new(salt_opt, &ikm_b);
    let mut okm = vec![0u8; n];
    if hk.expand(&info_b, &mut okm).is_err() {
        panic!("ANUBIS_CRYPTO_HKDF_EXPAND_FAILED");
    }
    anubis_bytes_list(&okm)
}

fn anubis_domain_hash(label: AnubisValue, data: AnubisValue) -> AnubisValue {
    let lab = anubis_crypto_bytes(&label);
    let dat = anubis_crypto_bytes(&data);
    if lab.len() > u32::MAX as usize || dat.len() > u32::MAX as usize {
        panic!("ANUBIS_CRYPTO_DOMAIN_HASH_TOO_LARGE");
    }
    let mut msg = Vec::with_capacity(1 + 4 + lab.len() + 4 + dat.len());
    msg.push(0x01);
    msg.extend_from_slice(&(lab.len() as u32).to_be_bytes());
    msg.extend_from_slice(&lab);
    msg.extend_from_slice(&(dat.len() as u32).to_be_bytes());
    msg.extend_from_slice(&dat);
    anubis_mk_str(anubis_hex_encode(&anubis_sha256_bytes(msg)))
}

/// TupleHash spirit (RWC Ch2): length-prefix each part so `H(a||b) ≠ H(ab)` ambiguity dies.
/// `parts` must be a list of strings or byte lists.
fn anubis_tuple_hash(label: AnubisValue, parts: AnubisValue) -> AnubisValue {
    let lab = anubis_crypto_bytes(&label);
    let AnubisValue::List(items) = parts else {
        panic!("ANUBIS_CRYPTO_TUPLE_HASH: parts must be a list");
    };
    if lab.len() > u32::MAX as usize || items.len() > u32::MAX as usize {
        panic!("ANUBIS_CRYPTO_TUPLE_HASH_TOO_LARGE");
    }
    let mut msg = Vec::new();
    msg.push(0x02); // domain version distinct from domain_hash
    msg.extend_from_slice(&(lab.len() as u32).to_be_bytes());
    msg.extend_from_slice(&lab);
    msg.extend_from_slice(&(items.len() as u32).to_be_bytes());
    for (i, p) in items.iter().enumerate() {
        let b = anubis_crypto_bytes(p);
        if b.len() > u32::MAX as usize {
            panic!("ANUBIS_CRYPTO_TUPLE_HASH_PART_TOO_LARGE: index {i}");
        }
        msg.extend_from_slice(&(b.len() as u32).to_be_bytes());
        msg.extend_from_slice(&b);
    }
    anubis_mk_str(anubis_hex_encode(&anubis_sha256_bytes(msg)))
}

/// 12-byte nonce from a 64-bit counter (RWC Ch4: unique per key). Layout: 4 zero bytes + BE u64.
/// Suitable for moderate sequential protocols; never reuse a counter under the same key.
fn anubis_aead_nonce_from_counter(counter: AnubisValue) -> AnubisValue {
    let c = counter.as_i64();
    if c < 0 {
        panic!("ANUBIS_CRYPTO_NONCE_COUNTER: counter must be >= 0");
    }
    let mut n = [0u8; 12];
    n[4..12].copy_from_slice(&(c as u64).to_be_bytes());
    anubis_bytes_list(&n)
}

fn anubis_random_bytes(n: AnubisValue) -> AnubisValue {
    let n_raw = n.as_i64();
    if n_raw < 0 {
        panic!("ANUBIS_CRYPTO_RANDOM_NEGATIVE_LENGTH: byte count must be non-negative, got {}", n_raw);
    }
    let n = n_raw as usize;
    if n > 1 << 20 {
        panic!("ANUBIS_CRYPTO_RANDOM_TOO_LARGE: max 1MiB per call");
    }
    let mut buf = vec![0u8; n];
    if let Err(e) = getrandom::getrandom(&mut buf) {
        panic!("ANUBIS_CRYPTO_RANDOM_FAILED: {}", e);
    }
    anubis_bytes_list(&buf)
}

fn anubis_aead_parse_key_nonce(key: &AnubisValue, nonce: &AnubisValue) -> ([u8; 32], [u8; 12]) {
    let kb = anubis_crypto_bytes(key);
    let nb = anubis_crypto_bytes(nonce);
    if kb.len() != 32 {
        panic!(
            "ANUBIS_CRYPTO_AEAD_KEY_LEN: ChaCha20-Poly1305 key must be 32 bytes, got {}",
            kb.len()
        );
    }
    if nb.len() != 12 {
        panic!(
            "ANUBIS_CRYPTO_AEAD_NONCE_LEN: nonce must be 12 bytes (RWC: unique per key), got {}",
            nb.len()
        );
    }
    let mut k = [0u8; 32];
    let mut n = [0u8; 12];
    k.copy_from_slice(&kb);
    n.copy_from_slice(&nb);
    (k, n)
}

fn anubis_aead_seal(
    key: AnubisValue,
    nonce: AnubisValue,
    aad: AnubisValue,
    plaintext: AnubisValue,
) -> AnubisValue {
    let (k, n) = anubis_aead_parse_key_nonce(&key, &nonce);
    let aad_b = anubis_crypto_bytes(&aad);
    let pt = anubis_crypto_bytes(&plaintext);
    let cipher = ChaCha20Poly1305::new((&k).into());
    let nonce = Nonce::from_slice(&n);
    let ct = cipher
        .encrypt(
            nonce,
            Payload {
                msg: &pt,
                aad: &aad_b,
            },
        )
        .unwrap_or_else(|_| panic!("ANUBIS_CRYPTO_AEAD_SEAL_FAILED"));
    anubis_bytes_list(&ct)
}

fn anubis_aead_open(
    key: AnubisValue,
    nonce: AnubisValue,
    aad: AnubisValue,
    ciphertext_and_tag: AnubisValue,
) -> AnubisValue {
    let (k, n) = anubis_aead_parse_key_nonce(&key, &nonce);
    let aad_b = anubis_crypto_bytes(&aad);
    let blob = anubis_crypto_bytes(&ciphertext_and_tag);
    if blob.len() < 16 {
        panic!("ANUBIS_CRYPTO_AEAD_OPEN_FAILED: ciphertext shorter than tag");
    }
    let cipher = ChaCha20Poly1305::new((&k).into());
    let nonce = Nonce::from_slice(&n);
    match cipher.decrypt(
        nonce,
        Payload {
            msg: &blob,
            aad: &aad_b,
        },
    ) {
        Ok(pt) => anubis_bytes_list(&pt),
        Err(_) => panic!("ANUBIS_CRYPTO_AEAD_OPEN_FAILED: authentication tag mismatch (fail closed)"),
    }
}

// ---- Password hashing: argon2 + pbkdf2 crates (RWC Ch8) ----

fn anubis_pbkdf2_hmac_sha256_raw(
    password: &[u8],
    salt: &[u8],
    iterations: u32,
    dk_len: usize,
) -> Vec<u8> {
    use pbkdf2::pbkdf2_hmac;
    if iterations < 1 {
        panic!("ANUBIS_CRYPTO_PBKDF2_ITERATIONS: must be >= 1");
    }
    if dk_len > 1024 * 1024 {
        panic!("ANUBIS_CRYPTO_PBKDF2_TOO_LONG: max 1MiB");
    }
    if salt.is_empty() {
        panic!("ANUBIS_CRYPTO_PBKDF2_SALT: salt must be non-empty (prefer >= 16 bytes)");
    }
    let mut okm = vec![0u8; dk_len];
    pbkdf2_hmac::<Sha256>(password, salt, iterations, &mut okm);
    okm
}

fn anubis_pbkdf2_hmac_sha256(
    password: AnubisValue,
    salt: AnubisValue,
    iterations: AnubisValue,
    length: AnubisValue,
) -> AnubisValue {
    let iters = iterations.as_i64();
    if iters < 1 || iters > u32::MAX as i64 {
        panic!("ANUBIS_CRYPTO_PBKDF2_ITERATIONS: must be in 1..2^32-1");
    }
    // RFC 8018 §5.2 dkLen: must be a positive integer, at most (2^32-1)*hLen. Prior code
    // silently coerced non-positive length to 0 via `.max(0)` and returned an empty byte
    // list — same SILENT_WRONG shape closed on HKDF. Kept parity with the pure lane so both
    // host runtimes enforce the same domain (a caller that verifies against pure and runs
    // against audited — or vice versa — cannot straddle a boundary at which one side silently
    // accepts).
    let n_raw = length.as_i64();
    if n_raw < 1 {
        panic!(
            "ANUBIS_CRYPTO_PBKDF2_LENGTH: dkLen must be >= 1 (RFC 8018), got {}",
            n_raw
        );
    }
    let n = n_raw as usize;
    let dk = anubis_pbkdf2_hmac_sha256_raw(
        &anubis_crypto_bytes(&password),
        &anubis_crypto_bytes(&salt),
        iters as u32,
        n,
    );
    anubis_bytes_list(&dk)
}

fn anubis_argon2id_raw(
    pwd: &[u8],
    salt: &[u8],
    m_cost: u32,
    t_cost: u32,
    p_cost: u32,
    out_len: usize,
) -> Vec<u8> {
    use argon2::{Algorithm, Argon2, Params, Version};
    if salt.len() < 8 {
        panic!("ANUBIS_CRYPTO_ARGON2_SALT: salt must be >= 8 bytes (prefer 16)");
    }
    if out_len < 4 || out_len > 1024 {
        panic!("ANUBIS_CRYPTO_ARGON2_OUTLEN: must be 4..1024");
    }
    if m_cost < 8 || m_cost > 256 * 1024 {
        panic!("ANUBIS_CRYPTO_ARGON2_M: m_kib must be in 8..262144");
    }
    if t_cost < 1 || p_cost < 1 {
        panic!("ANUBIS_CRYPTO_ARGON2_PARAMS: t and p must be >= 1");
    }
    let params = Params::new(m_cost, t_cost, p_cost, Some(out_len)).unwrap_or_else(|e| {
        panic!("ANUBIS_CRYPTO_ARGON2_PARAMS: {}", e);
    });
    let a2 = Argon2::new(Algorithm::Argon2id, Version::V0x13, params);
    let mut out = vec![0u8; out_len];
    a2.hash_password_into(pwd, salt, &mut out)
        .unwrap_or_else(|e| panic!("ANUBIS_CRYPTO_ARGON2_FAILED: {}", e));
    out
}

fn anubis_argon2id_hash(
    password: AnubisValue,
    salt: AnubisValue,
    m_kib: AnubisValue,
    t: AnubisValue,
    p: AnubisValue,
    out_len: AnubisValue,
) -> AnubisValue {
    let m = m_kib.as_i64();
    let tt = t.as_i64();
    let pp = p.as_i64();
    let ol = out_len.as_i64();
    if m < 8 || m > 256 * 1024 {
        panic!("ANUBIS_CRYPTO_ARGON2_M: m_kib must be in 8..262144");
    }
    if tt < 1 || tt > 100 {
        panic!("ANUBIS_CRYPTO_ARGON2_T: time cost must be in 1..100");
    }
    if pp < 1 || pp > 16 {
        panic!("ANUBIS_CRYPTO_ARGON2_P: parallelism must be in 1..16");
    }
    if ol < 4 || ol > 1024 {
        panic!("ANUBIS_CRYPTO_ARGON2_OUTLEN: must be 4..1024");
    }
    let hash = anubis_argon2id_raw(
        &anubis_crypto_bytes(&password),
        &anubis_crypto_bytes(&salt),
        m as u32,
        tt as u32,
        pp as u32,
        ol as usize,
    );
    anubis_bytes_list(&hash)
}

fn anubis_hex_decode_loose(s: &str) -> Option<Vec<u8>> {
    let chars: Vec<char> = s.chars().filter(|c| !c.is_whitespace()).collect();
    if chars.len() % 2 != 0 {
        return None;
    }
    if !chars.iter().all(|c| c.is_ascii_hexdigit()) {
        return None;
    }
    let mut out = Vec::with_capacity(chars.len() / 2);
    let mut i = 0;
    while i < chars.len() {
        let byte = u8::from_str_radix(&format!("{}{}", chars[i], chars[i + 1]), 16).ok()?;
        out.push(byte);
        i += 2;
    }
    Some(out)
}

/// Production password hash via argon2 crate (Argon2id, OWASP-class params).
fn anubis_password_hash_encode(password: AnubisValue) -> AnubisValue {
    let salt_v = anubis_random_bytes(AnubisValue::Int(16));
    let salt = anubis_crypto_bytes(&salt_v);
    let hash = anubis_argon2id_raw(&anubis_crypto_bytes(&password), &salt, 19456, 2, 1, 32);
    let enc = format!(
        "anubis$argon2id$v=19$m=19456,t=2,p=1${}${}",
        anubis_hex_encode(&salt),
        anubis_hex_encode(&hash)
    );
    anubis_mk_str(enc)
}

fn anubis_password_hash_pbkdf2_encode(password: AnubisValue) -> AnubisValue {
    let salt_v = anubis_random_bytes(AnubisValue::Int(16));
    let salt = anubis_crypto_bytes(&salt_v);
    let hash = anubis_pbkdf2_hmac_sha256_raw(&anubis_crypto_bytes(&password), &salt, 600_000, 32);
    let enc = format!(
        "anubis$pbkdf2-sha256$i=600000${}${}",
        anubis_hex_encode(&salt),
        anubis_hex_encode(&hash)
    );
    anubis_mk_str(enc)
}

/// Standard PHC string (`$argon2id$v=19$m=…`) via the argon2 crate's PasswordHasher —
/// interoperable with other tools that speak PHC. Prefer this for long-lived password stores.
fn anubis_password_hash_phc(password: AnubisValue) -> AnubisValue {
    use argon2::{
        password_hash::{rand_core::OsRng, PasswordHasher, SaltString},
        Algorithm, Argon2, Params, Version,
    };
    let pwd = anubis_crypto_bytes(&password);
    let salt = SaltString::generate(&mut OsRng);
    let params = Params::new(19456, 2, 1, None).unwrap_or_else(|e| {
        panic!("ANUBIS_CRYPTO_ARGON2_PARAMS: {}", e);
    });
    let a2 = Argon2::new(Algorithm::Argon2id, Version::V0x13, params);
    let hash = a2
        .hash_password(&pwd, &salt)
        .unwrap_or_else(|e| panic!("ANUBIS_CRYPTO_PASSWORD_HASH_PHC: {}", e));
    anubis_mk_str(hash.to_string())
}

fn anubis_password_verify_phc_raw(password: &[u8], encoding: &str) -> bool {
    use argon2::{
        password_hash::{PasswordHash, PasswordVerifier},
        Argon2,
    };
    let Ok(parsed) = PasswordHash::new(encoding) else {
        return false;
    };
    Argon2::default()
        .verify_password(password, &parsed)
        .is_ok()
}

// Re-bind password_verify to also accept standard PHC strings (`$argon2id$…`).
fn anubis_password_verify_encoding(password: AnubisValue, encoding: AnubisValue) -> AnubisValue {
    let enc = encoding.display_string();
    let pwd = anubis_crypto_bytes(&password);
    // Standard PHC (argon2 crate / passlib / libsodium interop)
    if enc.starts_with("$argon2") {
        return AnubisValue::Bool(anubis_password_verify_phc_raw(&pwd, &enc));
    }
    // anubis$… custom encodings (argon2id / pbkdf2-sha256)
    let parts: Vec<&str> = enc.split('$').collect();
    if parts.len() < 5 || parts[0] != "anubis" {
        return AnubisValue::Bool(false);
    }
    let algo = parts[1];
    let salt = match anubis_hex_decode_loose(parts[parts.len() - 2]) {
        Some(s) if !s.is_empty() => s,
        _ => return AnubisValue::Bool(false),
    };
    let expected = match anubis_hex_decode_loose(parts[parts.len() - 1]) {
        Some(h) if !h.is_empty() => h,
        _ => return AnubisValue::Bool(false),
    };
    let got = if algo == "argon2id" {
        if parts.len() < 6 {
            return AnubisValue::Bool(false);
        }
        let mut m: Option<u32> = None;
        let mut t: Option<u32> = None;
        let mut p: Option<u32> = None;
        for kv in parts[3].split(',') {
            if let Some(v) = kv.strip_prefix("m=") {
                m = v.parse().ok();
            } else if let Some(v) = kv.strip_prefix("t=") {
                t = v.parse().ok();
            } else if let Some(v) = kv.strip_prefix("p=") {
                p = v.parse().ok();
            }
        }
        let (Some(m), Some(t), Some(p)) = (m, t, p) else {
            return AnubisValue::Bool(false);
        };
        anubis_argon2id_raw(&pwd, &salt, m, t, p, expected.len())
    } else if algo == "pbkdf2-sha256" {
        let iters: u32 = match parts[2].strip_prefix("i=").and_then(|v| v.parse().ok()) {
            Some(i) if i >= 1 => i,
            _ => return AnubisValue::Bool(false),
        };
        anubis_pbkdf2_hmac_sha256_raw(&pwd, &salt, iters, expected.len())
    } else {
        return AnubisValue::Bool(false);
    };
    if got.len() != expected.len() {
        return AnubisValue::Bool(false);
    }
    AnubisValue::Bool(bool::from(got.ct_eq(expected.as_slice())))
}

// ---- Ed25519 (RWC / modern signatures — audited ed25519-dalek) ----

fn anubis_ed25519_keygen() -> AnubisValue {
    let mut seed = [0u8; 32];
    if let Err(e) = getrandom::getrandom(&mut seed) {
        panic!("ANUBIS_CRYPTO_ED25519_RNG: {}", e);
    }
    let sk = SigningKey::from_bytes(&seed);
    let pk = sk.verifying_key();
    // Return [secret_key_32, public_key_32] as nested byte lists
    anubis_mk_list(vec![
        anubis_bytes_list(sk.to_bytes().as_slice()),
        anubis_bytes_list(pk.as_bytes()),
    ])
}

fn anubis_ed25519_public_key(secret_key: AnubisValue) -> AnubisValue {
    let sk_b = anubis_crypto_bytes(&secret_key);
    if sk_b.len() != 32 {
        panic!(
            "ANUBIS_CRYPTO_ED25519_SK_LEN: secret key must be 32 bytes, got {}",
            sk_b.len()
        );
    }
    let mut seed = [0u8; 32];
    seed.copy_from_slice(&sk_b);
    let sk = SigningKey::from_bytes(&seed);
    anubis_bytes_list(sk.verifying_key().as_bytes())
}

fn anubis_ed25519_sign(secret_key: AnubisValue, msg: AnubisValue) -> AnubisValue {
    let sk_b = anubis_crypto_bytes(&secret_key);
    if sk_b.len() != 32 {
        panic!(
            "ANUBIS_CRYPTO_ED25519_SK_LEN: secret key must be 32 bytes, got {}",
            sk_b.len()
        );
    }
    let mut seed = [0u8; 32];
    seed.copy_from_slice(&sk_b);
    let sk = SigningKey::from_bytes(&seed);
    let sig = sk.sign(&anubis_crypto_bytes(&msg));
    anubis_bytes_list(sig.to_bytes().as_slice())
}

fn anubis_ed25519_verify(public_key: AnubisValue, msg: AnubisValue, signature: AnubisValue) -> AnubisValue {
    let pk_b = anubis_crypto_bytes(&public_key);
    let sig_b = anubis_crypto_bytes(&signature);
    if pk_b.len() != 32 {
        return AnubisValue::Bool(false);
    }
    if sig_b.len() != 64 {
        return AnubisValue::Bool(false);
    }
    let mut pk_arr = [0u8; 32];
    pk_arr.copy_from_slice(&pk_b);
    let Ok(pk) = VerifyingKey::from_bytes(&pk_arr) else {
        return AnubisValue::Bool(false);
    };
    let mut sig_arr = [0u8; 64];
    sig_arr.copy_from_slice(&sig_b);
    let sig = Signature::from_bytes(&sig_arr);
    AnubisValue::Bool(pk.verify(&anubis_crypto_bytes(&msg), &sig).is_ok())
}

/// Host runtime identity — useful for tests asserting audited path is live.
fn anubis_crypto_backend() -> AnubisValue {
    anubis_mk_str("audited-crates".into())
}

// ---- X25519 ECDH (RWC Ch5) + hybrid envelope (RWC Ch6 ECIES spirit) ----

fn anubis_x25519_from_sk_bytes(sk_b: &[u8]) -> StaticSecret {
    if sk_b.len() != 32 {
        panic!(
            "ANUBIS_CRYPTO_X25519_SK_LEN: secret key must be 32 bytes, got {}",
            sk_b.len()
        );
    }
    let mut seed = [0u8; 32];
    seed.copy_from_slice(sk_b);
    StaticSecret::from(seed)
}

fn anubis_x25519_from_pk_bytes(pk_b: &[u8]) -> X25519Public {
    if pk_b.len() != 32 {
        panic!(
            "ANUBIS_CRYPTO_X25519_PK_LEN: public key must be 32 bytes, got {}",
            pk_b.len()
        );
    }
    let mut arr = [0u8; 32];
    arr.copy_from_slice(pk_b);
    X25519Public::from(arr)
}

fn anubis_x25519_keygen() -> AnubisValue {
    let mut seed = [0u8; 32];
    if let Err(e) = getrandom::getrandom(&mut seed) {
        panic!("ANUBIS_CRYPTO_X25519_RNG: {}", e);
    }
    let sk = StaticSecret::from(seed);
    let pk = X25519Public::from(&sk);
    anubis_mk_list(vec![
        anubis_bytes_list(sk.to_bytes().as_slice()),
        anubis_bytes_list(pk.as_bytes()),
    ])
}

fn anubis_x25519_public_key(secret_key: AnubisValue) -> AnubisValue {
    let sk = anubis_x25519_from_sk_bytes(&anubis_crypto_bytes(&secret_key));
    let pk = X25519Public::from(&sk);
    anubis_bytes_list(pk.as_bytes())
}

/// Raw Diffie–Hellman shared secret. RWC: never use raw shared as AEAD key — HKDF first.
fn anubis_x25519_shared(secret_key: AnubisValue, peer_public: AnubisValue) -> AnubisValue {
    let sk = anubis_x25519_from_sk_bytes(&anubis_crypto_bytes(&secret_key));
    let pk = anubis_x25519_from_pk_bytes(&anubis_crypto_bytes(&peer_public));
    let shared = sk.diffie_hellman(&pk);
    anubis_bytes_list(shared.as_bytes())
}

fn anubis_hybrid_derive_key(shared: &[u8], eph_pk: &[u8], recip_pk: &[u8]) -> [u8; 32] {
    use hkdf::Hkdf;
    // IKM = shared; salt = eph_pk || recip_pk (binds both static identities into the transcript).
    let mut salt = Vec::with_capacity(64);
    salt.extend_from_slice(eph_pk);
    salt.extend_from_slice(recip_pk);
    let hk = Hkdf::<Sha256>::new(Some(&salt), shared);
    let mut okm = [0u8; 32];
    if hk
        .expand(b"anubis-hybrid-v1|chacha20-poly1305", &mut okm)
        .is_err()
    {
        panic!("ANUBIS_CRYPTO_HYBRID_HKDF_FAILED");
    }
    okm
}

/// Hybrid seal (ECIES spirit, RWC Ch6): ephemeral X25519 + HKDF + ChaCha20-Poly1305.
/// Returns [eph_public_32, nonce_12, ciphertext_and_tag].
fn anubis_hybrid_seal(
    recipient_public: AnubisValue,
    aad: AnubisValue,
    plaintext: AnubisValue,
) -> AnubisValue {
    let recip_pk_b = anubis_crypto_bytes(&recipient_public);
    let recip_pk = anubis_x25519_from_pk_bytes(&recip_pk_b);
    let mut eph_seed = [0u8; 32];
    if let Err(e) = getrandom::getrandom(&mut eph_seed) {
        panic!("ANUBIS_CRYPTO_HYBRID_RNG: {}", e);
    }
    let eph_sk = StaticSecret::from(eph_seed);
    let eph_pk = X25519Public::from(&eph_sk);
    let shared = eph_sk.diffie_hellman(&recip_pk);
    let key = anubis_hybrid_derive_key(shared.as_bytes(), eph_pk.as_bytes(), recip_pk.as_bytes());
    let mut nonce = [0u8; 12];
    if let Err(e) = getrandom::getrandom(&mut nonce) {
        panic!("ANUBIS_CRYPTO_HYBRID_NONCE_RNG: {}", e);
    }
    let cipher = ChaCha20Poly1305::new((&key).into());
    let aad_b = anubis_crypto_bytes(&aad);
    let pt = anubis_crypto_bytes(&plaintext);
    let ct = cipher
        .encrypt(
            Nonce::from_slice(&nonce),
            Payload {
                msg: &pt,
                aad: &aad_b,
            },
        )
        .unwrap_or_else(|_| panic!("ANUBIS_CRYPTO_HYBRID_SEAL_FAILED"));
    anubis_mk_list(vec![
        anubis_bytes_list(eph_pk.as_bytes()),
        anubis_bytes_list(&nonce),
        anubis_bytes_list(&ct),
    ])
}

/// Hybrid open: recipient static secret + envelope fields from hybrid_seal.
fn anubis_hybrid_open(
    recipient_secret: AnubisValue,
    eph_public: AnubisValue,
    aad: AnubisValue,
    nonce: AnubisValue,
    ciphertext_and_tag: AnubisValue,
) -> AnubisValue {
    let recip_sk = anubis_x25519_from_sk_bytes(&anubis_crypto_bytes(&recipient_secret));
    let recip_pk = X25519Public::from(&recip_sk);
    let eph_pk_b = anubis_crypto_bytes(&eph_public);
    let eph_pk = anubis_x25519_from_pk_bytes(&eph_pk_b);
    let shared = recip_sk.diffie_hellman(&eph_pk);
    let key = anubis_hybrid_derive_key(shared.as_bytes(), eph_pk.as_bytes(), recip_pk.as_bytes());
    let (k, n) = {
        let nb = anubis_crypto_bytes(&nonce);
        if nb.len() != 12 {
            panic!(
                "ANUBIS_CRYPTO_HYBRID_NONCE_LEN: expected 12 bytes, got {}",
                nb.len()
            );
        }
        let mut nn = [0u8; 12];
        nn.copy_from_slice(&nb);
        (key, nn)
    };
    let cipher = ChaCha20Poly1305::new((&k).into());
    let aad_b = anubis_crypto_bytes(&aad);
    let blob = anubis_crypto_bytes(&ciphertext_and_tag);
    if blob.len() < 16 {
        panic!("ANUBIS_CRYPTO_HYBRID_OPEN_FAILED: ciphertext shorter than tag");
    }
    match cipher.decrypt(
        Nonce::from_slice(&n),
        Payload {
            msg: &blob,
            aad: &aad_b,
        },
    ) {
        Ok(pt) => anubis_bytes_list(&pt),
        Err(_) => panic!(
            "ANUBIS_CRYPTO_HYBRID_OPEN_FAILED: authentication tag mismatch (fail closed)"
        ),
    }
}


use std::io::Write;
use std::process::{Command, Stdio};
#[cfg(unix)]
use std::os::unix::process::ExitStatusExt;

fn anubis_to_bytes(v: &AnubisValue) -> Vec<u8> {
    match v {
        // RECURSE, matching the Enum/Struct/Map arms below. Mapping `as_i64() as u8` over the
        // elements silently coerced a NESTED list to its LENGTH, because `as_i64()` on a list
        // returns its element count: `flat([[1,2],[3]])` produced `[2, 1]` — the two inner
        // lengths — where payload assembly needs `[1, 2, 3]`.
        //
        // `flat` is how PoC payloads are built, so this is worse than a wrong answer: an exploit
        // "proves" something about bytes nobody assembled, and a proof-carrying language emits a
        // proof about the wrong artifact.
        //
        // Flat lists are unaffected — an `Int` element serialises to `vec![n as u8]` either way —
        // so this fixes nesting without changing the common case.
        AnubisValue::List(items) => items.iter().flat_map(anubis_to_bytes).collect(),
        AnubisValue::Str(s) => s.as_bytes().to_vec(),
        AnubisValue::Int(n) => vec![*n as u8],
        AnubisValue::Float(n) => vec![(*n as i64) as u8],
        AnubisValue::Bool(b) => vec![if *b { 1 } else { 0 }],
        // Non-byte payloads: flatten structured fields for research harness only.
        AnubisValue::Enum { fields, .. } => {
            fields.iter().flat_map(|x| anubis_to_bytes(x)).collect()
        }
        AnubisValue::Struct { fields, .. } => {
            fields.iter().flat_map(|(_, x)| anubis_to_bytes(x)).collect()
        }
        AnubisValue::Map(m) => m.iter().flat_map(|(_, x)| anubis_to_bytes(x)).collect(),
        AnubisValue::Closure(_) => vec![],
    }
}

/// Fail closed on a non-numeric argument to a pack/cyclic call. `.as_i64()` on a List returns
/// the list's LENGTH, on a Map returns the entry count, on a Struct returns the field count —
/// so `p8([9,9,9])` silently produced `[3]`, `p32([1,2,3,4,5])` produced `[5, 0, 0, 0]`, and
/// `cyclic({"a":1,"b":2})` produced a 2-char pattern. That is worse than a crash for the same
/// reason the `flat` recursion bug was: `flat`/`p*`/`cyclic` compose the bytes an exploit
/// asserts things about, so a silently-wrong pack means a proof-carrying program emits a proof
/// about the wrong artifact. Booleans and numeric strings are still accepted (they are
/// documented-lenient numeric coercions per LANGUAGE.md); only structured values are refused.
fn anubis_pack_require_numeric(fn_name: &str, v: &AnubisValue) {
    match v {
        AnubisValue::Int(_) | AnubisValue::Float(_) | AnubisValue::Bool(_) => {}
        AnubisValue::Str(s) => {
            let trimmed = s.trim();
            if trimmed.parse::<i64>().is_err() && trimmed.parse::<f64>().is_err() {
                panic!(
                    "ANUBIS_POC_PACK_TYPE: `{fn_name}` requires a numeric argument; got string `{s}` which does not parse as a number"
                );
            }
        }
        AnubisValue::List(_) => panic!(
            "ANUBIS_POC_PACK_TYPE: `{fn_name}` requires a numeric argument; got a list (use flat(list) to concatenate bytes, or pass an integer)"
        ),
        AnubisValue::Map(_) => panic!(
            "ANUBIS_POC_PACK_TYPE: `{fn_name}` requires a numeric argument; got a map"
        ),
        AnubisValue::Struct { ty, .. } => panic!(
            "ANUBIS_POC_PACK_TYPE: `{fn_name}` requires a numeric argument; got struct `{ty}`"
        ),
        AnubisValue::Enum { ty, tag, .. } => panic!(
            "ANUBIS_POC_PACK_TYPE: `{fn_name}` requires a numeric argument; got enum variant `{ty}::{tag}`"
        ),
        AnubisValue::Closure(_) => panic!(
            "ANUBIS_POC_PACK_TYPE: `{fn_name}` requires a numeric argument; got a closure"
        ),
    }
}

fn anubis_p8(v: AnubisValue) -> AnubisValue {
    anubis_pack_require_numeric("p8", &v);
    anubis_mk_list(vec![AnubisValue::Int((v.as_i64() as u8) as i64)])
}
fn anubis_p16(v: AnubisValue) -> AnubisValue {
    anubis_pack_require_numeric("p16", &v);
    let n = v.as_i64() as u16;
    anubis_mk_list(n.to_le_bytes().iter().map(|b| AnubisValue::Int(*b as i64)).collect())
}
fn anubis_p32(v: AnubisValue) -> AnubisValue {
    anubis_pack_require_numeric("p32", &v);
    let n = v.as_i64() as u32;
    anubis_mk_list(n.to_le_bytes().iter().map(|b| AnubisValue::Int(*b as i64)).collect())
}
fn anubis_p64(v: AnubisValue) -> AnubisValue {
    anubis_pack_require_numeric("p64", &v);
    let n = v.as_i64() as u64;
    anubis_mk_list(n.to_le_bytes().iter().map(|b| AnubisValue::Int(*b as i64)).collect())
}
fn anubis_cyclic(v: AnubisValue) -> AnubisValue {
    anubis_pack_require_numeric("cyclic", &v);
    // `.max(0)` silently coerced a negative length to 0 and returned `[]` — same shape as the
    // HKDF / PBKDF2 fixes: a caller that passes a signed-overflow value or a computed length
    // otherwise silently got an empty pattern, which cyclic_find would then report "not found"
    // for, hiding the real bug (bad length arithmetic) behind an already-known negative code path.
    let n_raw = v.as_i64();
    if n_raw < 0 {
        panic!(
            "ANUBIS_POC_CYCLIC_LENGTH: cyclic length must be >= 0, got {}",
            n_raw
        );
    }
    let n = n_raw as usize;
    let alphabet = b"abcdefghijklmnopqrstuvwxyz";
    anubis_mk_list((0..n).map(|i| AnubisValue::Int(alphabet[i % alphabet.len()] as i64)).collect())
}

/// A+ target_run result: named struct fields (and list-index compatible).
/// Fields (order preserved for r[0]..):
///   crashed (0/1), signal, exit_code, payload_len, timed_out (0/1)
fn anubis_target_run_result(
    crashed: i64,
    signal: i64,
    exit_code: i64,
    payload_len: i64,
    timed_out: i64,
) -> AnubisValue {
    AnubisValue::Struct {
        ty: "TargetRun".to_string(),
        fields: vec![
            ("crashed".to_string(), AnubisValue::Int(crashed)),
            ("signal".to_string(), AnubisValue::Int(signal)),
            ("exit_code".to_string(), AnubisValue::Int(exit_code)),
            ("payload_len".to_string(), AnubisValue::Int(payload_len)),
            ("timed_out".to_string(), AnubisValue::Int(timed_out)),
        ],
    }
}

/// target_run(path, payload) -> TargetRun struct
/// Named: r.crashed / r.signal / r.exit_code / r.payload_len / r.timed_out
/// Positional (compat): r[0]..r[3] via struct field order.
fn anubis_target_run(path_v: AnubisValue, payload_v: AnubisValue) -> AnubisValue {
    let path = path_v.display_string();
    if path.contains("://") || path.starts_with("http") {
        eprintln!("ANUBIS_POC_NETWORK_FORBIDDEN: target must be a local filesystem path");
        return anubis_target_run_result(0, -1, -1, 0, 0);
    }
    let payload = anubis_to_bytes(&payload_v);
    let mut child = match Command::new(&path)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(c) => c,
        Err(e) => {
            eprintln!("ANUBIS_POC_SPAWN_FAILED: {}: {}", path, e);
            return anubis_target_run_result(0, -1, -1, payload.len() as i64, 0);
        }
    };
    if let Some(mut stdin) = child.stdin.take() {
        let _ = stdin.write_all(&payload);
    }
    let start = std::time::Instant::now();
    let timeout_ms = 2000u128;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => {
                if start.elapsed().as_millis() > timeout_ms {
                    let _ = child.kill();
                    let _ = child.wait();
                    eprintln!("ANUBIS_POC_TIMEOUT");
                    return anubis_target_run_result(0, -1, -1, payload.len() as i64, 1);
                }
                std::thread::sleep(std::time::Duration::from_millis(2));
            }
            Err(e) => {
                eprintln!("ANUBIS_POC_WAIT_FAILED: {}", e);
                return anubis_target_run_result(0, -1, -1, payload.len() as i64, 0);
            }
        }
    }
    let status = match child.wait() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("ANUBIS_POC_WAIT_FAILED: {}", e);
            return anubis_target_run_result(0, -1, -1, payload.len() as i64, 0);
        }
    };
    #[cfg(unix)]
    let signal = status.signal().unwrap_or(-1);
    #[cfg(not(unix))]
    let signal = -1i32;
    let exit_code = status.code().unwrap_or(-1);
    let crashed = if signal > 0 { 1 } else { 0 };
    anubis_target_run_result(
        crashed,
        signal as i64,
        exit_code as i64,
        payload.len() as i64,
        0,
    )
}


fn anubis_proof_input_u32_val(name: &str) -> AnubisValue {
    // Lightweight env map: ANUBIS_PROOF_INPUTS="k=v,k2=v2"
    if let Ok(raw) = std::env::var("ANUBIS_PROOF_INPUTS") {
        for part in raw.split(',') {
            let mut it = part.splitn(2, '=');
            if let (Some(k), Some(v)) = (it.next(), it.next()) {
                if k.trim() == name {
                    if let Ok(n) = v.trim().parse::<i64>() {
                        return AnubisValue::Int(n);
                    }
                }
            }
        }
    }
    panic!(
        "ANUBIS_PROOF_INPUT_MISSING: key `{}` (set ANUBIS_PROOF_INPUTS=k=v for run, or use prove --input-json)",
        name
    );
}
fn anubis_proof_input_bool_val(name: &str) -> AnubisValue {
    AnubisValue::Bool(anubis_proof_input_u32_val(name).as_i64() != 0)
}
fn anubis_proof_commit_u32(_name: &str, v: AnubisValue) -> AnubisValue { v }
fn anubis_proof_commit_bool(_name: &str, v: AnubisValue) -> AnubisValue {
    AnubisValue::Int(if v.as_bool() { 1 } else { 0 })
}
fn anubis_proof_assert(cond: AnubisValue) -> AnubisValue {
    if !cond.as_bool() {
        panic!("ANUBIS_PROOF_ASSERT_FAILED");
    }
    AnubisValue::Bool(true)
}

fn anb_domain_packs_core_core_pack__protocol_version() -> AnubisValue {
    __anb_stack_guard();
    return anubis_mk_str("1".to_string());
    AnubisValue::Int(0)
}

fn anb_domain_packs_core_core_pack__pack_id() -> AnubisValue {
    __anb_stack_guard();
    return anubis_mk_str("jackal.core.exact".to_string());
    AnubisValue::Int(0)
}

fn anb_domain_packs_core_core_pack__route_operation(mut requested_pack: AnubisValue, mut operation_id: AnubisValue, mut argument_count: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("!=", requested_pack.clone(), anb_domain_packs_core_core_pack__pack_id()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("pack-id-unknown: requested pack is not registered; fail closed".to_string()));
    }
    if anubis_cmp("==", operation_id.clone(), anubis_mk_str("core.exact.mod_pow.v1".to_string())).as_bool() {
        if anubis_cmp("!=", argument_count.clone(), AnubisValue::Int(3)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("pack-request-arity: core.exact.mod_pow.v1 requires exactly 3 arguments; fail closed".to_string()));
        }
        return anubis_mk_str("mod-pow".to_string());
    }
    anubis_panic(anubis_mk_str("pack-operation-unknown: no fallback is permitted; fail closed".to_string()))
}

fn anb_domain_packs_programming_programming_pack__protocol_version() -> AnubisValue {
    __anb_stack_guard();
    return anubis_mk_str("1".to_string());
    AnubisValue::Int(0)
}

fn anb_domain_packs_programming_programming_pack__pack_id() -> AnubisValue {
    __anb_stack_guard();
    return anubis_mk_str("jackal.programming.source".to_string());
    AnubisValue::Int(0)
}

fn anb_domain_packs_programming_programming_pack__route_operation(mut requested_pack: AnubisValue, mut operation_id: AnubisValue, mut argument_count: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("!=", requested_pack.clone(), anb_domain_packs_programming_programming_pack__pack_id()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("pack-id-unknown: requested pack is not registered; fail closed".to_string()));
    }
    if anubis_cmp("==", operation_id.clone(), anubis_mk_str("programming.source.test_exists.v1".to_string())).as_bool() {
        if anubis_cmp("!=", argument_count.clone(), AnubisValue::Int(5)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("pack-request-arity: programming.source.test_exists.v1 requires exactly 5 arguments; fail closed".to_string()));
        }
        return anubis_mk_str("test-exists".to_string());
    }
    if anubis_cmp("==", operation_id.clone(), anubis_mk_str("programming.source.claim_cites_test.v1".to_string())).as_bool() {
        if anubis_cmp("!=", argument_count.clone(), AnubisValue::Int(6)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("pack-request-arity: programming.source.claim_cites_test.v1 requires exactly 6 arguments; fail closed".to_string()));
        }
        return anubis_mk_str("claim-cites-test".to_string());
    }
    anubis_panic(anubis_mk_str("pack-operation-unknown: no fallback is permitted; fail closed".to_string()))
}

fn anb_domain_packs_decision_decision_pack__protocol_version() -> AnubisValue {
    __anb_stack_guard();
    return anubis_mk_str("1".to_string());
    AnubisValue::Int(0)
}

fn anb_domain_packs_decision_decision_pack__pack_id() -> AnubisValue {
    __anb_stack_guard();
    return anubis_mk_str("jackal.decision.matrix".to_string());
    AnubisValue::Int(0)
}

fn anb_domain_packs_decision_decision_pack__route_operation(mut requested_pack: AnubisValue, mut operation_id: AnubisValue, mut argument_count: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("!=", requested_pack.clone(), anb_domain_packs_decision_decision_pack__pack_id()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("pack-id-unknown: requested pack is not registered; fail closed".to_string()));
    }
    if anubis_cmp("==", operation_id.clone(), anubis_mk_str("decision.matrix.rank.v1".to_string())).as_bool() {
        if anubis_cmp("<", argument_count.clone(), AnubisValue::Int(7)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("pack-request-arity: decision.matrix.rank.v1 requires at least 7 arguments (id, criterion, sense, and two label/value pairs); fail closed".to_string()));
        }
        if anubis_cmp(">", argument_count.clone(), AnubisValue::Int(15)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("pack-request-arity: decision.matrix.rank.v1 accepts at most 6 options; fail closed".to_string()));
        }
        if anubis_cmp("!=", anubis_mod(anubis_sub(argument_count.clone(), AnubisValue::Int(3)), AnubisValue::Int(2)), AnubisValue::Int(0)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("pack-request-arity: decision.matrix.rank.v1 requires label/value pairs; fail closed".to_string()));
        }
        return anubis_mk_str("decision-rank".to_string());
    }
    anubis_panic(anubis_mk_str("pack-operation-unknown: no fallback is permitted; fail closed".to_string()))
}

fn anb_positive_abs(value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    fn __anb_body(mut value: AnubisValue) -> AnubisValue {
    anubis_require_int(&value, "value");
    if anubis_cmp("<", value.clone(), AnubisValue::Int(0)).as_bool() {
        return anubis_neg(value.clone());
    }
    return value.clone();
    AnubisValue::Int(0)
    }
    anubis_require_int_ret(__anb_body(value), "positive_abs")
}

fn anb_gcd_safe(a: AnubisValue, b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    fn __anb_body(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    anubis_require_int(&a, "a");
    anubis_require_int(&b, "b");
    let mut x = anb_positive_abs(a.clone());
    let mut y = anb_positive_abs(b.clone());
    while anubis_cmp("!=", y.clone(), AnubisValue::Int(0)).as_bool() {
        let mut remainder = anubis_mod(x.clone(), y.clone());
        x = y.clone();
        y = remainder.clone();
    }
    return x.clone();
    AnubisValue::Int(0)
    }
    anubis_require_int_ret(__anb_body(a, b), "gcd_safe")
}

fn anb_hex_digit(mut value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return (anubis_mk_str("0123456789ABCDEF".to_string())).index_get(value.clone());
    AnubisValue::Int(0)
}

fn anb_hex_unsigned(mut value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", value.clone(), AnubisValue::Int(0)).as_bool() {
        return anubis_mk_str("0".to_string());
    }
    let mut n = value.clone();
    let mut text = anubis_mk_str("".to_string());
    while anubis_cmp(">", n.clone(), AnubisValue::Int(0)).as_bool() {
        text = anubis_add(anb_hex_digit(anubis_mod(n.clone(), AnubisValue::Int(16))), text.clone());
        n = anubis_div(n.clone(), AnubisValue::Int(16));
    }
    return text.clone();
    AnubisValue::Int(0)
}

fn anb_format_hex(mut value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", value.clone(), AnubisValue::Int(0)).as_bool() {
        return anubis_add(anubis_mk_str("-0x".to_string()), anb_hex_unsigned(anb_positive_abs(value.clone())));
    }
    return anubis_add(anubis_mk_str("0x".to_string()), anb_hex_unsigned(value.clone()));
    AnubisValue::Int(0)
}

fn anb_binary_unsigned(mut value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", value.clone(), AnubisValue::Int(0)).as_bool() {
        return anubis_mk_str("0".to_string());
    }
    let mut n = value.clone();
    let mut text = anubis_mk_str("".to_string());
    while anubis_cmp(">", n.clone(), AnubisValue::Int(0)).as_bool() {
        text = anubis_add(anubis_str(anubis_mod(n.clone(), AnubisValue::Int(2))), text.clone());
        n = anubis_div(n.clone(), AnubisValue::Int(2));
    }
    return text.clone();
    AnubisValue::Int(0)
}

fn anb_format_binary(mut value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", value.clone(), AnubisValue::Int(0)).as_bool() {
        return anubis_add(anubis_mk_str("-0b".to_string()), anb_binary_unsigned(anb_positive_abs(value.clone())));
    }
    return anubis_add(anubis_mk_str("0b".to_string()), anb_binary_unsigned(value.clone()));
    AnubisValue::Int(0)
}

fn anb_usage() -> AnubisValue {
    __anb_stack_guard();
    println!("{}", anubis_mk_str("JACKAL CALC :: CLAIM-AWARE STEM ENGINE".to_string()).display_string());
    println!("{}", anubis_mk_str("trust:      claim-card self-test measure-mul uncertain-ohm kinetic-sensitivity".to_string()).display_string());
    println!("{}", anubis_mk_str("numerical:  matrix2 solve2 integrate-x2 derivative-x3".to_string()).display_string());
    println!("{}", anubis_mk_str("expression: eval integrate integrate-adaptive derivative solve   (variable x, ^ = power)".to_string()).display_string());
    println!("{}", anubis_mk_str("certified:  integrate-bound range-bound   (interval enclosures under a stated f64 model)".to_string()).display_string());
    println!("{}", anubis_mk_str("proof-carrying: range-bound-cert   (emits a Lean-checker-verifiable enclosure certificate)".to_string()).display_string());
    println!("{}", anubis_mk_str("symbolic:   diff \"x^2*sin(x)\"   (numerically-checked d/dx)".to_string()).display_string());
    println!("{}", anubis_mk_str("exact-rat:  rat \"0.1 + 0.2\"   (exact rational arithmetic)".to_string()).display_string());
    println!("{}", anubis_mk_str("worksheet:  worksheet \"a = 5; b = a^2; a+b\"   (variables persist across ;)".to_string()).display_string());
    println!("{}", anubis_mk_str("exact-int:  big-add big-mul big-pow big-fact big-ncr   (arbitrary precision)".to_string()).display_string());
    println!("{}", anubis_mk_str("exact-cert: xgcd mod-pow mod-inv crt divides prime-cert   (CERTIFIED EXACT ALGEBRA: number theory; final line = jackal-exact-cert-v1 JSON)".to_string()).display_string());
    println!("{}", anubis_mk_str("exact-cas:  canon poly-canon poly-eq poly-gcd ratfunc-canon roots-isolate alg-sign alg-cmp   (CERTIFIED EXACT ALGEBRA: Q[x], Sturm isolation)".to_string()).display_string());
    println!("{}", anubis_mk_str("science+:   ph dilute relativity decibel-power blackbody".to_string()).display_string());
    println!("{}", anubis_mk_str("science:    add sub mul div pow sqrt cbrt sin cos tan sin-deg hypot ln log10 exp".to_string()).display_string());
    println!("{}", anubis_mk_str("math:       quadratic lerp percent-error ncr gcd lcm fact prime".to_string()).display_string());
    println!("{}", anubis_mk_str("vectors:    dot cross norm3".to_string()).display_string());
    println!("{}", anubis_mk_str("data:       stats describe linreg".to_string()).display_string());
    println!("{}", anubis_mk_str("engineering: convert ohm parallel-r".to_string()).display_string());
    println!("{}", anubis_mk_str("physics:    kinetic projectile photon orbit ideal-gas molarity".to_string()).display_string());
    println!("{}", anubis_mk_str("programmer: hex bin band bor bxor shl shr".to_string()).display_string());
    println!("{}", anubis_mk_str("knowledge:  constants maturity   (maturity = per-command epistemic grades)".to_string()).display_string());
    println!("{}", anubis_mk_str("example:    jackal quadratic 1 -3 2".to_string()).display_string());
    AnubisValue::Int(0)
}

fn anb_require_arity(mut argv: AnubisValue, mut count: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("!=", (argv.clone()).len_val(), count.clone()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("wrong number of arguments; run with help".to_string()));
    }
    AnubisValue::Int(0)
}

fn anb_strict_float(mut text: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    { let __anb_m0 = anubis_parse_float_opt(text.clone()); let mut __anb_r0 = AnubisValue::Int(0); let mut __anb_done0 = false; if !__anb_done0 { if matches!(&__anb_m0, AnubisValue::Enum { ty, tag, .. } if ty == "Option" && tag == "Some") { let __anb_m0_p0 = (match &__anb_m0 { AnubisValue::Enum { fields, .. } if fields.len() > 0 => fields[0].clone(), _ => AnubisValue::Int(0) }); let mut v = __anb_m0_p0.clone(); __anb_r0 = ({ if anubis_cmp("!=", v.clone(), v.clone()).as_bool() {
    let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("not a finite number: '".to_string())), text.clone()), anubis_mk_str("'; fail closed".to_string())));
}
if AnubisValue::Bool((anubis_cmp(">", v.clone(), AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64))).as_bool() || (anubis_cmp("<", v.clone(), anubis_neg(AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64)))).as_bool()).as_bool() {
    let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("not a finite number: '".to_string())), text.clone()), anubis_mk_str("'; fail closed".to_string())));
}
return v.clone();
 AnubisValue::Int(0) }); __anb_done0 = true; } } if !__anb_done0 { if matches!(&__anb_m0, AnubisValue::Enum { ty, tag, .. } if ty == "Option" && tag == "None") { __anb_r0 = (anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("not a valid number: '".to_string())), text.clone()), anubis_mk_str("'; fail closed".to_string())))); __anb_done0 = true; } } if !__anb_done0 { panic!("ANUBIS_MATCH_UNMATCHED: no match arm matched value `{}` (add a `_` arm)", (__anb_m0).display_string()); } __anb_r0 }
}

fn anb_strict_int(mut text: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    { let __anb_m1 = anubis_parse_int_opt(text.clone()); let mut __anb_r1 = AnubisValue::Int(0); let mut __anb_done1 = false; if !__anb_done1 { if matches!(&__anb_m1, AnubisValue::Enum { ty, tag, .. } if ty == "Option" && tag == "Some") { let __anb_m1_p0 = (match &__anb_m1 { AnubisValue::Enum { fields, .. } if fields.len() > 0 => fields[0].clone(), _ => AnubisValue::Int(0) }); let mut v = __anb_m1_p0.clone(); __anb_r1 = (v.clone()); __anb_done1 = true; } } if !__anb_done1 { if matches!(&__anb_m1, AnubisValue::Enum { ty, tag, .. } if ty == "Option" && tag == "None") { __anb_r1 = (anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("not a valid integer: '".to_string())), text.clone()), anubis_mk_str("'; fail closed".to_string())))); __anb_done1 = true; } } if !__anb_done1 { panic!("ANUBIS_MATCH_UNMATCHED: no match arm matched value `{}` (add a `_` arm)", (__anb_m1).display_string()); } __anb_r1 }
}

fn anb_unary_float(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
    return anb_strict_float(argv.index_get(AnubisValue::Int(1)));
    AnubisValue::Int(0)
}

fn anb_binary_float_left(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
    return anb_strict_float(argv.index_get(AnubisValue::Int(1)));
    AnubisValue::Int(0)
}

fn anb_binary_float_right(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_strict_float(argv.index_get(AnubisValue::Int(2)));
    AnubisValue::Int(0)
}

fn anb_binary_int_left(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
    return anb_strict_int(argv.index_get(AnubisValue::Int(1)));
    AnubisValue::Int(0)
}

fn anb_binary_int_right(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_strict_int(argv.index_get(AnubisValue::Int(2)));
    AnubisValue::Int(0)
}

fn anb_shift_count(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut count = anb_binary_int_right(argv.clone());
    if AnubisValue::Bool((anubis_cmp("<", count.clone(), AnubisValue::Int(0))).as_bool() || (anubis_cmp(">", count.clone(), AnubisValue::Int(63))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("shift count must be within 0..63 on the i64 register model; fail closed".to_string()));
    }
    return count.clone();
    AnubisValue::Int(0)
}

fn anb_rounded(mut value: AnubisValue, mut places: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("!=", value.clone(), value.clone()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("rounded: non-finite value (NaN); fail closed".to_string()));
    }
    if AnubisValue::Bool((anubis_cmp(">", value.clone(), AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64))).as_bool() || (anubis_cmp("<", value.clone(), anubis_neg(AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64)))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("rounded: non-finite value (inf); fail closed".to_string()));
    }
    let mut scale = anubis_pow(AnubisValue::Float(10f64), places.clone());
    let mut scaled = anubis_mul(value.clone(), scale.clone());
    if AnubisValue::Bool((anubis_cmp(">=", scaled.clone(), AnubisValue::Float(9007199254740992f64))).as_bool() || (anubis_cmp("<=", scaled.clone(), anubis_neg(AnubisValue::Float(9007199254740992f64)))).as_bool()).as_bool() {
        return value.clone();
    }
    return anubis_div(anubis_round(scaled.clone()), scale.clone());
    AnubisValue::Int(0)
}

fn anb_refuse_non_finite(mut value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("!=", value.clone(), value.clone()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("non-finite value (NaN) reached output; fail closed — check inputs".to_string()));
    }
    if AnubisValue::Bool((anubis_cmp(">", value.clone(), AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64))).as_bool() || (anubis_cmp("<", value.clone(), anubis_neg(AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64)))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("non-finite value (inf) reached output; fail closed — check inputs".to_string()));
    }
    return value.clone();
    AnubisValue::Int(0)
}

fn anb_integer_renderable(mut value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", value.clone(), anubis_trunc(value.clone()))).as_bool() && (anubis_cmp("<", value.clone(), AnubisValue::Float(9007199254740992f64))).as_bool())).as_bool() && (anubis_cmp(">", value.clone(), anubis_neg(AnubisValue::Float(9007199254740992f64)))).as_bool());
    AnubisValue::Int(0)
}

fn anb_print_number(mut value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_refuse_non_finite(value.clone());
    if (anb_integer_renderable(value.clone())).as_bool() { { println!("{}", anubis_int(value.clone()).display_string());
 AnubisValue::Int(0) } } else { { println!("{}", value.clone().display_string());
 AnubisValue::Int(0) } }
}

fn anb_number_text(mut value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_refuse_non_finite(value.clone());
    if anb_integer_renderable(value.clone()).as_bool() {
        return anubis_str(anubis_int(value.clone()));
    }
    return anubis_str(value.clone());
    AnubisValue::Int(0)
}

fn anb_stats(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", (argv.clone()).len_val(), AnubisValue::Int(2)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("stats requires at least one value".to_string()));
    }
    let mut first = anb_strict_float(argv.index_get(AnubisValue::Int(1)));
    let mut total = AnubisValue::Float(0f64);
    let mut low = first.clone();
    let mut high = first.clone();
    let mut i = AnubisValue::Int(1);
    while anubis_cmp("<", i.clone(), (argv.clone()).len_val()).as_bool() {
        let mut value = anb_strict_float(argv.index_get(i.clone()));
        total = anubis_add(total.clone(), value.clone());
        if anubis_cmp("<", value.clone(), low.clone()).as_bool() {
            low = value.clone();
        }
        if anubis_cmp(">", value.clone(), high.clone()).as_bool() {
            high = value.clone();
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    let mut count = anubis_sub((argv.clone()).len_val(), AnubisValue::Int(1));
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("n=".to_string())), count.clone()), anubis_mk_str(" sum=".to_string())), anb_number_text(total.clone())), anubis_mk_str(" mean=".to_string())), anb_number_text(anubis_div(total.clone(), count.clone()))), anubis_mk_str(" min=".to_string())), anb_number_text(low.clone())), anubis_mk_str(" max=".to_string())), anb_number_text(high.clone())).display_string());
    AnubisValue::Int(0)
}

fn anb_arg_float(mut argv: AnubisValue, mut index: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_strict_float(argv.index_get(index.clone()));
    AnubisValue::Int(0)
}

fn anb_arg_int(mut argv: AnubisValue, mut index: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_strict_int(argv.index_get(index.clone()));
    AnubisValue::Int(0)
}

fn anb_vec3(mut argv: AnubisValue, mut offset: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Struct { ty: "Vec3".to_string(), fields: vec![("x".to_string(), anubis_field_coerce_float(anb_arg_float(argv.clone(), offset.clone()), "x")), ("y".to_string(), anubis_field_coerce_float(anb_arg_float(argv.clone(), anubis_add(offset.clone(), AnubisValue::Int(1))), "y")), ("z".to_string(), anubis_field_coerce_float(anb_arg_float(argv.clone(), anubis_add(offset.clone(), AnubisValue::Int(2))), "z"))] };
    AnubisValue::Int(0)
}

fn anb_dot3(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_add(anubis_add(anubis_mul(a.field_get("x"), b.field_get("x")), anubis_mul(a.field_get("y"), b.field_get("y"))), anubis_mul(a.field_get("z"), b.field_get("z")));
    AnubisValue::Int(0)
}

fn anb_cross3(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Struct { ty: "Vec3".to_string(), fields: vec![("x".to_string(), anubis_field_coerce_float(anubis_sub(anubis_mul(a.field_get("y"), b.field_get("z")), anubis_mul(a.field_get("z"), b.field_get("y"))), "x")), ("y".to_string(), anubis_field_coerce_float(anubis_sub(anubis_mul(a.field_get("z"), b.field_get("x")), anubis_mul(a.field_get("x"), b.field_get("z"))), "y")), ("z".to_string(), anubis_field_coerce_float(anubis_sub(anubis_mul(a.field_get("x"), b.field_get("y")), anubis_mul(a.field_get("y"), b.field_get("x"))), "z"))] };
    AnubisValue::Int(0)
}

fn anb_norm_vec3(mut v: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_sqrt(anb_dot3(v.clone(), v.clone()));
    AnubisValue::Int(0)
}

fn anb_vec_text(mut v: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("[".to_string())), anb_number_text(v.field_get("x"))), anubis_mk_str(",".to_string())), anb_number_text(v.field_get("y"))), anubis_mk_str(",".to_string())), anb_number_text(v.field_get("z"))), anubis_mk_str("]".to_string()));
    AnubisValue::Int(0)
}

fn anb_quadratic(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(4));
    let mut a = anb_arg_float(argv.clone(), AnubisValue::Int(1));
    let mut b = anb_arg_float(argv.clone(), AnubisValue::Int(2));
    let mut c = anb_arg_float(argv.clone(), AnubisValue::Int(3));
    if anubis_cmp("==", a.clone(), AnubisValue::Float(0f64)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("quadratic coefficient a must be nonzero".to_string()));
    }
    let mut discriminant = anubis_sub(anubis_mul(b.clone(), b.clone()), anubis_mul(anubis_mul(AnubisValue::Float(4f64), a.clone()), c.clone()));
    if (anubis_cmp(">=", discriminant.clone(), AnubisValue::Float(0f64))).as_bool() { { let mut root = anubis_sqrt(discriminant.clone());
let mut first = anubis_div(anubis_add(anubis_neg(b.clone()), root.clone()), anubis_mul(AnubisValue::Float(2f64), a.clone()));
let mut second = anubis_div(anubis_sub(anubis_neg(b.clone()), root.clone()), anubis_mul(AnubisValue::Float(2f64), a.clone()));
println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("roots=".to_string())), anb_number_text(first.clone())), anubis_mk_str(",".to_string())), anb_number_text(second.clone())), anubis_mk_str(" discriminant=".to_string())), anb_number_text(discriminant.clone())).display_string());
 AnubisValue::Int(0) } } else { { let mut real = anubis_div(anubis_neg(b.clone()), anubis_mul(AnubisValue::Float(2f64), a.clone()));
let mut imaginary = anubis_div(anubis_sqrt(anubis_neg(discriminant.clone())), anubis_abs(anubis_mul(AnubisValue::Float(2f64), a.clone())));
println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("complex roots: real=".to_string())), anb_number_text(real.clone())), anubis_mk_str(" imaginary=".to_string())), anb_number_text(imaginary.clone())).display_string());
 AnubisValue::Int(0) } }
}

fn anb_choose(mut n: AnubisValue, mut r: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("<", n.clone(), AnubisValue::Int(0))).as_bool() || (anubis_cmp("<", r.clone(), AnubisValue::Int(0))).as_bool())).as_bool() || (anubis_cmp(">", r.clone(), n.clone())).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("nCr requires 0 <= r <= n".to_string()));
    }
    let mut k = r.clone();
    if anubis_cmp("<", anubis_sub(n.clone(), r.clone()), k.clone()).as_bool() {
        k = anubis_sub(n.clone(), r.clone());
    }
    let mut limit = AnubisValue::Int(9223372036854775807);
    let mut result = AnubisValue::Int(1);
    let mut i = AnubisValue::Int(1);
    while anubis_cmp("<=", i.clone(), k.clone()).as_bool() {
        let mut factor = anubis_add(anubis_sub(n.clone(), k.clone()), i.clone());
        let mut g = anb_gcd_safe(factor.clone(), i.clone());
        let mut reduced_factor = anubis_div(factor.clone(), g.clone());
        let mut reduced_step = anubis_div(i.clone(), g.clone());
        let mut partial = anubis_div(result.clone(), reduced_step.clone());
        if anubis_cmp(">", partial.clone(), anubis_div(limit.clone(), reduced_factor.clone())).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("nCr overflow: C(".to_string())), n.clone()), anubis_mk_str(",".to_string())), r.clone()), anubis_mk_str(") exceeds i64; fail closed rather than wrap".to_string())));
        }
        result = anubis_mul(partial.clone(), reduced_factor.clone());
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return result.clone();
    AnubisValue::Int(0)
}

fn anb_prime_verdict(mut value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", value.clone(), AnubisValue::Int(2)).as_bool() {
        return AnubisValue::Enum { ty: "PrimeVerdict".to_string(), tag: "OutsideDomain".to_string(), fields: vec![value.clone()], field_names: vec![] };
    }
    if anubis_cmp("==", value.clone(), AnubisValue::Int(2)).as_bool() {
        return AnubisValue::Enum { ty: "PrimeVerdict".to_string(), tag: "Prime".to_string(), fields: vec![value.clone()], field_names: vec![] };
    }
    if anubis_cmp("==", anubis_mod(value.clone(), AnubisValue::Int(2)), AnubisValue::Int(0)).as_bool() {
        return AnubisValue::Enum { ty: "PrimeVerdict".to_string(), tag: "Composite".to_string(), fields: vec![value.clone(), AnubisValue::Int(2)], field_names: vec!["value".to_string(), "divisor".to_string()] };
    }
    let mut divisor = AnubisValue::Int(3);
    while anubis_cmp("<=", divisor.clone(), anubis_div(value.clone(), divisor.clone())).as_bool() {
        if anubis_cmp("==", anubis_mod(value.clone(), divisor.clone()), AnubisValue::Int(0)).as_bool() {
            return AnubisValue::Enum { ty: "PrimeVerdict".to_string(), tag: "Composite".to_string(), fields: vec![value.clone(), divisor.clone()], field_names: vec!["value".to_string(), "divisor".to_string()] };
        }
        divisor = anubis_add(divisor.clone(), AnubisValue::Int(2));
    }
    return AnubisValue::Enum { ty: "PrimeVerdict".to_string(), tag: "Prime".to_string(), fields: vec![value.clone()], field_names: vec![] };
    AnubisValue::Int(0)
}

fn anb_print_prime(mut value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    { let __anb_m2 = anb_prime_verdict(value.clone()); let mut __anb_r2 = AnubisValue::Int(0); let mut __anb_done2 = false; if !__anb_done2 { if matches!(&__anb_m2, AnubisValue::Enum { ty, tag, .. } if ty == "PrimeVerdict" && tag == "Prime") { let __anb_m2_p0 = (match &__anb_m2 { AnubisValue::Enum { fields, .. } if fields.len() > 0 => fields[0].clone(), _ => AnubisValue::Int(0) }); let mut n = __anb_m2_p0.clone(); __anb_r2 = ({ println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), n.clone()), anubis_mk_str(" is prime".to_string())).display_string()); AnubisValue::Int(0) }); __anb_done2 = true; } } if !__anb_done2 { if matches!(&__anb_m2, AnubisValue::Enum { ty, tag, .. } if ty == "PrimeVerdict" && tag == "Composite") { let __anb_m2_nf_value = (match &__anb_m2 { AnubisValue::Enum { fields, field_names, .. } => { let mut __v = AnubisValue::Int(0); for (__i, __n) in field_names.iter().enumerate() { if __n == &"value" { if let Some(__f) = fields.get(__i) { __v = __f.clone(); } break; } } __v }, _ => AnubisValue::Int(0) }); let mut n = __anb_m2_nf_value.clone(); let __anb_m2_nf_divisor = (match &__anb_m2 { AnubisValue::Enum { fields, field_names, .. } => { let mut __v = AnubisValue::Int(0); for (__i, __n) in field_names.iter().enumerate() { if __n == &"divisor" { if let Some(__f) = fields.get(__i) { __v = __f.clone(); } break; } } __v }, _ => AnubisValue::Int(0) }); let mut d = __anb_m2_nf_divisor.clone(); __anb_r2 = ({ println!("{}", anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), n.clone()), anubis_mk_str(" is composite; factor=".to_string())), d.clone()).display_string()); AnubisValue::Int(0) }); __anb_done2 = true; } } if !__anb_done2 { if matches!(&__anb_m2, AnubisValue::Enum { ty, tag, .. } if ty == "PrimeVerdict" && tag == "OutsideDomain") { let __anb_m2_p0 = (match &__anb_m2 { AnubisValue::Enum { fields, .. } if fields.len() > 0 => fields[0].clone(), _ => AnubisValue::Int(0) }); let mut n = __anb_m2_p0.clone(); __anb_r2 = ({ println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), n.clone()), anubis_mk_str(" is outside the prime domain".to_string())).display_string()); AnubisValue::Int(0) }); __anb_done2 = true; } } if !__anb_done2 { panic!("ANUBIS_MATCH_UNMATCHED: no match arm matched value `{}` (add a `_` arm)", (__anb_m2).display_string()); } __anb_r2 }
}

fn anb_sorted_samples(mut argv: AnubisValue, mut start: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut values = anubis_mk_list(vec![]);
    let mut i = start.clone();
    while anubis_cmp("<", i.clone(), (argv.clone()).len_val()).as_bool() {
        values.push_val(anb_arg_float(argv.clone(), i.clone()));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return anubis_sort(values.clone());
    AnubisValue::Int(0)
}

fn anb_median(mut values: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut n = (values.clone()).len_val();
    if anubis_cmp("==", n.clone(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("median requires data".to_string()));
    }
    let mut middle = anubis_div(n.clone(), AnubisValue::Int(2));
    if anubis_cmp("==", anubis_mod(n.clone(), AnubisValue::Int(2)), AnubisValue::Int(1)).as_bool() {
        return values.index_get(middle.clone());
    }
    return anubis_div(anubis_add(values.index_get(anubis_sub(middle.clone(), AnubisValue::Int(1))), values.index_get(middle.clone())), AnubisValue::Float(2f64));
    AnubisValue::Int(0)
}

fn anb_describe(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", (argv.clone()).len_val(), AnubisValue::Int(2)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("describe requires data".to_string()));
    }
    let mut values = anb_sorted_samples(argv.clone(), AnubisValue::Int(1));
    let mut total = AnubisValue::Float(0f64);
    for mut value in anubis_iter(values.clone()) {
        total = anubis_add(total.clone(), value.clone());
    }
    let mut mean = anubis_div(total.clone(), (values.clone()).len_val());
    let mut squared = AnubisValue::Float(0f64);
    for mut value in anubis_iter(values.clone()) {
        let mut delta = anubis_sub(value.clone(), mean.clone());
        squared = anubis_add(squared.clone(), anubis_mul(delta.clone(), delta.clone()));
    }
    let mut variance = anubis_div(squared.clone(), (values.clone()).len_val());
    let mut span = anubis_sub(values.index_get(anubis_sub((values.clone()).len_val(), AnubisValue::Int(1))), values.index_get(AnubisValue::Int(0)));
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("n=".to_string())), (values.clone()).len_val()), anubis_mk_str(" mean=".to_string())), anb_number_text(mean.clone())), anubis_mk_str(" median=".to_string())), anb_number_text(anb_median(values.clone()))), anubis_mk_str(" variance=".to_string())), anb_number_text(variance.clone())), anubis_mk_str(" sd=".to_string())), anb_number_text(anubis_sqrt(variance.clone()))), anubis_mk_str(" range=".to_string())), anb_number_text(span.clone())).display_string());
    AnubisValue::Int(0)
}

fn anb_linear_regression(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp("<", (argv.clone()).len_val(), AnubisValue::Int(5))).as_bool() || (anubis_cmp("!=", anubis_mod(anubis_sub((argv.clone()).len_val(), AnubisValue::Int(1)), AnubisValue::Int(2)), AnubisValue::Int(0))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("linreg requires x y pairs".to_string()));
    }
    let mut n = anubis_div(anubis_sub((argv.clone()).len_val(), AnubisValue::Int(1)), AnubisValue::Int(2));
    let mut sx = AnubisValue::Float(0f64);
    let mut sy = AnubisValue::Float(0f64);
    let mut sxx = AnubisValue::Float(0f64);
    let mut syy = AnubisValue::Float(0f64);
    let mut sxy = AnubisValue::Float(0f64);
    let mut i = AnubisValue::Int(1);
    while anubis_cmp("<", i.clone(), (argv.clone()).len_val()).as_bool() {
        let mut x = anb_arg_float(argv.clone(), i.clone());
        let mut y = anb_arg_float(argv.clone(), anubis_add(i.clone(), AnubisValue::Int(1)));
        sx = anubis_add(sx.clone(), x.clone());
        sy = anubis_add(sy.clone(), y.clone());
        sxx = anubis_add(sxx.clone(), anubis_mul(x.clone(), x.clone()));
        syy = anubis_add(syy.clone(), anubis_mul(y.clone(), y.clone()));
        sxy = anubis_add(sxy.clone(), anubis_mul(x.clone(), y.clone()));
        i = anubis_add(i.clone(), AnubisValue::Int(2));
    }
    let mut denominator = anubis_sub(anubis_mul(n.clone(), sxx.clone()), anubis_mul(sx.clone(), sx.clone()));
    let mut corr_denominator = anubis_sqrt(anubis_mul(anubis_sub(anubis_mul(n.clone(), sxx.clone()), anubis_mul(sx.clone(), sx.clone())), anubis_sub(anubis_mul(n.clone(), syy.clone()), anubis_mul(sy.clone(), sy.clone()))));
    if AnubisValue::Bool((anubis_cmp("==", denominator.clone(), AnubisValue::Float(0f64))).as_bool() || (anubis_cmp("==", corr_denominator.clone(), AnubisValue::Float(0f64))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("linreg requires varying x and y".to_string()));
    }
    let mut slope = anubis_div(anubis_sub(anubis_mul(n.clone(), sxy.clone()), anubis_mul(sx.clone(), sy.clone())), denominator.clone());
    return AnubisValue::Struct { ty: "Regression".to_string(), fields: vec![("slope".to_string(), anubis_field_coerce_float(slope.clone(), "slope")), ("intercept".to_string(), anubis_field_coerce_float(anubis_div(anubis_sub(sy.clone(), anubis_mul(slope.clone(), sx.clone())), n.clone()), "intercept")), ("correlation".to_string(), anubis_field_coerce_float(anubis_div(anubis_sub(anubis_mul(n.clone(), sxy.clone()), anubis_mul(sx.clone(), sy.clone())), corr_denominator.clone()), "correlation"))] };
    AnubisValue::Int(0)
}

fn anb_print_regression(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut fit = anb_linear_regression(argv.clone());
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("y=".to_string())), anb_number_text(fit.field_get("slope"))), anubis_mk_str("*x+".to_string())), anb_number_text(fit.field_get("intercept"))), anubis_mk_str(" r=".to_string())), anb_number_text(fit.field_get("correlation"))), anubis_mk_str(" r2=".to_string())), anb_number_text(anubis_mul(fit.field_get("correlation"), fit.field_get("correlation")))).display_string());
    AnubisValue::Int(0)
}

fn anb_convert_unit(mut value: AnubisValue, mut source: AnubisValue, mut target: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", source.clone(), target.clone()).as_bool() {
        return value.clone();
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("km".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("m".to_string()))).as_bool()).as_bool() {
        return anubis_mul(value.clone(), AnubisValue::Float(1000f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("m".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("km".to_string()))).as_bool()).as_bool() {
        return anubis_div(value.clone(), AnubisValue::Float(1000f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("cm".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("m".to_string()))).as_bool()).as_bool() {
        return anubis_div(value.clone(), AnubisValue::Float(100f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("m".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("cm".to_string()))).as_bool()).as_bool() {
        return anubis_mul(value.clone(), AnubisValue::Float(100f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("in".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("m".to_string()))).as_bool()).as_bool() {
        return anubis_mul(value.clone(), AnubisValue::Float(0.0254f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("m".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("in".to_string()))).as_bool()).as_bool() {
        return anubis_div(value.clone(), AnubisValue::Float(0.0254f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("ft".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("m".to_string()))).as_bool()).as_bool() {
        return anubis_mul(value.clone(), AnubisValue::Float(0.3048f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("m".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("ft".to_string()))).as_bool()).as_bool() {
        return anubis_div(value.clone(), AnubisValue::Float(0.3048f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("kg".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("g".to_string()))).as_bool()).as_bool() {
        return anubis_mul(value.clone(), AnubisValue::Float(1000f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("g".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("kg".to_string()))).as_bool()).as_bool() {
        return anubis_div(value.clone(), AnubisValue::Float(1000f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("lb".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("kg".to_string()))).as_bool()).as_bool() {
        return anubis_mul(value.clone(), AnubisValue::Float(0.45359237f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("kg".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("lb".to_string()))).as_bool()).as_bool() {
        return anubis_div(value.clone(), AnubisValue::Float(0.45359237f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("C".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("F".to_string()))).as_bool()).as_bool() {
        return anubis_add(anubis_div(anubis_mul(value.clone(), AnubisValue::Float(9f64)), AnubisValue::Float(5f64)), AnubisValue::Float(32f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("F".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("C".to_string()))).as_bool()).as_bool() {
        return anubis_div(anubis_mul(anubis_sub(value.clone(), AnubisValue::Float(32f64)), AnubisValue::Float(5f64)), AnubisValue::Float(9f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("C".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("K".to_string()))).as_bool()).as_bool() {
        return anubis_add(value.clone(), AnubisValue::Float(273.15f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("K".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("C".to_string()))).as_bool()).as_bool() {
        return anubis_sub(value.clone(), AnubisValue::Float(273.15f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("atm".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("Pa".to_string()))).as_bool()).as_bool() {
        return anubis_mul(value.clone(), AnubisValue::Float(101325f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("Pa".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("atm".to_string()))).as_bool()).as_bool() {
        return anubis_div(value.clone(), AnubisValue::Float(101325f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("bar".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("Pa".to_string()))).as_bool()).as_bool() {
        return anubis_mul(value.clone(), AnubisValue::Float(100000f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("Pa".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("bar".to_string()))).as_bool()).as_bool() {
        return anubis_div(value.clone(), AnubisValue::Float(100000f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("kWh".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("J".to_string()))).as_bool()).as_bool() {
        return anubis_mul(value.clone(), AnubisValue::Float(3600000f64));
    }
    if AnubisValue::Bool((anubis_cmp("==", source.clone(), anubis_mk_str("J".to_string()))).as_bool() && (anubis_cmp("==", target.clone(), anubis_mk_str("kWh".to_string()))).as_bool()).as_bool() {
        return anubis_div(value.clone(), AnubisValue::Float(3600000f64));
    }
    anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("unsupported or dimension-mismatched conversion: ".to_string())), source.clone()), anubis_mk_str(" -> ".to_string())), target.clone()))
}

fn anb_print_conversion(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(4));
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anb_number_text(anb_convert_unit(anb_arg_float(argv.clone(), AnubisValue::Int(1)), argv.index_get(AnubisValue::Int(2)), argv.index_get(AnubisValue::Int(3))))), anubis_mk_str(" ".to_string())), argv.index_get(AnubisValue::Int(3))).display_string());
    AnubisValue::Int(0)
}

fn anb_print_ohm(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(4));
    let mut mode = argv.index_get(AnubisValue::Int(1));
    let mut first = anb_arg_float(argv.clone(), AnubisValue::Int(2));
    let mut second = anb_arg_float(argv.clone(), AnubisValue::Int(3));
    let mut voltage = AnubisValue::Float(0f64);
    let mut current = AnubisValue::Float(0f64);
    let mut resistance = AnubisValue::Float(0f64);
    if anubis_cmp("==", mode.clone(), anubis_mk_str("v".to_string())).as_bool() {
        voltage = first.clone();
        resistance = second.clone();
        current = anubis_div(voltage.clone(), resistance.clone());
    } else {
        if anubis_cmp("==", mode.clone(), anubis_mk_str("i".to_string())).as_bool() {
            current = first.clone();
            resistance = second.clone();
            voltage = anubis_mul(current.clone(), resistance.clone());
        } else {
            if anubis_cmp("==", mode.clone(), anubis_mk_str("r".to_string())).as_bool() {
                voltage = first.clone();
                current = second.clone();
                resistance = anubis_div(voltage.clone(), current.clone());
            } else {
                let _ = anubis_panic(anubis_mk_str("ohm mode must be v, i, or r".to_string()));
            }
        }
    }
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("voltage=".to_string())), anb_number_text(voltage.clone())), anubis_mk_str(" V current=".to_string())), anb_number_text(current.clone())), anubis_mk_str(" A resistance=".to_string())), anb_number_text(resistance.clone())), anubis_mk_str(" ohm power=".to_string())), anb_number_text(anubis_mul(voltage.clone(), current.clone()))), anubis_mk_str(" W".to_string())).display_string());
    AnubisValue::Int(0)
}

fn anb_projectile(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(4));
    let mut speed = anb_arg_float(argv.clone(), AnubisValue::Int(1));
    let mut angle = anubis_div(anubis_mul(anb_arg_float(argv.clone(), AnubisValue::Int(2)), anubis_pi()), AnubisValue::Float(180f64));
    let mut gravity = anb_arg_float(argv.clone(), AnubisValue::Int(3));
    if anubis_cmp("<=", gravity.clone(), AnubisValue::Float(0f64)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("gravity must be positive".to_string()));
    }
    let mut flight = anubis_div(anubis_mul(anubis_mul(AnubisValue::Float(2f64), speed.clone()), anubis_sin(angle.clone())), gravity.clone());
    let mut distance = anubis_div(anubis_mul(anubis_mul(speed.clone(), speed.clone()), anubis_sin(anubis_mul(AnubisValue::Float(2f64), angle.clone()))), gravity.clone());
    let mut height = anubis_div(anubis_mul(anubis_mul(anubis_mul(speed.clone(), speed.clone()), anubis_sin(angle.clone())), anubis_sin(angle.clone())), anubis_mul(AnubisValue::Float(2f64), gravity.clone()));
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("range=".to_string())), anb_number_text(distance.clone())), anubis_mk_str(" m time=".to_string())), anb_number_text(flight.clone())), anubis_mk_str(" s max-height=".to_string())), anb_number_text(height.clone())), anubis_mk_str(" m".to_string())).display_string());
    AnubisValue::Int(0)
}

fn anb_orbit(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
    let mut radius = anb_arg_float(argv.clone(), AnubisValue::Int(1));
    let mut mu = anb_arg_float(argv.clone(), AnubisValue::Int(2));
    if AnubisValue::Bool((anubis_cmp("<=", radius.clone(), AnubisValue::Float(0f64))).as_bool() || (anubis_cmp("<=", mu.clone(), AnubisValue::Float(0f64))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("orbit radius and gravitational parameter must be positive".to_string()));
    }
    let mut speed = anubis_sqrt(anubis_div(mu.clone(), radius.clone()));
    let mut period = anubis_mul(anubis_mul(AnubisValue::Float(2f64), anubis_pi()), anubis_sqrt(anubis_div(anubis_mul(anubis_mul(radius.clone(), radius.clone()), radius.clone()), mu.clone())));
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("speed=".to_string())), anb_number_text(speed.clone())), anubis_mk_str(" m/s period=".to_string())), anb_number_text(period.clone())), anubis_mk_str(" s".to_string())).display_string());
    AnubisValue::Int(0)
}

fn anb_measurement(mut value: AnubisValue, mut uncertainty: AnubisValue, mut unit: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", uncertainty.clone(), AnubisValue::Float(0f64)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("measurement uncertainty must be nonnegative".to_string()));
    }
    return AnubisValue::Struct { ty: "Measurement".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(value.clone(), "value")), ("uncertainty".to_string(), anubis_field_coerce_float(uncertainty.clone(), "uncertainty")), ("unit".to_string(), unit.clone())] };
    AnubisValue::Int(0)
}

fn anb_relative_uncertainty(mut item: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", item.field_get("value"), AnubisValue::Float(0f64)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("relative uncertainty undefined at zero".to_string()));
    }
    return anubis_abs(anubis_div(item.field_get("uncertainty"), item.field_get("value")));
    AnubisValue::Int(0)
}

fn anb_multiply_measurements(mut left: AnubisValue, mut right: AnubisValue, mut output_unit: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut value = anubis_mul(left.field_get("value"), right.field_get("value"));
    let mut relative = anubis_add(anb_relative_uncertainty(left.clone()), anb_relative_uncertainty(right.clone()));
    return AnubisValue::Struct { ty: "Measurement".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(value.clone(), "value")), ("uncertainty".to_string(), anubis_field_coerce_float(anubis_mul(anubis_abs(value.clone()), relative.clone()), "uncertainty")), ("unit".to_string(), output_unit.clone())] };
    AnubisValue::Int(0)
}

fn anb_divide_measurements(mut numerator: AnubisValue, mut denominator: AnubisValue, mut output_unit: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", denominator.field_get("value"), AnubisValue::Float(0f64)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("measurement division by zero".to_string()));
    }
    let mut value = anubis_div(numerator.field_get("value"), denominator.field_get("value"));
    let mut relative = anubis_add(anb_relative_uncertainty(numerator.clone()), anb_relative_uncertainty(denominator.clone()));
    return AnubisValue::Struct { ty: "Measurement".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(value.clone(), "value")), ("uncertainty".to_string(), anubis_field_coerce_float(anubis_mul(anubis_abs(value.clone()), relative.clone()), "uncertainty")), ("unit".to_string(), output_unit.clone())] };
    AnubisValue::Int(0)
}

fn anb_measurement_text(mut item: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut relative = anubis_mul(anb_relative_uncertainty(item.clone()), AnubisValue::Float(100f64));
    return anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anb_number_text(item.field_get("value"))), anubis_mk_str(" ± ".to_string())), anb_number_text(anb_rounded(item.field_get("uncertainty"), AnubisValue::Float(12f64)))), anubis_mk_str(" ".to_string())), item.field_get("unit")), anubis_mk_str(" (".to_string())), anb_number_text(anb_rounded(relative.clone(), AnubisValue::Float(12f64)))), anubis_mk_str("%)".to_string()));
    AnubisValue::Int(0)
}

fn anb_matrix2(mut argv: AnubisValue, mut offset: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Struct { ty: "Matrix2".to_string(), fields: vec![("a".to_string(), anubis_field_coerce_float(anb_arg_float(argv.clone(), offset.clone()), "a")), ("b".to_string(), anubis_field_coerce_float(anb_arg_float(argv.clone(), anubis_add(offset.clone(), AnubisValue::Int(1))), "b")), ("c".to_string(), anubis_field_coerce_float(anb_arg_float(argv.clone(), anubis_add(offset.clone(), AnubisValue::Int(2))), "c")), ("d".to_string(), anubis_field_coerce_float(anb_arg_float(argv.clone(), anubis_add(offset.clone(), AnubisValue::Int(3))), "d"))] };
    AnubisValue::Int(0)
}

fn anb_determinant2(mut matrix: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_sub(anubis_mul(matrix.field_get("a"), matrix.field_get("d")), anubis_mul(matrix.field_get("b"), matrix.field_get("c")));
    AnubisValue::Int(0)
}

fn anb_inverse2(mut matrix: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut determinant = anb_determinant2(matrix.clone());
    if anubis_cmp("==", determinant.clone(), AnubisValue::Float(0f64)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("singular matrix has no inverse".to_string()));
    }
    return AnubisValue::Struct { ty: "Matrix2".to_string(), fields: vec![("a".to_string(), anubis_field_coerce_float(anubis_div(matrix.field_get("d"), determinant.clone()), "a")), ("b".to_string(), anubis_field_coerce_float(anubis_div(anubis_neg(matrix.field_get("b")), determinant.clone()), "b")), ("c".to_string(), anubis_field_coerce_float(anubis_div(anubis_neg(matrix.field_get("c")), determinant.clone()), "c")), ("d".to_string(), anubis_field_coerce_float(anubis_div(matrix.field_get("a"), determinant.clone()), "d"))] };
    AnubisValue::Int(0)
}

fn anb_matrix_text(mut matrix: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("[".to_string())), anb_number_text(matrix.field_get("a"))), anubis_mk_str(",".to_string())), anb_number_text(matrix.field_get("b"))), anubis_mk_str(";".to_string())), anb_number_text(matrix.field_get("c"))), anubis_mk_str(",".to_string())), anb_number_text(matrix.field_get("d"))), anubis_mk_str("]".to_string()));
    AnubisValue::Int(0)
}

fn anb_solve_linear2(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(7));
    let mut a = anb_arg_float(argv.clone(), AnubisValue::Int(1));
    let mut b = anb_arg_float(argv.clone(), AnubisValue::Int(2));
    let mut p = anb_arg_float(argv.clone(), AnubisValue::Int(3));
    let mut c = anb_arg_float(argv.clone(), AnubisValue::Int(4));
    let mut d = anb_arg_float(argv.clone(), AnubisValue::Int(5));
    let mut q = anb_arg_float(argv.clone(), AnubisValue::Int(6));
    let mut determinant = anubis_sub(anubis_mul(a.clone(), d.clone()), anubis_mul(b.clone(), c.clone()));
    if anubis_cmp("==", determinant.clone(), AnubisValue::Float(0f64)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("linear system is singular".to_string()));
    }
    let mut x = anubis_div(anubis_sub(anubis_mul(p.clone(), d.clone()), anubis_mul(b.clone(), q.clone())), determinant.clone());
    let mut y = anubis_div(anubis_sub(anubis_mul(a.clone(), q.clone()), anubis_mul(p.clone(), c.clone())), determinant.clone());
    let mut residual1 = anubis_abs(anubis_sub(anubis_add(anubis_mul(a.clone(), x.clone()), anubis_mul(b.clone(), y.clone())), p.clone()));
    let mut residual2 = anubis_abs(anubis_sub(anubis_add(anubis_mul(c.clone(), x.clone()), anubis_mul(d.clone(), y.clone())), q.clone()));
    let mut residual = anubis_max(vec![residual1.clone(), residual2.clone()]);
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("x=".to_string())), anb_number_text(x.clone())), anubis_mk_str(" y=".to_string())), anb_number_text(y.clone())), anubis_mk_str(" residual=".to_string())), anb_number_text(residual.clone())).display_string());
    AnubisValue::Int(0)
}

fn anb_integrate_square_simpson(mut start: AnubisValue, mut finish: AnubisValue, mut panels: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp("<=", panels.clone(), AnubisValue::Int(0))).as_bool() || (anubis_cmp("!=", anubis_mod(panels.clone(), AnubisValue::Int(2)), AnubisValue::Int(0))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("Simpson integration requires a positive even panel count".to_string()));
    }
    let mut width = anubis_div(anubis_sub(finish.clone(), start.clone()), panels.clone());
    let mut total = anubis_add(anubis_mul(start.clone(), start.clone()), anubis_mul(finish.clone(), finish.clone()));
    let mut i = AnubisValue::Int(1);
    while anubis_cmp("<", i.clone(), panels.clone()).as_bool() {
        let mut x = anubis_add(start.clone(), anubis_mul(i.clone(), width.clone()));
        let mut weight = if (anubis_cmp("==", anubis_mod(i.clone(), AnubisValue::Int(2)), AnubisValue::Int(0))).as_bool() { AnubisValue::Float(2f64) } else { AnubisValue::Float(4f64) };
        total = anubis_add(total.clone(), anubis_mul(anubis_mul(weight.clone(), x.clone()), x.clone()));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return anubis_div(anubis_mul(total.clone(), width.clone()), AnubisValue::Float(3f64));
    AnubisValue::Int(0)
}

fn anb_derivative_cube(mut value: AnubisValue, mut step: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<=", step.clone(), AnubisValue::Float(0f64)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("derivative step must be positive".to_string()));
    }
    return anubis_div(anubis_sub(anubis_pow(anubis_add(value.clone(), step.clone()), AnubisValue::Float(3f64)), anubis_pow(anubis_sub(value.clone(), step.clone()), AnubisValue::Float(3f64))), anubis_mul(AnubisValue::Float(2f64), step.clone()));
    AnubisValue::Int(0)
}

fn anb_spectrum_band(mut wavelength_nm: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", wavelength_nm.clone(), AnubisValue::Float(380f64)).as_bool() {
        return AnubisValue::Enum { ty: "SpectrumBand".to_string(), tag: "Ultraviolet".to_string(), fields: vec![], field_names: vec![] };
    }
    if anubis_cmp("<=", wavelength_nm.clone(), AnubisValue::Float(750f64)).as_bool() {
        return AnubisValue::Enum { ty: "SpectrumBand".to_string(), tag: "Visible".to_string(), fields: vec![], field_names: vec![] };
    }
    return AnubisValue::Enum { ty: "SpectrumBand".to_string(), tag: "Infrared".to_string(), fields: vec![], field_names: vec![] };
    AnubisValue::Int(0)
}

fn anb_spectrum_text(mut band: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return { let __anb_m3 = band.clone(); let mut __anb_r3 = AnubisValue::Int(0); let mut __anb_done3 = false; if !__anb_done3 { if matches!(&__anb_m3, AnubisValue::Enum { ty, tag, .. } if ty == "SpectrumBand" && tag == "Ultraviolet") { __anb_r3 = (anubis_mk_str("ultraviolet".to_string())); __anb_done3 = true; } } if !__anb_done3 { if matches!(&__anb_m3, AnubisValue::Enum { ty, tag, .. } if ty == "SpectrumBand" && tag == "Visible") { __anb_r3 = (anubis_mk_str("visible".to_string())); __anb_done3 = true; } } if !__anb_done3 { if matches!(&__anb_m3, AnubisValue::Enum { ty, tag, .. } if ty == "SpectrumBand" && tag == "Infrared") { __anb_r3 = (anubis_mk_str("infrared".to_string())); __anb_done3 = true; } } if !__anb_done3 { panic!("ANUBIS_MATCH_UNMATCHED: no match arm matched value `{}` (add a `_` arm)", (__anb_m3).display_string()); } __anb_r3 };
    AnubisValue::Int(0)
}

fn anb_require_finite_admission(mut value: AnubisValue, mut name: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("!=", value.clone(), value.clone())).as_bool() || (anubis_cmp(">", value.clone(), AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64))).as_bool())).as_bool() || (anubis_cmp("<", value.clone(), anubis_neg(AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64)))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("claim-card admission: ".to_string())), name.clone()), anubis_mk_str(" must be finite; a fingerprint is not an accept verdict; fail closed".to_string())));
    }
    AnubisValue::Int(0)
}

fn anb_projectile_claim_card(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(5));
    if anubis_cmp("!=", argv.index_get(AnubisValue::Int(1)), anubis_mk_str("projectile".to_string())).as_bool() {
        let _ = anubis_panic(anubis_mk_str("claim-card currently supports projectile".to_string()));
    }
    let mut speed = anb_arg_float(argv.clone(), AnubisValue::Int(2));
    let mut angle_degrees = anb_arg_float(argv.clone(), AnubisValue::Int(3));
    let mut gravity = anb_arg_float(argv.clone(), AnubisValue::Int(4));
    let _ = anb_require_finite_admission(speed.clone(), anubis_mk_str("speed".to_string()));
    let _ = anb_require_finite_admission(angle_degrees.clone(), anubis_mk_str("angle".to_string()));
    let _ = anb_require_finite_admission(gravity.clone(), anubis_mk_str("gravity".to_string()));
    if AnubisValue::Bool((anubis_cmp("<", speed.clone(), AnubisValue::Float(0f64))).as_bool() || (anubis_cmp("<=", gravity.clone(), AnubisValue::Float(0f64))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("invalid projectile claim inputs".to_string()));
    }
    let mut angle = anubis_div(anubis_mul(angle_degrees.clone(), anubis_pi()), AnubisValue::Float(180f64));
    let mut distance = anubis_div(anubis_mul(anubis_mul(speed.clone(), speed.clone()), anubis_sin(anubis_mul(AnubisValue::Float(2f64), angle.clone()))), gravity.clone());
    let mut flight = anubis_div(anubis_mul(anubis_mul(AnubisValue::Float(2f64), speed.clone()), anubis_sin(angle.clone())), gravity.clone());
    let mut height = anubis_div(anubis_mul(anubis_mul(anubis_mul(speed.clone(), speed.clone()), anubis_sin(angle.clone())), anubis_sin(angle.clone())), anubis_mul(AnubisValue::Float(2f64), gravity.clone()));
    let mut canonical = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("jackal-claim-v1|ideal-projectile|speed=".to_string())), speed.clone()), anubis_mk_str("|angle-deg=".to_string())), angle_degrees.clone()), anubis_mk_str("|gravity=".to_string())), gravity.clone()), anubis_mk_str("|range=".to_string())), distance.clone()), anubis_mk_str("|time=".to_string())), flight.clone()), anubis_mk_str("|height=".to_string())), height.clone());
    println!("{}", anubis_mk_str("JACKAL CLAIM CARD v1".to_string()).display_string());
    println!("{}", anubis_mk_str("status=model-based".to_string()).display_string());
    println!("{}", anubis_mk_str("model=ideal-projectile".to_string()).display_string());
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("inputs.speed=".to_string())), anb_number_text(speed.clone())), anubis_mk_str(" m/s inputs.angle=".to_string())), anb_number_text(angle_degrees.clone())), anubis_mk_str(" deg inputs.gravity=".to_string())), anb_number_text(gravity.clone())), anubis_mk_str(" m/s2".to_string())).display_string());
    println!("{}", anubis_mk_str("assumptions=same elevation; vacuum; constant gravity; point mass".to_string()).display_string());
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("observed.range=".to_string())), anb_number_text(distance.clone())), anubis_mk_str(" m observed.time=".to_string())), anb_number_text(flight.clone())), anubis_mk_str(" s observed.max-height=".to_string())), anb_number_text(height.clone())), anubis_mk_str(" m".to_string())).display_string());
    println!("{}", anubis_mk_str("sensitivity.speed=2 sensitivity.gravity=-1".to_string()).display_string());
    println!("{}", anubis_mk_str("non-claims=no drag; no wind; no terrain; no uncertainty inferred".to_string()).display_string());
    println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("canonical=".to_string())), canonical.clone()).display_string());
    println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("fingerprint.sha256=".to_string())), anubis_sha256(canonical.clone())).display_string());
    AnubisValue::Int(0)
}

fn anb_char_in(mut set: AnubisValue, mut ch: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (set.clone()).len_val()).as_bool() {
        if anubis_cmp("==", (set.clone()).index_get(i.clone()), ch.clone()).as_bool() {
            return AnubisValue::Bool(true);
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return AnubisValue::Bool(false);
    AnubisValue::Int(0)
}

fn anb_is_digit_char(mut ch: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_char_in(anubis_mk_str("0123456789".to_string()), ch.clone());
    AnubisValue::Int(0)
}

fn anb_is_alpha_char(mut ch: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_char_in(anubis_mk_str("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_".to_string()), ch.clone());
    AnubisValue::Int(0)
}

fn anb_make_token(mut kind: AnubisValue, mut num: AnubisValue, mut text: AnubisValue, mut at: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Struct { ty: "Token".to_string(), fields: vec![("kind".to_string(), kind.clone()), ("num".to_string(), anubis_field_coerce_float(num.clone(), "num")), ("text".to_string(), text.clone()), ("at".to_string(), anubis_field_require_int(at.clone(), "at"))] };
    AnubisValue::Int(0)
}

fn anb_tokenize(mut source: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tokens = anubis_mk_list(vec![]);
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (source.clone()).len_val()).as_bool() {
        let mut ch = (source.clone()).index_get(i.clone());
        if AnubisValue::Bool((anubis_cmp("==", ch.clone(), anubis_mk_str(" ".to_string()))).as_bool() || (anubis_cmp("==", ch.clone(), anubis_mk_str("\t".to_string()))).as_bool()).as_bool() {
            i = anubis_add(i.clone(), AnubisValue::Int(1));
            continue;
        }
        if anb_is_digit_char(ch.clone()).as_bool() {
            let mut start = i.clone();
            let mut text = anubis_mk_str("".to_string());
            while AnubisValue::Bool((anubis_cmp("<", i.clone(), (source.clone()).len_val())).as_bool() && (anb_is_digit_char((source.clone()).index_get(i.clone()))).as_bool()).as_bool() {
                text = anubis_add(text.clone(), (source.clone()).index_get(i.clone()));
                i = anubis_add(i.clone(), AnubisValue::Int(1));
            }
            if AnubisValue::Bool((anubis_cmp("<", i.clone(), (source.clone()).len_val())).as_bool() && (anubis_cmp("==", (source.clone()).index_get(i.clone()), anubis_mk_str(".".to_string()))).as_bool()).as_bool() {
                text = anubis_add(text.clone(), anubis_mk_str(".".to_string()));
                i = anubis_add(i.clone(), AnubisValue::Int(1));
                if AnubisValue::Bool((anubis_cmp(">=", i.clone(), (source.clone()).len_val())).as_bool() || (AnubisValue::Bool(!(anb_is_digit_char((source.clone()).index_get(i.clone()))).as_bool())).as_bool()).as_bool() {
                    let _ = anubis_panic(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: digits must follow the decimal point at offset ".to_string())), i.clone()));
                }
                while AnubisValue::Bool((anubis_cmp("<", i.clone(), (source.clone()).len_val())).as_bool() && (anb_is_digit_char((source.clone()).index_get(i.clone()))).as_bool()).as_bool() {
                    text = anubis_add(text.clone(), (source.clone()).index_get(i.clone()));
                    i = anubis_add(i.clone(), AnubisValue::Int(1));
                }
            }
            if AnubisValue::Bool((anubis_cmp("<", i.clone(), (source.clone()).len_val())).as_bool() && (AnubisValue::Bool((anubis_cmp("==", (source.clone()).index_get(i.clone()), anubis_mk_str("e".to_string()))).as_bool() || (anubis_cmp("==", (source.clone()).index_get(i.clone()), anubis_mk_str("E".to_string()))).as_bool())).as_bool()).as_bool() {
                let mut j = anubis_add(i.clone(), AnubisValue::Int(1));
                if AnubisValue::Bool((anubis_cmp("<", j.clone(), (source.clone()).len_val())).as_bool() && (AnubisValue::Bool((anubis_cmp("==", (source.clone()).index_get(j.clone()), anubis_mk_str("+".to_string()))).as_bool() || (anubis_cmp("==", (source.clone()).index_get(j.clone()), anubis_mk_str("-".to_string()))).as_bool())).as_bool()).as_bool() {
                    j = anubis_add(j.clone(), AnubisValue::Int(1));
                }
                if AnubisValue::Bool((anubis_cmp("<", j.clone(), (source.clone()).len_val())).as_bool() && (anb_is_digit_char((source.clone()).index_get(j.clone()))).as_bool()).as_bool() {
                    text = anubis_add(text.clone(), (source.clone()).index_get(i.clone()));
                    i = anubis_add(i.clone(), AnubisValue::Int(1));
                    if AnubisValue::Bool((anubis_cmp("==", (source.clone()).index_get(i.clone()), anubis_mk_str("+".to_string()))).as_bool() || (anubis_cmp("==", (source.clone()).index_get(i.clone()), anubis_mk_str("-".to_string()))).as_bool()).as_bool() {
                        text = anubis_add(text.clone(), (source.clone()).index_get(i.clone()));
                        i = anubis_add(i.clone(), AnubisValue::Int(1));
                    }
                    while AnubisValue::Bool((anubis_cmp("<", i.clone(), (source.clone()).len_val())).as_bool() && (anb_is_digit_char((source.clone()).index_get(i.clone()))).as_bool()).as_bool() {
                        text = anubis_add(text.clone(), (source.clone()).index_get(i.clone()));
                        i = anubis_add(i.clone(), AnubisValue::Int(1));
                    }
                }
            }
            tokens.push_val(anb_make_token(anubis_mk_str("num".to_string()), anubis_parse_float(text.clone()), text.clone(), start.clone()));
            continue;
        }
        if anb_is_alpha_char(ch.clone()).as_bool() {
            let mut start = i.clone();
            let mut text = anubis_mk_str("".to_string());
            while AnubisValue::Bool((anubis_cmp("<", i.clone(), (source.clone()).len_val())).as_bool() && (AnubisValue::Bool((anb_is_alpha_char((source.clone()).index_get(i.clone()))).as_bool() || (anb_is_digit_char((source.clone()).index_get(i.clone()))).as_bool())).as_bool()).as_bool() {
                text = anubis_add(text.clone(), (source.clone()).index_get(i.clone()));
                i = anubis_add(i.clone(), AnubisValue::Int(1));
            }
            tokens.push_val(anb_make_token(anubis_mk_str("ident".to_string()), AnubisValue::Float(0f64), text.clone(), start.clone()));
            continue;
        }
        if anb_char_in(anubis_mk_str("+-*/%^".to_string()), ch.clone()).as_bool() {
            tokens.push_val(anb_make_token(anubis_mk_str("op".to_string()), AnubisValue::Float(0f64), ch.clone(), i.clone()));
            i = anubis_add(i.clone(), AnubisValue::Int(1));
            continue;
        }
        if anubis_cmp("==", ch.clone(), anubis_mk_str("(".to_string())).as_bool() {
            tokens.push_val(anb_make_token(anubis_mk_str("lparen".to_string()), AnubisValue::Float(0f64), anubis_mk_str("(".to_string()), i.clone()));
            i = anubis_add(i.clone(), AnubisValue::Int(1));
            continue;
        }
        if anubis_cmp("==", ch.clone(), anubis_mk_str(")".to_string())).as_bool() {
            tokens.push_val(anb_make_token(anubis_mk_str("rparen".to_string()), AnubisValue::Float(0f64), anubis_mk_str(")".to_string()), i.clone()));
            i = anubis_add(i.clone(), AnubisValue::Int(1));
            continue;
        }
        if anubis_cmp("==", ch.clone(), anubis_mk_str(",".to_string())).as_bool() {
            tokens.push_val(anb_make_token(anubis_mk_str("comma".to_string()), AnubisValue::Float(0f64), anubis_mk_str(",".to_string()), i.clone()));
            i = anubis_add(i.clone(), AnubisValue::Int(1));
            continue;
        }
        if anubis_cmp("==", ch.clone(), anubis_mk_str("=".to_string())).as_bool() {
            tokens.push_val(anb_make_token(anubis_mk_str("assign".to_string()), AnubisValue::Float(0f64), anubis_mk_str("=".to_string()), i.clone()));
            i = anubis_add(i.clone(), AnubisValue::Int(1));
            continue;
        }
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: unsupported character '".to_string())), ch.clone()), anubis_mk_str("' at offset ".to_string())), i.clone()));
    }
    tokens.push_val(anb_make_token(anubis_mk_str("end".to_string()), AnubisValue::Float(0f64), anubis_mk_str("".to_string()), (source.clone()).len_val()));
    return tokens.clone();
    AnubisValue::Int(0)
}

fn anb_is_constant_name(mut name: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", name.clone(), anubis_mk_str("pi".to_string()))).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("e".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("tau".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("c".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("g0".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("h".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("na".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("kb".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("r".to_string()))).as_bool());
    AnubisValue::Int(0)
}

fn anb_constant_value(mut name: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", name.clone(), anubis_mk_str("pi".to_string())).as_bool() {
        return anubis_pi();
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("e".to_string())).as_bool() {
        return anubis_e();
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("tau".to_string())).as_bool() {
        return anubis_mul(AnubisValue::Float(2f64), anubis_pi());
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("c".to_string())).as_bool() {
        return AnubisValue::Float(299792458f64);
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("g0".to_string())).as_bool() {
        return AnubisValue::Float(9.80665f64);
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("h".to_string())).as_bool() {
        return AnubisValue::Float(0.000000000000000000000000000000000662607015f64);
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("na".to_string())).as_bool() {
        return AnubisValue::Float(602214076000000000000000f64);
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("kb".to_string())).as_bool() {
        return AnubisValue::Float(0.00000000000000000000001380649f64);
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("r".to_string())).as_bool() {
        return AnubisValue::Float(8.31446261815324f64);
    }
    anubis_panic(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("unknown constant: ".to_string())), name.clone()))
}

fn anb_expect_arity_fn(mut name: AnubisValue, mut values: AnubisValue, mut count: AnubisValue, mut at: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("!=", (values.clone()).len_val(), count.clone()).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: ".to_string())), name.clone()), anubis_mk_str(" expects ".to_string())), count.clone()), anubis_mk_str(" argument(s), got ".to_string())), (values.clone()).len_val()), anubis_mk_str(" at offset ".to_string())), at.clone()));
    }
    AnubisValue::Int(0)
}

fn anb_apply_function(mut name: AnubisValue, mut values: AnubisValue, mut at: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", name.clone(), anubis_mk_str("sin".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_sin(values.index_get(AnubisValue::Int(0)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("cos".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_cos(values.index_get(AnubisValue::Int(0)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("tan".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_tan(values.index_get(AnubisValue::Int(0)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("asin".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_asin(values.index_get(AnubisValue::Int(0)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("acos".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_acos(values.index_get(AnubisValue::Int(0)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("atan".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_atan(values.index_get(AnubisValue::Int(0)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("sqrt".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_sqrt(values.index_get(AnubisValue::Int(0)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("cbrt".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_cbrt(values.index_get(AnubisValue::Int(0)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("ln".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_ln(values.index_get(AnubisValue::Int(0)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("log10".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_log10(values.index_get(AnubisValue::Int(0)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("log2".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_log2(values.index_get(AnubisValue::Int(0)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("exp".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_exp(values.index_get(AnubisValue::Int(0)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("abs".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_abs(values.index_get(AnubisValue::Int(0)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("floor".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_add(AnubisValue::Float(0f64), anubis_floor(values.index_get(AnubisValue::Int(0))));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("ceil".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_add(AnubisValue::Float(0f64), anubis_ceil(values.index_get(AnubisValue::Int(0))));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("round".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_add(AnubisValue::Float(0f64), anubis_round(values.index_get(AnubisValue::Int(0))));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("trunc".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(1), at.clone());
        return anubis_add(AnubisValue::Float(0f64), anubis_trunc(values.index_get(AnubisValue::Int(0))));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("hypot".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(2), at.clone());
        return anubis_hypot(values.index_get(AnubisValue::Int(0)), values.index_get(AnubisValue::Int(1)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("pow".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(2), at.clone());
        return anubis_pow(values.index_get(AnubisValue::Int(0)), values.index_get(AnubisValue::Int(1)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("atan2".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(2), at.clone());
        return anubis_atan2(values.index_get(AnubisValue::Int(0)), values.index_get(AnubisValue::Int(1)));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("min".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(2), at.clone());
        return anubis_min(vec![values.index_get(AnubisValue::Int(0)), values.index_get(AnubisValue::Int(1))]);
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("max".to_string())).as_bool() {
        let _ = anb_expect_arity_fn(name.clone(), values.clone(), AnubisValue::Int(2), at.clone());
        return anubis_max(vec![values.index_get(AnubisValue::Int(0)), values.index_get(AnubisValue::Int(1))]);
    }
    anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: unknown function '".to_string())), name.clone()), anubis_mk_str("' at offset ".to_string())), at.clone()))
}

fn anb_map_has_key(mut m: AnubisValue, mut key: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    for mut k in anubis_iter(m.clone()) {
        if anubis_cmp("==", k.clone(), key.clone()).as_bool() {
            return AnubisValue::Bool(true);
        }
    }
    return AnubisValue::Bool(false);
    AnubisValue::Int(0)
}

fn anb_parse_call_args(mut tokens: AnubisValue, mut pos: AnubisValue, mut env: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut values = anubis_mk_list(vec![]);
    let mut cursor = anubis_add(pos.clone(), AnubisValue::Int(1));
    if anubis_cmp("==", (tokens.index_get(cursor.clone())).field_get("kind"), anubis_mk_str("rparen".to_string())).as_bool() {
        return AnubisValue::Struct { ty: "ArgsState".to_string(), fields: vec![("values".to_string(), values.clone()), ("next".to_string(), anubis_field_require_int(anubis_add(cursor.clone(), AnubisValue::Int(1)), "next"))] };
    }
    let mut state = anb_parse_expr(tokens.clone(), cursor.clone(), env.clone());
    values.push_val(state.field_get("value"));
    cursor = state.field_get("next");
    while anubis_cmp("==", (tokens.index_get(cursor.clone())).field_get("kind"), anubis_mk_str("comma".to_string())).as_bool() {
        state = anb_parse_expr(tokens.clone(), anubis_add(cursor.clone(), AnubisValue::Int(1)), env.clone());
        values.push_val(state.field_get("value"));
        cursor = state.field_get("next");
    }
    if anubis_cmp("!=", (tokens.index_get(cursor.clone())).field_get("kind"), anubis_mk_str("rparen".to_string())).as_bool() {
        let mut bad = tokens.index_get(cursor.clone());
        let _ = anubis_panic(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: expected ')' at offset ".to_string())), bad.field_get("at")));
    }
    return AnubisValue::Struct { ty: "ArgsState".to_string(), fields: vec![("values".to_string(), values.clone()), ("next".to_string(), anubis_field_require_int(anubis_add(cursor.clone(), AnubisValue::Int(1)), "next"))] };
    AnubisValue::Int(0)
}

fn anb_parse_atom(mut tokens: AnubisValue, mut pos: AnubisValue, mut env: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut token = tokens.index_get(pos.clone());
    if anubis_cmp("==", token.field_get("kind"), anubis_mk_str("num".to_string())).as_bool() {
        return AnubisValue::Struct { ty: "EvalState".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(token.field_get("num"), "value")), ("next".to_string(), anubis_field_require_int(anubis_add(pos.clone(), AnubisValue::Int(1)), "next"))] };
    }
    if anubis_cmp("==", token.field_get("kind"), anubis_mk_str("lparen".to_string())).as_bool() {
        let mut inner = anb_parse_expr(tokens.clone(), anubis_add(pos.clone(), AnubisValue::Int(1)), env.clone());
        let mut closing = tokens.index_get(inner.field_get("next"));
        if anubis_cmp("!=", closing.field_get("kind"), anubis_mk_str("rparen".to_string())).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: expected ')' at offset ".to_string())), closing.field_get("at")));
        }
        return AnubisValue::Struct { ty: "EvalState".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(inner.field_get("value"), "value")), ("next".to_string(), anubis_field_require_int(anubis_add(inner.field_get("next"), AnubisValue::Int(1)), "next"))] };
    }
    if anubis_cmp("==", token.field_get("kind"), anubis_mk_str("ident".to_string())).as_bool() {
        let mut follower = tokens.index_get(anubis_add(pos.clone(), AnubisValue::Int(1)));
        if anubis_cmp("==", follower.field_get("kind"), anubis_mk_str("lparen".to_string())).as_bool() {
            let mut args = anb_parse_call_args(tokens.clone(), anubis_add(pos.clone(), AnubisValue::Int(1)), env.clone());
            return AnubisValue::Struct { ty: "EvalState".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(anb_apply_function(token.field_get("text"), args.field_get("values"), token.field_get("at")), "value")), ("next".to_string(), anubis_field_require_int(args.field_get("next"), "next"))] };
        }
        if anb_map_has_key(env.clone(), token.field_get("text")).as_bool() {
            return AnubisValue::Struct { ty: "EvalState".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(anubis_get(env.clone(), token.field_get("text"), AnubisValue::Float(0f64)), "value")), ("next".to_string(), anubis_field_require_int(anubis_add(pos.clone(), AnubisValue::Int(1)), "next"))] };
        }
        if anb_is_constant_name(token.field_get("text")).as_bool() {
            return AnubisValue::Struct { ty: "EvalState".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(anb_constant_value(token.field_get("text")), "value")), ("next".to_string(), anubis_field_require_int(anubis_add(pos.clone(), AnubisValue::Int(1)), "next"))] };
        }
        if anubis_cmp("==", token.field_get("text"), anubis_mk_str("x".to_string())).as_bool() {
            let _ = anubis_panic(anubis_mk_str("expression error: variable x is only bound inside integrate/derivative/solve".to_string()));
        }
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: unknown identifier '".to_string())), token.field_get("text")), anubis_mk_str("' at offset ".to_string())), token.field_get("at")));
    }
    if anubis_cmp("==", token.field_get("kind"), anubis_mk_str("end".to_string())).as_bool() {
        let _ = anubis_panic(anubis_mk_str("expression error: unexpected end of expression".to_string()));
    }
    anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: unexpected '".to_string())), token.field_get("text")), anubis_mk_str("' at offset ".to_string())), token.field_get("at")))
}

fn anb_parse_power(mut tokens: AnubisValue, mut pos: AnubisValue, mut env: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut base = anb_parse_atom(tokens.clone(), pos.clone(), env.clone());
    if AnubisValue::Bool((anubis_cmp("==", (tokens.index_get(base.field_get("next"))).field_get("kind"), anubis_mk_str("op".to_string()))).as_bool() && (anubis_cmp("==", (tokens.index_get(base.field_get("next"))).field_get("text"), anubis_mk_str("^".to_string()))).as_bool()).as_bool() {
        let mut exponent = anb_parse_unary(tokens.clone(), anubis_add(base.field_get("next"), AnubisValue::Int(1)), env.clone());
        return AnubisValue::Struct { ty: "EvalState".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(anubis_pow(base.field_get("value"), exponent.field_get("value")), "value")), ("next".to_string(), anubis_field_require_int(exponent.field_get("next"), "next"))] };
    }
    return base.clone();
    AnubisValue::Int(0)
}

fn anb_parse_unary(mut tokens: AnubisValue, mut pos: AnubisValue, mut env: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp("==", (tokens.index_get(pos.clone())).field_get("kind"), anubis_mk_str("op".to_string()))).as_bool() && (anubis_cmp("==", (tokens.index_get(pos.clone())).field_get("text"), anubis_mk_str("-".to_string()))).as_bool()).as_bool() {
        let mut inner = anb_parse_unary(tokens.clone(), anubis_add(pos.clone(), AnubisValue::Int(1)), env.clone());
        return AnubisValue::Struct { ty: "EvalState".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(anubis_neg(inner.field_get("value")), "value")), ("next".to_string(), anubis_field_require_int(inner.field_get("next"), "next"))] };
    }
    return anb_parse_power(tokens.clone(), pos.clone(), env.clone());
    AnubisValue::Int(0)
}

fn anb_parse_term(mut tokens: AnubisValue, mut pos: AnubisValue, mut env: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut state = anb_parse_unary(tokens.clone(), pos.clone(), env.clone());
    while AnubisValue::Bool((anubis_cmp("==", (tokens.index_get(state.field_get("next"))).field_get("kind"), anubis_mk_str("op".to_string()))).as_bool() && (AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", (tokens.index_get(state.field_get("next"))).field_get("text"), anubis_mk_str("*".to_string()))).as_bool() || (anubis_cmp("==", (tokens.index_get(state.field_get("next"))).field_get("text"), anubis_mk_str("/".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", (tokens.index_get(state.field_get("next"))).field_get("text"), anubis_mk_str("%".to_string()))).as_bool())).as_bool()).as_bool() {
        let mut operator = (tokens.index_get(state.field_get("next"))).field_get("text");
        let mut right = anb_parse_unary(tokens.clone(), anubis_add(state.field_get("next"), AnubisValue::Int(1)), env.clone());
        if anubis_cmp("==", operator.clone(), anubis_mk_str("*".to_string())).as_bool() {
            state = AnubisValue::Struct { ty: "EvalState".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(anubis_mul(state.field_get("value"), right.field_get("value")), "value")), ("next".to_string(), anubis_field_require_int(right.field_get("next"), "next"))] };
        } else {
            if anubis_cmp("==", operator.clone(), anubis_mk_str("/".to_string())).as_bool() {
                if anubis_cmp("==", right.field_get("value"), AnubisValue::Float(0f64)).as_bool() {
                    let _ = anubis_panic(anubis_mk_str("expression error: division by zero; fail closed".to_string()));
                }
                state = AnubisValue::Struct { ty: "EvalState".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(anubis_div(state.field_get("value"), right.field_get("value")), "value")), ("next".to_string(), anubis_field_require_int(right.field_get("next"), "next"))] };
            } else {
                if anubis_cmp("==", right.field_get("value"), AnubisValue::Float(0f64)).as_bool() {
                    let _ = anubis_panic(anubis_mk_str("expression error: modulo by zero; fail closed".to_string()));
                }
                state = AnubisValue::Struct { ty: "EvalState".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(anubis_mod(state.field_get("value"), right.field_get("value")), "value")), ("next".to_string(), anubis_field_require_int(right.field_get("next"), "next"))] };
            }
        }
    }
    return state.clone();
    AnubisValue::Int(0)
}

fn anb_parse_expr(mut tokens: AnubisValue, mut pos: AnubisValue, mut env: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut state = anb_parse_term(tokens.clone(), pos.clone(), env.clone());
    while AnubisValue::Bool((anubis_cmp("==", (tokens.index_get(state.field_get("next"))).field_get("kind"), anubis_mk_str("op".to_string()))).as_bool() && (AnubisValue::Bool((anubis_cmp("==", (tokens.index_get(state.field_get("next"))).field_get("text"), anubis_mk_str("+".to_string()))).as_bool() || (anubis_cmp("==", (tokens.index_get(state.field_get("next"))).field_get("text"), anubis_mk_str("-".to_string()))).as_bool())).as_bool()).as_bool() {
        let mut operator = (tokens.index_get(state.field_get("next"))).field_get("text");
        let mut right = anb_parse_term(tokens.clone(), anubis_add(state.field_get("next"), AnubisValue::Int(1)), env.clone());
        if anubis_cmp("==", operator.clone(), anubis_mk_str("+".to_string())).as_bool() {
            state = AnubisValue::Struct { ty: "EvalState".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(anubis_add(state.field_get("value"), right.field_get("value")), "value")), ("next".to_string(), anubis_field_require_int(right.field_get("next"), "next"))] };
        } else {
            state = AnubisValue::Struct { ty: "EvalState".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(anubis_sub(state.field_get("value"), right.field_get("value")), "value")), ("next".to_string(), anubis_field_require_int(right.field_get("next"), "next"))] };
        }
    }
    return state.clone();
    AnubisValue::Int(0)
}

fn anb_require_finite(mut value: AnubisValue, mut source: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("!=", value.clone(), value.clone()).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression produced NaN (IEEE domain violation); fail closed: ".to_string())), source.clone()));
    }
    if AnubisValue::Bool((anubis_cmp(">", value.clone(), AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64))).as_bool() || (anubis_cmp("<", value.clone(), anubis_neg(AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64)))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression produced a non-finite value; fail closed: ".to_string())), source.clone()));
    }
    AnubisValue::Int(0)
}

fn anb_evaluate_expression(mut source: AnubisValue, mut env: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", (source.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("expression error: empty expression".to_string()));
    }
    let mut tokens = anb_tokenize(source.clone());
    let mut state = anb_parse_expr(tokens.clone(), AnubisValue::Int(0), env.clone());
    if anubis_cmp("!=", (tokens.index_get(state.field_get("next"))).field_get("kind"), anubis_mk_str("end".to_string())).as_bool() {
        let mut leftover = tokens.index_get(state.field_get("next"));
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: unexpected '".to_string())), leftover.field_get("text")), anubis_mk_str("' at offset ".to_string())), leftover.field_get("at")));
    }
    let _ = anb_require_finite(state.field_get("value"), source.clone());
    return state.field_get("value");
    AnubisValue::Int(0)
}

fn anb_simpson_general(mut source: AnubisValue, mut start: AnubisValue, mut finish: AnubisValue, mut panels: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp("<=", panels.clone(), AnubisValue::Int(0))).as_bool() || (anubis_cmp("!=", anubis_mod(panels.clone(), AnubisValue::Int(2)), AnubisValue::Int(0))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("Simpson integration requires a positive even panel count".to_string()));
    }
    let mut width = anubis_div(anubis_sub(finish.clone(), start.clone()), panels.clone());
    let mut total = anubis_add(anb_evaluate_expression(source.clone(), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), start.clone())])), anb_evaluate_expression(source.clone(), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), finish.clone())])));
    let mut i = AnubisValue::Int(1);
    while anubis_cmp("<", i.clone(), panels.clone()).as_bool() {
        let mut xv = anubis_add(start.clone(), anubis_mul(i.clone(), width.clone()));
        let mut weight = if (anubis_cmp("==", anubis_mod(i.clone(), AnubisValue::Int(2)), AnubisValue::Int(0))).as_bool() { AnubisValue::Float(2f64) } else { AnubisValue::Float(4f64) };
        total = anubis_add(total.clone(), anubis_mul(weight.clone(), anb_evaluate_expression(source.clone(), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), xv.clone())]))));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return anubis_div(anubis_mul(total.clone(), width.clone()), AnubisValue::Float(3f64));
    AnubisValue::Int(0)
}

fn anb_is_function_name(mut name: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", name.clone(), anubis_mk_str("sin".to_string()))).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("cos".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("tan".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("asin".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("acos".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("atan".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("sqrt".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("cbrt".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("ln".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("log10".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("log2".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("exp".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("abs".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("floor".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("ceil".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("round".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("trunc".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("hypot".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("pow".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("atan2".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("min".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("max".to_string()))).as_bool());
    AnubisValue::Int(0)
}

fn anb_is_reserved_name(mut name: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Bool((anb_is_constant_name(name.clone())).as_bool() || (anb_is_function_name(name.clone())).as_bool());
    AnubisValue::Int(0)
}

fn anb_statement_is_blank(mut statement: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (statement.clone()).len_val()).as_bool() {
        let mut ch = (statement.clone()).index_get(i.clone());
        if AnubisValue::Bool((anubis_cmp("!=", ch.clone(), anubis_mk_str(" ".to_string()))).as_bool() && (anubis_cmp("!=", ch.clone(), anubis_mk_str("\t".to_string()))).as_bool()).as_bool() {
            return AnubisValue::Bool(false);
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return AnubisValue::Bool(true);
    AnubisValue::Int(0)
}

fn anb_run_worksheet(mut source: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut env = anubis_map_lit(vec![]);
    let mut statements = anubis_mk_list(vec![]);
    let mut current = anubis_mk_str("".to_string());
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (source.clone()).len_val()).as_bool() {
        let mut ch = (source.clone()).index_get(i.clone());
        if anubis_cmp("==", ch.clone(), anubis_mk_str(";".to_string())).as_bool() {
            statements.push_val(current.clone());
            current = anubis_mk_str("".to_string());
        } else {
            current = anubis_add(current.clone(), ch.clone());
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    statements.push_val(current.clone());
    let mut evaluated = AnubisValue::Int(0);
    for mut statement in anubis_iter(statements.clone()) {
        if anb_statement_is_blank(statement.clone()).as_bool() {
            continue;
        }
        let mut tokens = anb_tokenize(statement.clone());
        if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp(">=", (tokens.clone()).len_val(), AnubisValue::Int(3))).as_bool() && (anubis_cmp("==", (tokens.index_get(AnubisValue::Int(0))).field_get("kind"), anubis_mk_str("ident".to_string()))).as_bool())).as_bool() && (anubis_cmp("==", (tokens.index_get(AnubisValue::Int(1))).field_get("kind"), anubis_mk_str("assign".to_string()))).as_bool()).as_bool() {
            let mut name = (tokens.index_get(AnubisValue::Int(0))).field_get("text");
            if anb_is_reserved_name(name.clone()).as_bool() {
                let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("worksheet error: cannot assign to reserved name '".to_string())), name.clone()), anubis_mk_str("'".to_string())));
            }
            let mut state = anb_parse_expr(tokens.clone(), AnubisValue::Int(2), env.clone());
            if anubis_cmp("!=", (tokens.index_get(state.field_get("next"))).field_get("kind"), anubis_mk_str("end".to_string())).as_bool() {
                let mut leftover = tokens.index_get(state.field_get("next"));
                let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: unexpected '".to_string())), leftover.field_get("text")), anubis_mk_str("' at offset ".to_string())), leftover.field_get("at")));
            }
            let _ = anb_require_finite(state.field_get("value"), statement.clone());
            env.set_at(&[AnubisPathSeg::Index(name.clone())], state.field_get("value"));
            println!("{}", anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), name.clone()), anubis_mk_str(" = ".to_string())), anb_number_text(state.field_get("value"))).display_string());
        } else {
            let mut state = anb_parse_expr(tokens.clone(), AnubisValue::Int(0), env.clone());
            if anubis_cmp("!=", (tokens.index_get(state.field_get("next"))).field_get("kind"), anubis_mk_str("end".to_string())).as_bool() {
                let mut leftover = tokens.index_get(state.field_get("next"));
                let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: unexpected '".to_string())), leftover.field_get("text")), anubis_mk_str("' at offset ".to_string())), leftover.field_get("at")));
            }
            let _ = anb_require_finite(state.field_get("value"), statement.clone());
            println!("{}", anb_number_text(state.field_get("value")).display_string());
        }
        evaluated = anubis_add(evaluated.clone(), AnubisValue::Int(1));
    }
    if anubis_cmp("==", evaluated.clone(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("worksheet error: no statements".to_string()));
    }
    AnubisValue::Int(0)
}

fn anb_digit_value(mut ch: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut digits = anubis_mk_str("0123456789".to_string());
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), AnubisValue::Int(10)).as_bool() {
        if anubis_cmp("==", (digits.clone()).index_get(i.clone()), ch.clone()).as_bool() {
            return i.clone();
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    anubis_panic(anubis_mk_str("big-integer input must be decimal digits only".to_string()))
}

fn anb_big_normalize(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    while AnubisValue::Bool((anubis_cmp(">", (a.clone()).len_val(), AnubisValue::Int(1))).as_bool() && (anubis_cmp("==", a.index_get(anubis_sub((a.clone()).len_val(), AnubisValue::Int(1))), AnubisValue::Int(0))).as_bool()).as_bool() {
        let _ = anubis_pop(&mut a);
    }
    return a.clone();
    AnubisValue::Int(0)
}

fn anb_big_from_text(mut text: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", (text.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("big-integer input must be decimal digits only".to_string()));
    }
    let mut limbs = anubis_mk_list(vec![]);
    let mut end = (text.clone()).len_val();
    while anubis_cmp(">", end.clone(), AnubisValue::Int(0)).as_bool() {
        let mut start = anubis_sub(end.clone(), AnubisValue::Int(9));
        if anubis_cmp("<", start.clone(), AnubisValue::Int(0)).as_bool() {
            start = AnubisValue::Int(0);
        }
        let mut value = AnubisValue::Int(0);
        let mut j = start.clone();
        while anubis_cmp("<", j.clone(), end.clone()).as_bool() {
            value = anubis_add(anubis_mul(value.clone(), AnubisValue::Int(10)), anb_digit_value((text.clone()).index_get(j.clone())));
            j = anubis_add(j.clone(), AnubisValue::Int(1));
        }
        limbs.push_val(value.clone());
        end = start.clone();
    }
    return anb_big_normalize(limbs.clone());
    AnubisValue::Int(0)
}

fn anb_zero_padded9(mut limb: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut text = anubis_str(limb.clone());
    while anubis_cmp("<", (text.clone()).len_val(), AnubisValue::Int(9)).as_bool() {
        text = anubis_add(anubis_mk_str("0".to_string()), text.clone());
    }
    return text.clone();
    AnubisValue::Int(0)
}

fn anb_big_to_text(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut text = anubis_str(a.index_get(anubis_sub((a.clone()).len_val(), AnubisValue::Int(1))));
    let mut i = anubis_sub((a.clone()).len_val(), AnubisValue::Int(2));
    while anubis_cmp(">=", i.clone(), AnubisValue::Int(0)).as_bool() {
        text = anubis_add(text.clone(), anb_zero_padded9(a.index_get(i.clone())));
        i = anubis_sub(i.clone(), AnubisValue::Int(1));
    }
    return text.clone();
    AnubisValue::Int(0)
}

fn anb_base_low(total: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    fn __anb_body(mut total: AnubisValue) -> AnubisValue {
    anubis_require_int(&total, "total");
    return anubis_mod(total.clone(), AnubisValue::Int(1000000000));
    AnubisValue::Int(0)
    }
    anubis_require_int_ret(__anb_body(total), "base_low")
}

fn anb_base_high(total: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    fn __anb_body(mut total: AnubisValue) -> AnubisValue {
    anubis_require_int(&total, "total");
    return anubis_div(total.clone(), AnubisValue::Int(1000000000));
    AnubisValue::Int(0)
    }
    anubis_require_int_ret(__anb_body(total), "base_high")
}

fn anb_big_add(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut result = anubis_mk_list(vec![]);
    let mut carry = AnubisValue::Int(0);
    let mut i = AnubisValue::Int(0);
    while AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("<", i.clone(), (a.clone()).len_val())).as_bool() || (anubis_cmp("<", i.clone(), (b.clone()).len_val())).as_bool())).as_bool() || (anubis_cmp(">", carry.clone(), AnubisValue::Int(0))).as_bool()).as_bool() {
        let mut total = carry.clone();
        if anubis_cmp("<", i.clone(), (a.clone()).len_val()).as_bool() {
            total = anubis_add(total.clone(), a.index_get(i.clone()));
        }
        if anubis_cmp("<", i.clone(), (b.clone()).len_val()).as_bool() {
            total = anubis_add(total.clone(), b.index_get(i.clone()));
        }
        result.push_val(anb_base_low(total.clone()));
        carry = anb_base_high(total.clone());
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    if anubis_cmp("==", (result.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        result.push_val(AnubisValue::Int(0));
    }
    return result.clone();
    AnubisValue::Int(0)
}

fn anb_big_mul_small(mut a: AnubisValue, mut k: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut result = anubis_mk_list(vec![]);
    let mut carry = AnubisValue::Int(0);
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (a.clone()).len_val()).as_bool() {
        let mut total = anubis_add(anubis_mul(a.index_get(i.clone()), k.clone()), carry.clone());
        result.push_val(anubis_mod(total.clone(), AnubisValue::Int(1000000000)));
        carry = anubis_div(total.clone(), AnubisValue::Int(1000000000));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    while anubis_cmp(">", carry.clone(), AnubisValue::Int(0)).as_bool() {
        result.push_val(anubis_mod(carry.clone(), AnubisValue::Int(1000000000)));
        carry = anubis_div(carry.clone(), AnubisValue::Int(1000000000));
    }
    if anubis_cmp("==", (result.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        result.push_val(AnubisValue::Int(0));
    }
    return anb_big_normalize(result.clone());
    AnubisValue::Int(0)
}

fn anb_big_mul(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut result = anubis_mk_list(vec![]);
    let mut t = AnubisValue::Int(0);
    while anubis_cmp("<", t.clone(), anubis_add((a.clone()).len_val(), (b.clone()).len_val())).as_bool() {
        result.push_val(AnubisValue::Int(0));
        t = anubis_add(t.clone(), AnubisValue::Int(1));
    }
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (a.clone()).len_val()).as_bool() {
        let mut carry = AnubisValue::Int(0);
        let mut j = AnubisValue::Int(0);
        while anubis_cmp("<", j.clone(), (b.clone()).len_val()).as_bool() {
            let mut current = anubis_add(anubis_add(result.index_get(anubis_add(i.clone(), j.clone())), anubis_mul(a.index_get(i.clone()), b.index_get(j.clone()))), carry.clone());
            result.set_at(&[AnubisPathSeg::Index(anubis_add(i.clone(), j.clone()))], anubis_mod(current.clone(), AnubisValue::Int(1000000000)));
            carry = anubis_div(current.clone(), AnubisValue::Int(1000000000));
            j = anubis_add(j.clone(), AnubisValue::Int(1));
        }
        let mut k = anubis_add(i.clone(), (b.clone()).len_val());
        while anubis_cmp(">", carry.clone(), AnubisValue::Int(0)).as_bool() {
            let mut current = anubis_add(result.index_get(k.clone()), carry.clone());
            result.set_at(&[AnubisPathSeg::Index(k.clone())], anubis_mod(current.clone(), AnubisValue::Int(1000000000)));
            carry = anubis_div(current.clone(), AnubisValue::Int(1000000000));
            k = anubis_add(k.clone(), AnubisValue::Int(1));
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return anb_big_normalize(result.clone());
    AnubisValue::Int(0)
}

fn anb_big_divmod_small(mut a: AnubisValue, mut d: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<=", d.clone(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("big-integer division requires a positive small divisor".to_string()));
    }
    let mut quotient = anubis_mk_list(vec![]);
    let mut t = AnubisValue::Int(0);
    while anubis_cmp("<", t.clone(), (a.clone()).len_val()).as_bool() {
        quotient.push_val(AnubisValue::Int(0));
        t = anubis_add(t.clone(), AnubisValue::Int(1));
    }
    let mut remainder = AnubisValue::Int(0);
    let mut i = anubis_sub((a.clone()).len_val(), AnubisValue::Int(1));
    while anubis_cmp(">=", i.clone(), AnubisValue::Int(0)).as_bool() {
        let mut current = anubis_add(anubis_mul(remainder.clone(), AnubisValue::Int(1000000000)), a.index_get(i.clone()));
        quotient.set_at(&[AnubisPathSeg::Index(i.clone())], anubis_div(current.clone(), d.clone()));
        remainder = anubis_mod(current.clone(), d.clone());
        i = anubis_sub(i.clone(), AnubisValue::Int(1));
    }
    return AnubisValue::Struct { ty: "BigDivState".to_string(), fields: vec![("quotient".to_string(), anb_big_normalize(quotient.clone())), ("remainder".to_string(), anubis_field_require_int(remainder.clone(), "remainder"))] };
    AnubisValue::Int(0)
}

fn anb_big_fact(mut n: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp("<", n.clone(), AnubisValue::Int(0))).as_bool() || (anubis_cmp(">", n.clone(), AnubisValue::Int(10000))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("big-fact requires 0 <= n <= 10000 (compute budget); fail closed".to_string()));
    }
    let mut result = anubis_mk_list(vec![AnubisValue::Int(1)]);
    let mut k = AnubisValue::Int(2);
    while anubis_cmp("<=", k.clone(), n.clone()).as_bool() {
        result = anb_big_mul_small(result.clone(), k.clone());
        k = anubis_add(k.clone(), AnubisValue::Int(1));
    }
    return result.clone();
    AnubisValue::Int(0)
}

fn anb_big_ncr(mut n: AnubisValue, mut r: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("<", n.clone(), AnubisValue::Int(0))).as_bool() || (anubis_cmp("<", r.clone(), AnubisValue::Int(0))).as_bool())).as_bool() || (anubis_cmp(">", r.clone(), n.clone())).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("nCr requires 0 <= r <= n".to_string()));
    }
    if anubis_cmp(">", n.clone(), AnubisValue::Int(10000)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("big-ncr requires n <= 10000 (compute budget); fail closed".to_string()));
    }
    let mut k = r.clone();
    if anubis_cmp("<", anubis_sub(n.clone(), r.clone()), k.clone()).as_bool() {
        k = anubis_sub(n.clone(), r.clone());
    }
    let mut result = anubis_mk_list(vec![AnubisValue::Int(1)]);
    let mut i = AnubisValue::Int(1);
    while anubis_cmp("<=", i.clone(), k.clone()).as_bool() {
        result = anb_big_mul_small(result.clone(), anubis_add(anubis_sub(n.clone(), k.clone()), i.clone()));
        let mut division = anb_big_divmod_small(result.clone(), i.clone());
        if anubis_cmp("!=", division.field_get("remainder"), AnubisValue::Int(0)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("internal invariant violated in big-ncr; fail closed".to_string()));
        }
        result = division.field_get("quotient");
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return result.clone();
    AnubisValue::Int(0)
}

fn anb_big_pow(mut base: AnubisValue, mut exponent: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", exponent.clone(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("big-pow requires exponent >= 0".to_string()));
    }
    if anubis_cmp(">", exponent.clone(), AnubisValue::Int(10000)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("big-pow exponent is capped at 10000 (compute budget); fail closed".to_string()));
    }
    let mut result = anubis_mk_list(vec![AnubisValue::Int(1)]);
    let mut e = AnubisValue::Int(0);
    while anubis_cmp("<", e.clone(), exponent.clone()).as_bool() {
        result = anb_big_mul(result.clone(), base.clone());
        e = anubis_add(e.clone(), AnubisValue::Int(1));
    }
    return result.clone();
    AnubisValue::Int(0)
}

fn anb_function_arity(mut name: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", name.clone(), anubis_mk_str("hypot".to_string()))).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("pow".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("atan2".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("min".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("max".to_string()))).as_bool()).as_bool() {
        return AnubisValue::Int(2);
    }
    return AnubisValue::Int(1);
    AnubisValue::Int(0)
}

fn anb_ast_parse_call_args(mut tokens: AnubisValue, mut pos: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut arguments = anubis_mk_list(vec![]);
    let mut cursor = anubis_add(pos.clone(), AnubisValue::Int(1));
    if anubis_cmp("==", (tokens.index_get(cursor.clone())).field_get("kind"), anubis_mk_str("rparen".to_string())).as_bool() {
        return AnubisValue::Struct { ty: "AstState".to_string(), fields: vec![("node".to_string(), arguments.clone()), ("next".to_string(), anubis_field_require_int(anubis_add(cursor.clone(), AnubisValue::Int(1)), "next"))] };
    }
    let mut state = anb_ast_parse_expr(tokens.clone(), cursor.clone());
    arguments.push_val(state.field_get("node"));
    cursor = state.field_get("next");
    while anubis_cmp("==", (tokens.index_get(cursor.clone())).field_get("kind"), anubis_mk_str("comma".to_string())).as_bool() {
        state = anb_ast_parse_expr(tokens.clone(), anubis_add(cursor.clone(), AnubisValue::Int(1)));
        arguments.push_val(state.field_get("node"));
        cursor = state.field_get("next");
    }
    if anubis_cmp("!=", (tokens.index_get(cursor.clone())).field_get("kind"), anubis_mk_str("rparen".to_string())).as_bool() {
        let mut bad = tokens.index_get(cursor.clone());
        let _ = anubis_panic(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: expected ')' at offset ".to_string())), bad.field_get("at")));
    }
    return AnubisValue::Struct { ty: "AstState".to_string(), fields: vec![("node".to_string(), arguments.clone()), ("next".to_string(), anubis_field_require_int(anubis_add(cursor.clone(), AnubisValue::Int(1)), "next"))] };
    AnubisValue::Int(0)
}

fn anb_ast_parse_atom(mut tokens: AnubisValue, mut pos: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut token = tokens.index_get(pos.clone());
    if anubis_cmp("==", token.field_get("kind"), anubis_mk_str("num".to_string())).as_bool() {
        return AnubisValue::Struct { ty: "AstState".to_string(), fields: vec![("node".to_string(), anubis_mk_list(vec![anubis_mk_str("num".to_string()), token.field_get("num"), token.field_get("text")])), ("next".to_string(), anubis_field_require_int(anubis_add(pos.clone(), AnubisValue::Int(1)), "next"))] };
    }
    if anubis_cmp("==", token.field_get("kind"), anubis_mk_str("lparen".to_string())).as_bool() {
        let mut inner = anb_ast_parse_expr(tokens.clone(), anubis_add(pos.clone(), AnubisValue::Int(1)));
        let mut closing = tokens.index_get(inner.field_get("next"));
        if anubis_cmp("!=", closing.field_get("kind"), anubis_mk_str("rparen".to_string())).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: expected ')' at offset ".to_string())), closing.field_get("at")));
        }
        return AnubisValue::Struct { ty: "AstState".to_string(), fields: vec![("node".to_string(), inner.field_get("node")), ("next".to_string(), anubis_field_require_int(anubis_add(inner.field_get("next"), AnubisValue::Int(1)), "next"))] };
    }
    if anubis_cmp("==", token.field_get("kind"), anubis_mk_str("ident".to_string())).as_bool() {
        let mut follower = tokens.index_get(anubis_add(pos.clone(), AnubisValue::Int(1)));
        if anubis_cmp("==", follower.field_get("kind"), anubis_mk_str("lparen".to_string())).as_bool() {
            if AnubisValue::Bool(!(anb_is_function_name(token.field_get("text"))).as_bool()).as_bool() {
                let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: unknown function '".to_string())), token.field_get("text")), anubis_mk_str("' at offset ".to_string())), token.field_get("at")));
            }
            let mut args = anb_ast_parse_call_args(tokens.clone(), anubis_add(pos.clone(), AnubisValue::Int(1)));
            if anubis_cmp("!=", (args.field_get("node")).len_val(), anb_function_arity(token.field_get("text"))).as_bool() {
                let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: ".to_string())), token.field_get("text")), anubis_mk_str(" expects ".to_string())), anb_function_arity(token.field_get("text"))), anubis_mk_str(" argument(s), got ".to_string())), (args.field_get("node")).len_val()), anubis_mk_str(" at offset ".to_string())), token.field_get("at")));
            }
            return AnubisValue::Struct { ty: "AstState".to_string(), fields: vec![("node".to_string(), anubis_mk_list(vec![anubis_mk_str("call".to_string()), token.field_get("text"), args.field_get("node")])), ("next".to_string(), anubis_field_require_int(args.field_get("next"), "next"))] };
        }
        if anb_is_constant_name(token.field_get("text")).as_bool() {
            return AnubisValue::Struct { ty: "AstState".to_string(), fields: vec![("node".to_string(), anubis_mk_list(vec![anubis_mk_str("const".to_string()), token.field_get("text")])), ("next".to_string(), anubis_field_require_int(anubis_add(pos.clone(), AnubisValue::Int(1)), "next"))] };
        }
        return AnubisValue::Struct { ty: "AstState".to_string(), fields: vec![("node".to_string(), anubis_mk_list(vec![anubis_mk_str("var".to_string()), token.field_get("text")])), ("next".to_string(), anubis_field_require_int(anubis_add(pos.clone(), AnubisValue::Int(1)), "next"))] };
    }
    if anubis_cmp("==", token.field_get("kind"), anubis_mk_str("end".to_string())).as_bool() {
        let _ = anubis_panic(anubis_mk_str("expression error: unexpected end of expression".to_string()));
    }
    anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: unexpected '".to_string())), token.field_get("text")), anubis_mk_str("' at offset ".to_string())), token.field_get("at")))
}

fn anb_ast_parse_power(mut tokens: AnubisValue, mut pos: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut base = anb_ast_parse_atom(tokens.clone(), pos.clone());
    if AnubisValue::Bool((anubis_cmp("==", (tokens.index_get(base.field_get("next"))).field_get("kind"), anubis_mk_str("op".to_string()))).as_bool() && (anubis_cmp("==", (tokens.index_get(base.field_get("next"))).field_get("text"), anubis_mk_str("^".to_string()))).as_bool()).as_bool() {
        let mut exponent = anb_ast_parse_unary(tokens.clone(), anubis_add(base.field_get("next"), AnubisValue::Int(1)));
        return AnubisValue::Struct { ty: "AstState".to_string(), fields: vec![("node".to_string(), anubis_mk_list(vec![anubis_mk_str("pow".to_string()), base.field_get("node"), exponent.field_get("node")])), ("next".to_string(), anubis_field_require_int(exponent.field_get("next"), "next"))] };
    }
    return base.clone();
    AnubisValue::Int(0)
}

fn anb_ast_parse_unary(mut tokens: AnubisValue, mut pos: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp("==", (tokens.index_get(pos.clone())).field_get("kind"), anubis_mk_str("op".to_string()))).as_bool() && (anubis_cmp("==", (tokens.index_get(pos.clone())).field_get("text"), anubis_mk_str("-".to_string()))).as_bool()).as_bool() {
        let mut inner = anb_ast_parse_unary(tokens.clone(), anubis_add(pos.clone(), AnubisValue::Int(1)));
        return AnubisValue::Struct { ty: "AstState".to_string(), fields: vec![("node".to_string(), anubis_mk_list(vec![anubis_mk_str("neg".to_string()), inner.field_get("node")])), ("next".to_string(), anubis_field_require_int(inner.field_get("next"), "next"))] };
    }
    return anb_ast_parse_power(tokens.clone(), pos.clone());
    AnubisValue::Int(0)
}

fn anb_ast_parse_term(mut tokens: AnubisValue, mut pos: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut state = anb_ast_parse_unary(tokens.clone(), pos.clone());
    while AnubisValue::Bool((anubis_cmp("==", (tokens.index_get(state.field_get("next"))).field_get("kind"), anubis_mk_str("op".to_string()))).as_bool() && (AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", (tokens.index_get(state.field_get("next"))).field_get("text"), anubis_mk_str("*".to_string()))).as_bool() || (anubis_cmp("==", (tokens.index_get(state.field_get("next"))).field_get("text"), anubis_mk_str("/".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", (tokens.index_get(state.field_get("next"))).field_get("text"), anubis_mk_str("%".to_string()))).as_bool())).as_bool()).as_bool() {
        let mut operator = (tokens.index_get(state.field_get("next"))).field_get("text");
        let mut right = anb_ast_parse_unary(tokens.clone(), anubis_add(state.field_get("next"), AnubisValue::Int(1)));
        let mut tag = anubis_mk_str("mul".to_string());
        if anubis_cmp("==", operator.clone(), anubis_mk_str("/".to_string())).as_bool() {
            tag = anubis_mk_str("div".to_string());
        }
        if anubis_cmp("==", operator.clone(), anubis_mk_str("%".to_string())).as_bool() {
            tag = anubis_mk_str("mod".to_string());
        }
        state = AnubisValue::Struct { ty: "AstState".to_string(), fields: vec![("node".to_string(), anubis_mk_list(vec![tag.clone(), state.field_get("node"), right.field_get("node")])), ("next".to_string(), anubis_field_require_int(right.field_get("next"), "next"))] };
    }
    return state.clone();
    AnubisValue::Int(0)
}

fn anb_ast_parse_expr(mut tokens: AnubisValue, mut pos: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut state = anb_ast_parse_term(tokens.clone(), pos.clone());
    while AnubisValue::Bool((anubis_cmp("==", (tokens.index_get(state.field_get("next"))).field_get("kind"), anubis_mk_str("op".to_string()))).as_bool() && (AnubisValue::Bool((anubis_cmp("==", (tokens.index_get(state.field_get("next"))).field_get("text"), anubis_mk_str("+".to_string()))).as_bool() || (anubis_cmp("==", (tokens.index_get(state.field_get("next"))).field_get("text"), anubis_mk_str("-".to_string()))).as_bool())).as_bool()).as_bool() {
        let mut operator = (tokens.index_get(state.field_get("next"))).field_get("text");
        let mut right = anb_ast_parse_term(tokens.clone(), anubis_add(state.field_get("next"), AnubisValue::Int(1)));
        let mut tag = anubis_mk_str("add".to_string());
        if anubis_cmp("==", operator.clone(), anubis_mk_str("-".to_string())).as_bool() {
            tag = anubis_mk_str("sub".to_string());
        }
        state = AnubisValue::Struct { ty: "AstState".to_string(), fields: vec![("node".to_string(), anubis_mk_list(vec![tag.clone(), state.field_get("node"), right.field_get("node")])), ("next".to_string(), anubis_field_require_int(right.field_get("next"), "next"))] };
    }
    return state.clone();
    AnubisValue::Int(0)
}

fn anb_parse_ast(mut source: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", (source.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("expression error: empty expression".to_string()));
    }
    let mut tokens = anb_tokenize(source.clone());
    let mut state = anb_ast_parse_expr(tokens.clone(), AnubisValue::Int(0));
    if anubis_cmp("!=", (tokens.index_get(state.field_get("next"))).field_get("kind"), anubis_mk_str("end".to_string())).as_bool() {
        let mut leftover = tokens.index_get(state.field_get("next"));
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("expression error: unexpected '".to_string())), leftover.field_get("text")), anubis_mk_str("' at offset ".to_string())), leftover.field_get("at")));
    }
    return state.field_get("node");
    AnubisValue::Int(0)
}

fn anb_eval_ast(mut node: AnubisValue, mut env: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string())).as_bool() {
        return node.index_get(AnubisValue::Int(1));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string())).as_bool() {
        let mut name = node.index_get(AnubisValue::Int(1));
        return anubis_get(env.clone(), name.clone(), anubis_div(AnubisValue::Float(0f64), AnubisValue::Float(0f64)));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string())).as_bool() {
        return anb_constant_value(node.index_get(AnubisValue::Int(1)));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        return anubis_neg(anb_eval_ast(node.index_get(AnubisValue::Int(1)), env.clone()));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("call".to_string())).as_bool() {
        let mut arguments = node.index_get(AnubisValue::Int(2));
        let mut values = anubis_mk_list(vec![]);
        let mut i = AnubisValue::Int(0);
        while anubis_cmp("<", i.clone(), (arguments.clone()).len_val()).as_bool() {
            values.push_val(anb_eval_ast(arguments.index_get(i.clone()), env.clone()));
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        return anb_apply_function(node.index_get(AnubisValue::Int(1)), values.clone(), AnubisValue::Int(0));
    }
    let mut left = anb_eval_ast(node.index_get(AnubisValue::Int(1)), env.clone());
    let mut right = anb_eval_ast(node.index_get(AnubisValue::Int(2)), env.clone());
    if anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string())).as_bool() {
        return anubis_add(left.clone(), right.clone());
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string())).as_bool() {
        return anubis_sub(left.clone(), right.clone());
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string())).as_bool() {
        return anubis_mul(left.clone(), right.clone());
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string())).as_bool() {
        return anubis_div(left.clone(), right.clone());
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mod".to_string())).as_bool() {
        return anubis_mod(left.clone(), right.clone());
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("pow".to_string())).as_bool() {
        return anubis_pow(left.clone(), right.clone());
    }
    anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("internal error: unknown AST node '".to_string())), tag.clone()), anubis_mk_str("'".to_string())))
}

fn anb_collect_vars(mut node: AnubisValue, mut acc: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string())).as_bool() {
        let mut name = node.index_get(AnubisValue::Int(1));
        acc.set_at(&[AnubisPathSeg::Index(name.clone())], AnubisValue::Float(1.5f64));
        return acc.clone();
    }
    if AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string()))).as_bool()).as_bool() {
        return acc.clone();
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        return anb_collect_vars(node.index_get(AnubisValue::Int(1)), acc.clone());
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("call".to_string())).as_bool() {
        let mut arguments = node.index_get(AnubisValue::Int(2));
        let mut i = AnubisValue::Int(0);
        while anubis_cmp("<", i.clone(), (arguments.clone()).len_val()).as_bool() {
            acc = anb_collect_vars(arguments.index_get(i.clone()), acc.clone());
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        return acc.clone();
    }
    acc = anb_collect_vars(node.index_get(AnubisValue::Int(1)), acc.clone());
    return anb_collect_vars(node.index_get(AnubisValue::Int(2)), acc.clone());
    AnubisValue::Int(0)
}

fn anb_ast_prec(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string()))).as_bool()).as_bool() {
        return AnubisValue::Int(1);
    }
    if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("mod".to_string()))).as_bool()).as_bool() {
        return AnubisValue::Int(2);
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        return AnubisValue::Int(3);
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("pow".to_string())).as_bool() {
        return AnubisValue::Int(4);
    }
    return AnubisValue::Int(5);
    AnubisValue::Int(0)
}

fn anb_ast_wrap(mut node: AnubisValue, mut minimum: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut text = anb_ast_to_text(node.clone());
    if anubis_cmp("<", anb_ast_prec(node.clone()), minimum.clone()).as_bool() {
        return anubis_add(anubis_add(anubis_mk_str("(".to_string()), text.clone()), anubis_mk_str(")".to_string()));
    }
    return text.clone();
    AnubisValue::Int(0)
}

fn anb_ast_to_text(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string())).as_bool() {
        let mut text = node.index_get(AnubisValue::Int(2));
        if anubis_cmp(">", (text.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
            return text.clone();
        }
        return anb_number_text(node.index_get(AnubisValue::Int(1)));
    }
    if AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string()))).as_bool()).as_bool() {
        return node.index_get(AnubisValue::Int(1));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        return anubis_add(anubis_mk_str("-".to_string()), anb_ast_wrap(node.index_get(AnubisValue::Int(1)), AnubisValue::Int(4)));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string())).as_bool() {
        return anubis_add(anubis_add(anb_ast_wrap(node.index_get(AnubisValue::Int(1)), AnubisValue::Int(1)), anubis_mk_str("+".to_string())), anb_ast_wrap(node.index_get(AnubisValue::Int(2)), AnubisValue::Int(1)));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string())).as_bool() {
        return anubis_add(anubis_add(anb_ast_wrap(node.index_get(AnubisValue::Int(1)), AnubisValue::Int(1)), anubis_mk_str("-".to_string())), anb_ast_wrap(node.index_get(AnubisValue::Int(2)), AnubisValue::Int(2)));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string())).as_bool() {
        return anubis_add(anubis_add(anb_ast_wrap(node.index_get(AnubisValue::Int(1)), AnubisValue::Int(2)), anubis_mk_str("*".to_string())), anb_ast_wrap(node.index_get(AnubisValue::Int(2)), AnubisValue::Int(3)));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string())).as_bool() {
        return anubis_add(anubis_add(anb_ast_wrap(node.index_get(AnubisValue::Int(1)), AnubisValue::Int(2)), anubis_mk_str("/".to_string())), anb_ast_wrap(node.index_get(AnubisValue::Int(2)), AnubisValue::Int(3)));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mod".to_string())).as_bool() {
        return anubis_add(anubis_add(anb_ast_wrap(node.index_get(AnubisValue::Int(1)), AnubisValue::Int(2)), anubis_mk_str("%".to_string())), anb_ast_wrap(node.index_get(AnubisValue::Int(2)), AnubisValue::Int(3)));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("pow".to_string())).as_bool() {
        return anubis_add(anubis_add(anb_ast_wrap(node.index_get(AnubisValue::Int(1)), AnubisValue::Int(5)), anubis_mk_str("^".to_string())), anb_ast_wrap(node.index_get(AnubisValue::Int(2)), AnubisValue::Int(3)));
    }
    let mut arguments = node.index_get(AnubisValue::Int(2));
    let mut text = anubis_add(node.index_get(AnubisValue::Int(1)), anubis_mk_str("(".to_string()));
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (arguments.clone()).len_val()).as_bool() {
        if anubis_cmp(">", i.clone(), AnubisValue::Int(0)).as_bool() {
            text = anubis_add(text.clone(), anubis_mk_str(",".to_string()));
        }
        text = anubis_add(text.clone(), anb_ast_to_text(arguments.index_get(i.clone())));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return anubis_add(text.clone(), anubis_mk_str(")".to_string()));
    AnubisValue::Int(0)
}

fn anb_ast_equal(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("!=", a.index_get(AnubisValue::Int(0)), b.index_get(AnubisValue::Int(0))).as_bool() {
        return AnubisValue::Bool(false);
    }
    let mut tag = a.index_get(AnubisValue::Int(0));
    if anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string())).as_bool() {
        return anubis_cmp("==", a.index_get(AnubisValue::Int(1)), b.index_get(AnubisValue::Int(1)));
    }
    if AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string()))).as_bool()).as_bool() {
        return anubis_cmp("==", a.index_get(AnubisValue::Int(1)), b.index_get(AnubisValue::Int(1)));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        return anb_ast_equal(a.index_get(AnubisValue::Int(1)), b.index_get(AnubisValue::Int(1)));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("call".to_string())).as_bool() {
        if anubis_cmp("!=", a.index_get(AnubisValue::Int(1)), b.index_get(AnubisValue::Int(1))).as_bool() {
            return AnubisValue::Bool(false);
        }
        let mut left_args = a.index_get(AnubisValue::Int(2));
        let mut right_args = b.index_get(AnubisValue::Int(2));
        if anubis_cmp("!=", (left_args.clone()).len_val(), (right_args.clone()).len_val()).as_bool() {
            return AnubisValue::Bool(false);
        }
        let mut i = AnubisValue::Int(0);
        while anubis_cmp("<", i.clone(), (left_args.clone()).len_val()).as_bool() {
            if AnubisValue::Bool(!(anb_ast_equal(left_args.index_get(i.clone()), right_args.index_get(i.clone()))).as_bool()).as_bool() {
                return AnubisValue::Bool(false);
            }
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        return AnubisValue::Bool(true);
    }
    return AnubisValue::Bool((anb_ast_equal(a.index_get(AnubisValue::Int(1)), b.index_get(AnubisValue::Int(1)))).as_bool() && (anb_ast_equal(a.index_get(AnubisValue::Int(2)), b.index_get(AnubisValue::Int(2)))).as_bool());
    AnubisValue::Int(0)
}

fn anb_mk_num(mut value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_mk_list(vec![anubis_mk_str("num".to_string()), value.clone(), anubis_mk_str("".to_string())]);
    AnubisValue::Int(0)
}

fn anb_mk_signed_num(mut value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", value.clone(), AnubisValue::Float(0f64)).as_bool() {
        return anubis_mk_list(vec![anubis_mk_str("neg".to_string()), anubis_mk_list(vec![anubis_mk_str("num".to_string()), anubis_neg(value.clone()), anubis_mk_str("".to_string())])]);
    }
    return anubis_mk_list(vec![anubis_mk_str("num".to_string()), value.clone(), anubis_mk_str("".to_string())]);
    AnubisValue::Int(0)
}

fn anb_ast_is_num(mut node: AnubisValue, mut value: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Bool((anubis_cmp("==", node.index_get(AnubisValue::Int(0)), anubis_mk_str("num".to_string()))).as_bool() && (anubis_cmp("==", node.index_get(AnubisValue::Int(1)), value.clone())).as_bool());
    AnubisValue::Int(0)
}

fn anb_simplify(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string()))).as_bool()).as_bool() {
        return node.clone();
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        let mut child = anb_simplify(node.index_get(AnubisValue::Int(1)));
        if anubis_cmp("==", child.index_get(AnubisValue::Int(0)), anubis_mk_str("num".to_string())).as_bool() {
            return anb_mk_signed_num(anubis_neg(child.index_get(AnubisValue::Int(1))));
        }
        if anubis_cmp("==", child.index_get(AnubisValue::Int(0)), anubis_mk_str("neg".to_string())).as_bool() {
            return child.index_get(AnubisValue::Int(1));
        }
        return anubis_mk_list(vec![anubis_mk_str("neg".to_string()), child.clone()]);
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("call".to_string())).as_bool() {
        let mut arguments = node.index_get(AnubisValue::Int(2));
        let mut out = anubis_mk_list(vec![]);
        let mut i = AnubisValue::Int(0);
        while anubis_cmp("<", i.clone(), (arguments.clone()).len_val()).as_bool() {
            out.push_val(anb_simplify(arguments.index_get(i.clone())));
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        return anubis_mk_list(vec![anubis_mk_str("call".to_string()), node.index_get(AnubisValue::Int(1)), out.clone()]);
    }
    let mut left = anb_simplify(node.index_get(AnubisValue::Int(1)));
    let mut right = anb_simplify(node.index_get(AnubisValue::Int(2)));
    if AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("mod".to_string()))).as_bool())).as_bool() && (anubis_cmp("==", right.index_get(AnubisValue::Int(0)), anubis_mk_str("num".to_string()))).as_bool())).as_bool() && (anubis_cmp("==", right.index_get(AnubisValue::Int(1)), AnubisValue::Float(0f64))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("d/dx: literal division by zero is undefined; fail closed (consistent with eval and rat)".to_string()));
    }
    if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", left.index_get(AnubisValue::Int(0)), anubis_mk_str("num".to_string()))).as_bool() && (anubis_cmp("==", right.index_get(AnubisValue::Int(0)), anubis_mk_str("num".to_string()))).as_bool())).as_bool() && (anubis_cmp("!=", tag.clone(), anubis_mk_str("mod".to_string()))).as_bool()).as_bool() {
        let mut folded = AnubisValue::Float(0f64);
        let mut can_fold = AnubisValue::Bool(true);
        if anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string())).as_bool() {
            folded = anubis_add(left.index_get(AnubisValue::Int(1)), right.index_get(AnubisValue::Int(1)));
        } else {
            if anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string())).as_bool() {
                folded = anubis_sub(left.index_get(AnubisValue::Int(1)), right.index_get(AnubisValue::Int(1)));
            } else {
                if anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string())).as_bool() {
                    folded = anubis_mul(left.index_get(AnubisValue::Int(1)), right.index_get(AnubisValue::Int(1)));
                } else {
                    if anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string())).as_bool() {
                        if anubis_cmp("==", right.index_get(AnubisValue::Int(1)), AnubisValue::Float(0f64)).as_bool() {
                            can_fold = AnubisValue::Bool(false);
                        } else {
                            folded = anubis_div(left.index_get(AnubisValue::Int(1)), right.index_get(AnubisValue::Int(1)));
                        }
                    } else {
                        folded = anubis_pow(left.index_get(AnubisValue::Int(1)), right.index_get(AnubisValue::Int(1)));
                    }
                }
            }
        }
        if AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((can_fold.clone()).as_bool() && (anubis_cmp("==", folded.clone(), folded.clone())).as_bool())).as_bool() && (anubis_cmp("<=", folded.clone(), AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64))).as_bool())).as_bool() && (anubis_cmp(">=", folded.clone(), anubis_neg(AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64)))).as_bool()).as_bool() {
            return anb_mk_signed_num(folded.clone());
        }
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string())).as_bool() {
        if anb_ast_is_num(left.clone(), AnubisValue::Float(0f64)).as_bool() {
            return right.clone();
        }
        if anb_ast_is_num(right.clone(), AnubisValue::Float(0f64)).as_bool() {
            return left.clone();
        }
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string())).as_bool() {
        if anb_ast_is_num(right.clone(), AnubisValue::Float(0f64)).as_bool() {
            return left.clone();
        }
        if anb_ast_is_num(left.clone(), AnubisValue::Float(0f64)).as_bool() {
            return anb_simplify(anubis_mk_list(vec![anubis_mk_str("neg".to_string()), right.clone()]));
        }
        if anb_ast_equal(left.clone(), right.clone()).as_bool() {
            return anb_mk_num(AnubisValue::Float(0f64));
        }
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string())).as_bool() {
        if AnubisValue::Bool((anb_ast_is_num(left.clone(), AnubisValue::Float(0f64))).as_bool() || (anb_ast_is_num(right.clone(), AnubisValue::Float(0f64))).as_bool()).as_bool() {
            return anb_mk_num(AnubisValue::Float(0f64));
        }
        if anb_ast_is_num(left.clone(), AnubisValue::Float(1f64)).as_bool() {
            return right.clone();
        }
        if anb_ast_is_num(right.clone(), AnubisValue::Float(1f64)).as_bool() {
            return left.clone();
        }
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string())).as_bool() {
        if anb_ast_is_num(right.clone(), AnubisValue::Float(1f64)).as_bool() {
            return left.clone();
        }
        if anb_ast_is_num(left.clone(), AnubisValue::Float(0f64)).as_bool() {
            return anb_mk_num(AnubisValue::Float(0f64));
        }
        if anb_ast_equal(left.clone(), right.clone()).as_bool() {
            return anb_mk_num(AnubisValue::Float(1f64));
        }
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("pow".to_string())).as_bool() {
        if anb_ast_is_num(right.clone(), AnubisValue::Float(1f64)).as_bool() {
            return left.clone();
        }
        if anb_ast_is_num(right.clone(), AnubisValue::Float(0f64)).as_bool() {
            return anb_mk_num(AnubisValue::Float(1f64));
        }
        if anb_ast_is_num(left.clone(), AnubisValue::Float(1f64)).as_bool() {
            return anb_mk_num(AnubisValue::Float(1f64));
        }
    }
    return anubis_mk_list(vec![tag.clone(), left.clone(), right.clone()]);
    AnubisValue::Int(0)
}

fn anb_has_where_defined_convention(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string()))).as_bool()).as_bool() {
        return AnubisValue::Bool(false);
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        return anb_has_where_defined_convention(node.index_get(AnubisValue::Int(1)));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("call".to_string())).as_bool() {
        let mut arguments = node.index_get(AnubisValue::Int(2));
        let mut i = AnubisValue::Int(0);
        while anubis_cmp("<", i.clone(), (arguments.clone()).len_val()).as_bool() {
            if anb_has_where_defined_convention(arguments.index_get(i.clone())).as_bool() {
                return AnubisValue::Bool(true);
            }
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        return AnubisValue::Bool(false);
    }
    if AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string()))).as_bool() && (anb_ast_equal(node.index_get(AnubisValue::Int(1)), node.index_get(AnubisValue::Int(2)))).as_bool()).as_bool() {
        return AnubisValue::Bool(true);
    }
    if AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string()))).as_bool() && (anb_ast_equal(node.index_get(AnubisValue::Int(1)), node.index_get(AnubisValue::Int(2)))).as_bool()).as_bool() {
        return AnubisValue::Bool(true);
    }
    if AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("pow".to_string()))).as_bool() && (anb_ast_is_num(node.index_get(AnubisValue::Int(2)), AnubisValue::Float(0f64))).as_bool()).as_bool() {
        return AnubisValue::Bool(true);
    }
    if AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string()))).as_bool() && (AnubisValue::Bool((anb_ast_is_num(node.index_get(AnubisValue::Int(1)), AnubisValue::Float(0f64))).as_bool() || (anb_ast_is_num(node.index_get(AnubisValue::Int(2)), AnubisValue::Float(0f64))).as_bool())).as_bool()).as_bool() {
        return AnubisValue::Bool(true);
    }
    if anb_has_where_defined_convention(node.index_get(AnubisValue::Int(1))).as_bool() {
        return AnubisValue::Bool(true);
    }
    return anb_has_where_defined_convention(node.index_get(AnubisValue::Int(2)));
    AnubisValue::Int(0)
}

fn anb_simplify_bound(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string()))).as_bool()).as_bool() {
        return node.clone();
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        let mut child = anb_simplify_bound(node.index_get(AnubisValue::Int(1)));
        if anubis_cmp("==", child.index_get(AnubisValue::Int(0)), anubis_mk_str("neg".to_string())).as_bool() {
            return child.index_get(AnubisValue::Int(1));
        }
        return anubis_mk_list(vec![anubis_mk_str("neg".to_string()), child.clone()]);
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("call".to_string())).as_bool() {
        let mut arguments = node.index_get(AnubisValue::Int(2));
        let mut out = anubis_mk_list(vec![]);
        let mut i = AnubisValue::Int(0);
        while anubis_cmp("<", i.clone(), (arguments.clone()).len_val()).as_bool() {
            out.push_val(anb_simplify_bound(arguments.index_get(i.clone())));
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        return anubis_mk_list(vec![anubis_mk_str("call".to_string()), node.index_get(AnubisValue::Int(1)), out.clone()]);
    }
    let mut left = anb_simplify_bound(node.index_get(AnubisValue::Int(1)));
    let mut right = anb_simplify_bound(node.index_get(AnubisValue::Int(2)));
    if AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("mod".to_string()))).as_bool())).as_bool() && (anubis_cmp("==", right.index_get(AnubisValue::Int(0)), anubis_mk_str("num".to_string()))).as_bool())).as_bool() && (anubis_cmp("==", right.index_get(AnubisValue::Int(1)), AnubisValue::Float(0f64))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("d/dx: literal division by zero is undefined; fail closed (consistent with eval and rat)".to_string()));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string())).as_bool() {
        if anb_ast_is_num(left.clone(), AnubisValue::Float(0f64)).as_bool() {
            return right.clone();
        }
        if anb_ast_is_num(right.clone(), AnubisValue::Float(0f64)).as_bool() {
            return left.clone();
        }
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string())).as_bool() {
        if anb_ast_is_num(right.clone(), AnubisValue::Float(0f64)).as_bool() {
            return left.clone();
        }
        if anb_ast_is_num(left.clone(), AnubisValue::Float(0f64)).as_bool() {
            return anb_simplify_bound(anubis_mk_list(vec![anubis_mk_str("neg".to_string()), right.clone()]));
        }
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string())).as_bool() {
        if anb_ast_is_num(left.clone(), AnubisValue::Float(1f64)).as_bool() {
            return right.clone();
        }
        if anb_ast_is_num(right.clone(), AnubisValue::Float(1f64)).as_bool() {
            return left.clone();
        }
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string())).as_bool() {
        if anb_ast_is_num(right.clone(), AnubisValue::Float(1f64)).as_bool() {
            return left.clone();
        }
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("pow".to_string())).as_bool() {
        if anb_ast_is_num(right.clone(), AnubisValue::Float(1f64)).as_bool() {
            return left.clone();
        }
    }
    return anubis_mk_list(vec![tag.clone(), left.clone(), right.clone()]);
    AnubisValue::Int(0)
}

fn anb_ast_sexp(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string())).as_bool() {
        return anubis_add(anubis_add(anubis_mk_str("(num ".to_string()), node.index_get(AnubisValue::Int(2))), anubis_mk_str(")".to_string()));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string())).as_bool() {
        return anubis_add(anubis_add(anubis_mk_str("(var ".to_string()), node.index_get(AnubisValue::Int(1))), anubis_mk_str(")".to_string()));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string())).as_bool() {
        return anubis_add(anubis_add(anubis_mk_str("(const ".to_string()), node.index_get(AnubisValue::Int(1))), anubis_mk_str(")".to_string()));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        let mut inner = anb_ast_sexp(node.index_get(AnubisValue::Int(1)));
        return anubis_add(anubis_add(anubis_mk_str("(neg ".to_string()), inner.clone()), anubis_mk_str(")".to_string()));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("call".to_string())).as_bool() {
        let mut arguments = node.index_get(AnubisValue::Int(2));
        let mut text = anubis_add(anubis_mk_str("(call ".to_string()), node.index_get(AnubisValue::Int(1)));
        let mut i = AnubisValue::Int(0);
        while anubis_cmp("<", i.clone(), (arguments.clone()).len_val()).as_bool() {
            let mut piece = anb_ast_sexp(arguments.index_get(i.clone()));
            text = anubis_add(anubis_add(text.clone(), anubis_mk_str(" ".to_string())), piece.clone());
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        return anubis_add(text.clone(), anubis_mk_str(")".to_string()));
    }
    let mut left = anb_ast_sexp(node.index_get(AnubisValue::Int(1)));
    let mut right = anb_ast_sexp(node.index_get(AnubisValue::Int(2)));
    return anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("(".to_string()), tag.clone()), anubis_mk_str(" ".to_string())), left.clone()), anubis_mk_str(" ".to_string())), right.clone()), anubis_mk_str(")".to_string()));
    AnubisValue::Int(0)
}

fn anb_ast_smooth_ok(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string()))).as_bool()).as_bool() {
        return AnubisValue::Bool(true);
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        return anb_ast_smooth_ok(node.index_get(AnubisValue::Int(1)));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mod".to_string())).as_bool() {
        return AnubisValue::Bool(false);
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("call".to_string())).as_bool() {
        let mut name = node.index_get(AnubisValue::Int(1));
        if AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", name.clone(), anubis_mk_str("abs".to_string()))).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("floor".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("ceil".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("round".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("trunc".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("min".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("max".to_string()))).as_bool()).as_bool() {
            return AnubisValue::Bool(false);
        }
        let mut arguments = node.index_get(AnubisValue::Int(2));
        let mut i = AnubisValue::Int(0);
        while anubis_cmp("<", i.clone(), (arguments.clone()).len_val()).as_bool() {
            if AnubisValue::Bool(!(anb_ast_smooth_ok(arguments.index_get(i.clone()))).as_bool()).as_bool() {
                return AnubisValue::Bool(false);
            }
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        return AnubisValue::Bool(true);
    }
    if AnubisValue::Bool(!(anb_ast_smooth_ok(node.index_get(AnubisValue::Int(1)))).as_bool()).as_bool() {
        return AnubisValue::Bool(false);
    }
    return anb_ast_smooth_ok(node.index_get(AnubisValue::Int(2)));
    AnubisValue::Int(0)
}

fn anb_ast_const_value_or_nan(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", node.index_get(AnubisValue::Int(0)), anubis_mk_str("num".to_string())).as_bool() {
        return node.index_get(AnubisValue::Int(1));
    }
    if anubis_cmp("==", node.index_get(AnubisValue::Int(0)), anubis_mk_str("const".to_string())).as_bool() {
        return anb_constant_value(node.index_get(AnubisValue::Int(1)));
    }
    if anubis_cmp("==", node.index_get(AnubisValue::Int(0)), anubis_mk_str("neg".to_string())).as_bool() {
        return anubis_neg(anb_ast_const_value_or_nan(node.index_get(AnubisValue::Int(1))));
    }
    return anubis_div(AnubisValue::Float(0f64), AnubisValue::Float(0f64));
    AnubisValue::Int(0)
}

fn anb_deriv(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    let mut target = node.clone();
    if AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("call".to_string()))).as_bool() && (anubis_cmp("==", node.index_get(AnubisValue::Int(1)), anubis_mk_str("pow".to_string()))).as_bool()).as_bool() {
        let mut normalized = node.index_get(AnubisValue::Int(2));
        target = anubis_mk_list(vec![anubis_mk_str("pow".to_string()), normalized.index_get(AnubisValue::Int(0)), normalized.index_get(AnubisValue::Int(1))]);
        tag = anubis_mk_str("pow".to_string());
    }
    if AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string()))).as_bool()).as_bool() {
        return anb_mk_num(AnubisValue::Float(0f64));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string())).as_bool() {
        if anubis_cmp("==", target.index_get(AnubisValue::Int(1)), anubis_mk_str("x".to_string())).as_bool() {
            return anb_mk_num(AnubisValue::Float(1f64));
        }
        return anb_mk_num(AnubisValue::Float(0f64));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        let mut du = anb_deriv(target.index_get(AnubisValue::Int(1)));
        return anubis_mk_list(vec![anubis_mk_str("neg".to_string()), du.clone()]);
    }
    if AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string()))).as_bool()).as_bool() {
        let mut du = anb_deriv(target.index_get(AnubisValue::Int(1)));
        let mut dv = anb_deriv(target.index_get(AnubisValue::Int(2)));
        return anubis_mk_list(vec![tag.clone(), du.clone(), dv.clone()]);
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string())).as_bool() {
        let mut u = target.index_get(AnubisValue::Int(1));
        let mut v = target.index_get(AnubisValue::Int(2));
        let mut du = anb_deriv(u.clone());
        let mut dv = anb_deriv(v.clone());
        let mut left = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), du.clone(), v.clone()]);
        let mut right = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), u.clone(), dv.clone()]);
        return anubis_mk_list(vec![anubis_mk_str("add".to_string()), left.clone(), right.clone()]);
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string())).as_bool() {
        let mut u = target.index_get(AnubisValue::Int(1));
        let mut v = target.index_get(AnubisValue::Int(2));
        let mut du = anb_deriv(u.clone());
        let mut dv = anb_deriv(v.clone());
        let mut left = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), du.clone(), v.clone()]);
        let mut right = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), u.clone(), dv.clone()]);
        let mut numerator = anubis_mk_list(vec![anubis_mk_str("sub".to_string()), left.clone(), right.clone()]);
        let mut denominator = anubis_mk_list(vec![anubis_mk_str("pow".to_string()), v.clone(), anb_mk_num(AnubisValue::Float(2f64))]);
        return anubis_mk_list(vec![anubis_mk_str("div".to_string()), numerator.clone(), denominator.clone()]);
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mod".to_string())).as_bool() {
        let _ = anubis_panic(anubis_mk_str("d/dx: '%' is discontinuous and not differentiable; fail closed".to_string()));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("pow".to_string())).as_bool() {
        let mut base = target.index_get(AnubisValue::Int(1));
        let mut exponent = target.index_get(AnubisValue::Int(2));
        let mut du = anb_deriv(base.clone());
        let mut c = anb_ast_const_value_or_nan(exponent.clone());
        if anubis_cmp("==", c.clone(), c.clone()).as_bool() {
            let mut coefficient = anb_mk_signed_num(c.clone());
            let mut reduced = anb_mk_signed_num(anubis_sub(c.clone(), AnubisValue::Float(1f64)));
            let mut power = anubis_mk_list(vec![anubis_mk_str("pow".to_string()), base.clone(), reduced.clone()]);
            let mut scaled = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), coefficient.clone(), power.clone()]);
            return anubis_mk_list(vec![anubis_mk_str("mul".to_string()), scaled.clone(), du.clone()]);
        }
        let mut dv = anb_deriv(exponent.clone());
        let mut original = anubis_mk_list(vec![anubis_mk_str("pow".to_string()), base.clone(), exponent.clone()]);
        let mut log_base = anubis_mk_list(vec![anubis_mk_str("call".to_string()), anubis_mk_str("ln".to_string()), anubis_mk_list(vec![base.clone()])]);
        let mut log_part = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), dv.clone(), log_base.clone()]);
        let mut ratio_top = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), exponent.clone(), du.clone()]);
        let mut ratio = anubis_mk_list(vec![anubis_mk_str("div".to_string()), ratio_top.clone(), base.clone()]);
        let mut bracket = anubis_mk_list(vec![anubis_mk_str("add".to_string()), log_part.clone(), ratio.clone()]);
        return anubis_mk_list(vec![anubis_mk_str("mul".to_string()), original.clone(), bracket.clone()]);
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("call".to_string())).as_bool() {
        let mut name = target.index_get(AnubisValue::Int(1));
        let mut arguments = target.index_get(AnubisValue::Int(2));
        if anubis_cmp("==", name.clone(), anubis_mk_str("hypot".to_string())).as_bool() {
            let mut u = arguments.index_get(AnubisValue::Int(0));
            let mut v = arguments.index_get(AnubisValue::Int(1));
            let mut du = anb_deriv(u.clone());
            let mut dv = anb_deriv(v.clone());
            let mut left = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), u.clone(), du.clone()]);
            let mut right = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), v.clone(), dv.clone()]);
            let mut numerator = anubis_mk_list(vec![anubis_mk_str("add".to_string()), left.clone(), right.clone()]);
            let mut denominator = anubis_mk_list(vec![anubis_mk_str("call".to_string()), anubis_mk_str("hypot".to_string()), anubis_mk_list(vec![u.clone(), v.clone()])]);
            return anubis_mk_list(vec![anubis_mk_str("div".to_string()), numerator.clone(), denominator.clone()]);
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("atan2".to_string())).as_bool() {
            let mut u = arguments.index_get(AnubisValue::Int(0));
            let mut v = arguments.index_get(AnubisValue::Int(1));
            let mut du = anb_deriv(u.clone());
            let mut dv = anb_deriv(v.clone());
            let mut left = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), v.clone(), du.clone()]);
            let mut right = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), u.clone(), dv.clone()]);
            let mut numerator = anubis_mk_list(vec![anubis_mk_str("sub".to_string()), left.clone(), right.clone()]);
            let mut u2 = anubis_mk_list(vec![anubis_mk_str("pow".to_string()), u.clone(), anb_mk_num(AnubisValue::Float(2f64))]);
            let mut v2 = anubis_mk_list(vec![anubis_mk_str("pow".to_string()), v.clone(), anb_mk_num(AnubisValue::Float(2f64))]);
            let mut denominator = anubis_mk_list(vec![anubis_mk_str("add".to_string()), u2.clone(), v2.clone()]);
            return anubis_mk_list(vec![anubis_mk_str("div".to_string()), numerator.clone(), denominator.clone()]);
        }
        if AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", name.clone(), anubis_mk_str("abs".to_string()))).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("floor".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("ceil".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("round".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("trunc".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("min".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("max".to_string()))).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("d/dx: ".to_string())), name.clone()), anubis_mk_str(" is not differentiable everywhere; fail closed rather than guess".to_string())));
        }
        let mut u = arguments.index_get(AnubisValue::Int(0));
        let mut du = anb_deriv(u.clone());
        if anubis_cmp("==", name.clone(), anubis_mk_str("sin".to_string())).as_bool() {
            let mut outer = anubis_mk_list(vec![anubis_mk_str("call".to_string()), anubis_mk_str("cos".to_string()), anubis_mk_list(vec![u.clone()])]);
            return anubis_mk_list(vec![anubis_mk_str("mul".to_string()), outer.clone(), du.clone()]);
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("cos".to_string())).as_bool() {
            let mut outer = anubis_mk_list(vec![anubis_mk_str("call".to_string()), anubis_mk_str("sin".to_string()), anubis_mk_list(vec![u.clone()])]);
            let mut product = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), outer.clone(), du.clone()]);
            return anubis_mk_list(vec![anubis_mk_str("neg".to_string()), product.clone()]);
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("tan".to_string())).as_bool() {
            let mut outer = anubis_mk_list(vec![anubis_mk_str("call".to_string()), anubis_mk_str("cos".to_string()), anubis_mk_list(vec![u.clone()])]);
            let mut denominator = anubis_mk_list(vec![anubis_mk_str("pow".to_string()), outer.clone(), anb_mk_num(AnubisValue::Float(2f64))]);
            return anubis_mk_list(vec![anubis_mk_str("div".to_string()), du.clone(), denominator.clone()]);
        }
        if AnubisValue::Bool((anubis_cmp("==", name.clone(), anubis_mk_str("asin".to_string()))).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("acos".to_string()))).as_bool()).as_bool() {
            let mut u2 = anubis_mk_list(vec![anubis_mk_str("pow".to_string()), u.clone(), anb_mk_num(AnubisValue::Float(2f64))]);
            let mut inside = anubis_mk_list(vec![anubis_mk_str("sub".to_string()), anb_mk_num(AnubisValue::Float(1f64)), u2.clone()]);
            let mut root = anubis_mk_list(vec![anubis_mk_str("call".to_string()), anubis_mk_str("sqrt".to_string()), anubis_mk_list(vec![inside.clone()])]);
            let mut ratio = anubis_mk_list(vec![anubis_mk_str("div".to_string()), du.clone(), root.clone()]);
            if anubis_cmp("==", name.clone(), anubis_mk_str("asin".to_string())).as_bool() {
                return ratio.clone();
            }
            return anubis_mk_list(vec![anubis_mk_str("neg".to_string()), ratio.clone()]);
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("atan".to_string())).as_bool() {
            let mut u2 = anubis_mk_list(vec![anubis_mk_str("pow".to_string()), u.clone(), anb_mk_num(AnubisValue::Float(2f64))]);
            let mut denominator = anubis_mk_list(vec![anubis_mk_str("add".to_string()), anb_mk_num(AnubisValue::Float(1f64)), u2.clone()]);
            return anubis_mk_list(vec![anubis_mk_str("div".to_string()), du.clone(), denominator.clone()]);
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("sqrt".to_string())).as_bool() {
            let mut root = anubis_mk_list(vec![anubis_mk_str("call".to_string()), anubis_mk_str("sqrt".to_string()), anubis_mk_list(vec![u.clone()])]);
            let mut denominator = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), anb_mk_num(AnubisValue::Float(2f64)), root.clone()]);
            return anubis_mk_list(vec![anubis_mk_str("div".to_string()), du.clone(), denominator.clone()]);
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("cbrt".to_string())).as_bool() {
            let mut root = anubis_mk_list(vec![anubis_mk_str("call".to_string()), anubis_mk_str("cbrt".to_string()), anubis_mk_list(vec![u.clone()])]);
            let mut squared = anubis_mk_list(vec![anubis_mk_str("pow".to_string()), root.clone(), anb_mk_num(AnubisValue::Float(2f64))]);
            let mut denominator = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), anb_mk_num(AnubisValue::Float(3f64)), squared.clone()]);
            return anubis_mk_list(vec![anubis_mk_str("div".to_string()), du.clone(), denominator.clone()]);
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("ln".to_string())).as_bool() {
            return anubis_mk_list(vec![anubis_mk_str("div".to_string()), du.clone(), u.clone()]);
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("log10".to_string())).as_bool() {
            let mut denominator = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), u.clone(), anb_mk_num(AnubisValue::Float(2.302585092994046f64))]);
            return anubis_mk_list(vec![anubis_mk_str("div".to_string()), du.clone(), denominator.clone()]);
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("log2".to_string())).as_bool() {
            let mut denominator = anubis_mk_list(vec![anubis_mk_str("mul".to_string()), u.clone(), anb_mk_num(AnubisValue::Float(0.6931471805599453f64))]);
            return anubis_mk_list(vec![anubis_mk_str("div".to_string()), du.clone(), denominator.clone()]);
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("exp".to_string())).as_bool() {
            let mut outer = anubis_mk_list(vec![anubis_mk_str("call".to_string()), anubis_mk_str("exp".to_string()), anubis_mk_list(vec![u.clone()])]);
            return anubis_mk_list(vec![anubis_mk_str("mul".to_string()), outer.clone(), du.clone()]);
        }
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("d/dx: no rule for function '".to_string())), name.clone()), anubis_mk_str("'; fail closed".to_string())));
    }
    anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("internal error: unknown AST node '".to_string())), tag.clone()), anubis_mk_str("'".to_string())))
}

fn anb_verify_derivative(mut ast: AnubisValue, mut derived: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut bindings = anb_collect_vars(ast.clone(), anubis_map_lit(vec![]));
    let mut samples = anubis_mk_list(vec![anubis_neg(AnubisValue::Float(2.6f64)), anubis_neg(AnubisValue::Float(1.7f64)), anubis_neg(AnubisValue::Float(1.1f64)), anubis_neg(AnubisValue::Float(0.6f64)), AnubisValue::Float(0.3f64), AnubisValue::Float(0.9f64), AnubisValue::Float(1.4f64), AnubisValue::Float(1.8f64), AnubisValue::Float(2.7f64)]);
    let mut step = AnubisValue::Float(0.00001f64);
    let mut used = AnubisValue::Int(0);
    let mut skipped = AnubisValue::Int(0);
    let mut worst = AnubisValue::Float(0f64);
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (samples.clone()).len_val()).as_bool() {
        let mut xv = samples.index_get(i.clone());
        i = anubis_add(i.clone(), AnubisValue::Int(1));
        let mut env = bindings.clone();
        env.set_at(&[AnubisPathSeg::Index(anubis_mk_str("x".to_string()))], xv.clone());
        let mut sym = anb_eval_ast(derived.clone(), env.clone());
        let mut env_hi = bindings.clone();
        env_hi.set_at(&[AnubisPathSeg::Index(anubis_mk_str("x".to_string()))], anubis_add(xv.clone(), step.clone()));
        let mut env_lo = bindings.clone();
        env_lo.set_at(&[AnubisPathSeg::Index(anubis_mk_str("x".to_string()))], anubis_sub(xv.clone(), step.clone()));
        let mut f_hi = anb_eval_ast(ast.clone(), env_hi.clone());
        let mut f_lo = anb_eval_ast(ast.clone(), env_lo.clone());
        let mut coarse = anubis_div(anubis_sub(f_hi.clone(), f_lo.clone()), anubis_mul(AnubisValue::Float(2f64), step.clone()));
        let mut half = anubis_div(step.clone(), AnubisValue::Float(2f64));
        let mut env_h2 = bindings.clone();
        env_h2.set_at(&[AnubisPathSeg::Index(anubis_mk_str("x".to_string()))], anubis_add(xv.clone(), half.clone()));
        let mut env_l2 = bindings.clone();
        env_l2.set_at(&[AnubisPathSeg::Index(anubis_mk_str("x".to_string()))], anubis_sub(xv.clone(), half.clone()));
        let mut f_h2 = anb_eval_ast(ast.clone(), env_h2.clone());
        let mut f_l2 = anb_eval_ast(ast.clone(), env_l2.clone());
        let mut fine = anubis_div(anubis_sub(f_h2.clone(), f_l2.clone()), anubis_mul(AnubisValue::Float(2f64), half.clone()));
        let mut numeric = anubis_div(anubis_sub(anubis_mul(AnubisValue::Float(4f64), fine.clone()), coarse.clone()), AnubisValue::Float(3f64));
        if AnubisValue::Bool((anubis_cmp("!=", sym.clone(), sym.clone())).as_bool() || (anubis_cmp("!=", numeric.clone(), numeric.clone())).as_bool()).as_bool() {
            continue;
        }
        if AnubisValue::Bool((anubis_cmp(">", anubis_abs(sym.clone()), AnubisValue::Float(1000000000000f64))).as_bool() || (anubis_cmp(">", anubis_abs(numeric.clone()), AnubisValue::Float(1000000000000f64))).as_bool()).as_bool() {
            continue;
        }
        let mut probe_scale = anubis_max(vec![AnubisValue::Float(1f64), anubis_abs(fine.clone())]);
        if anubis_cmp(">", anubis_div(anubis_abs(anubis_sub(fine.clone(), coarse.clone())), probe_scale.clone()), AnubisValue::Float(0.01f64)).as_bool() {
            skipped = anubis_add(skipped.clone(), AnubisValue::Int(1));
            continue;
        }
        let mut scale = anubis_max(vec![AnubisValue::Float(1f64), anubis_abs(sym.clone())]);
        let mut deviation = anubis_div(anubis_abs(anubis_sub(sym.clone(), numeric.clone())), scale.clone());
        if anubis_cmp(">", deviation.clone(), worst.clone()).as_bool() {
            worst = deviation.clone();
        }
        used = anubis_add(used.clone(), AnubisValue::Int(1));
    }
    if anubis_cmp("<", used.clone(), AnubisValue::Int(3)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("d/dx: could not verify the derivative numerically on enough sample points; fail closed".to_string()));
    }
    if anubis_cmp(">", worst.clone(), AnubisValue::Float(0.0001f64)).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("d/dx: symbolic result failed numeric verification (max deviation ".to_string())), worst.clone()), anubis_mk_str("); fail closed".to_string())));
    }
    return AnubisValue::Struct { ty: "DiffCheck".to_string(), fields: vec![("points".to_string(), anubis_field_require_int(used.clone(), "points")), ("max_dev".to_string(), anubis_field_coerce_float(worst.clone(), "max_dev")), ("skipped".to_string(), anubis_field_require_int(skipped.clone(), "skipped"))] };
    AnubisValue::Int(0)
}

fn anb_big_is_zero(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Bool((anubis_cmp("==", (a.clone()).len_val(), AnubisValue::Int(1))).as_bool() && (anubis_cmp("==", a.index_get(AnubisValue::Int(0)), AnubisValue::Int(0))).as_bool());
    AnubisValue::Int(0)
}

fn anb_big_cmp(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("!=", (a.clone()).len_val(), (b.clone()).len_val()).as_bool() {
        if anubis_cmp(">", (a.clone()).len_val(), (b.clone()).len_val()).as_bool() {
            return AnubisValue::Int(1);
        }
        return anubis_neg(AnubisValue::Int(1));
    }
    let mut i = anubis_sub((a.clone()).len_val(), AnubisValue::Int(1));
    while anubis_cmp(">=", i.clone(), AnubisValue::Int(0)).as_bool() {
        if anubis_cmp("!=", a.index_get(i.clone()), b.index_get(i.clone())).as_bool() {
            if anubis_cmp(">", a.index_get(i.clone()), b.index_get(i.clone())).as_bool() {
                return AnubisValue::Int(1);
            }
            return anubis_neg(AnubisValue::Int(1));
        }
        i = anubis_sub(i.clone(), AnubisValue::Int(1));
    }
    return AnubisValue::Int(0);
    AnubisValue::Int(0)
}

fn anb_big_sub(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", anb_big_cmp(a.clone(), b.clone()), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("internal error: big_sub underflow; fail closed".to_string()));
    }
    let mut result = anubis_mk_list(vec![]);
    let mut borrow = AnubisValue::Int(0);
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (a.clone()).len_val()).as_bool() {
        let mut current = anubis_sub(a.index_get(i.clone()), borrow.clone());
        if anubis_cmp("<", i.clone(), (b.clone()).len_val()).as_bool() {
            current = anubis_sub(current.clone(), b.index_get(i.clone()));
        }
        if anubis_cmp("<", current.clone(), AnubisValue::Int(0)).as_bool() {
            current = anubis_add(current.clone(), AnubisValue::Int(1000000000));
            borrow = AnubisValue::Int(1);
        } else {
            borrow = AnubisValue::Int(0);
        }
        result.push_val(current.clone());
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return anb_big_normalize(result.clone());
    AnubisValue::Int(0)
}

fn anb_big_is_even(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_cmp("==", anubis_mod(a.index_get(AnubisValue::Int(0)), AnubisValue::Int(2)), AnubisValue::Int(0));
    AnubisValue::Int(0)
}

fn anb_big_half(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return (anb_big_divmod_small(a.clone(), AnubisValue::Int(2))).field_get("quotient");
    AnubisValue::Int(0)
}

fn anb_big_gcd(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anb_big_is_zero(a.clone()).as_bool() {
        return b.clone();
    }
    if anb_big_is_zero(b.clone()).as_bool() {
        return a.clone();
    }
    let mut x = a.clone();
    let mut y = b.clone();
    let mut shift = AnubisValue::Int(0);
    while AnubisValue::Bool((anb_big_is_even(x.clone())).as_bool() && (anb_big_is_even(y.clone())).as_bool()).as_bool() {
        x = anb_big_half(x.clone());
        y = anb_big_half(y.clone());
        shift = anubis_add(shift.clone(), AnubisValue::Int(1));
    }
    while anb_big_is_even(x.clone()).as_bool() {
        x = anb_big_half(x.clone());
    }
    while AnubisValue::Bool(true).as_bool() {
        while anb_big_is_even(y.clone()).as_bool() {
            y = anb_big_half(y.clone());
        }
        if anubis_cmp(">", anb_big_cmp(x.clone(), y.clone()), AnubisValue::Int(0)).as_bool() {
            let mut swap = x.clone();
            x = y.clone();
            y = swap.clone();
        }
        y = anb_big_sub(y.clone(), x.clone());
        if anb_big_is_zero(y.clone()).as_bool() {
            break;
        }
    }
    let mut s = AnubisValue::Int(0);
    while anubis_cmp("<", s.clone(), shift.clone()).as_bool() {
        x = anb_big_add(x.clone(), x.clone());
        s = anubis_add(s.clone(), AnubisValue::Int(1));
    }
    return x.clone();
    AnubisValue::Int(0)
}

fn anb_big_divmod(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anb_big_is_zero(b.clone()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("exact division by zero; fail closed".to_string()));
    }
    if anubis_cmp("<", anb_big_cmp(a.clone(), b.clone()), AnubisValue::Int(0)).as_bool() {
        return AnubisValue::Struct { ty: "BigDivmod".to_string(), fields: vec![("quotient".to_string(), anubis_mk_list(vec![AnubisValue::Int(0)])), ("remainder".to_string(), a.clone())] };
    }
    let mut digits = anb_big_to_text(a.clone());
    let mut remainder = anubis_mk_list(vec![AnubisValue::Int(0)]);
    let mut quotient_text = anubis_mk_str("".to_string());
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (digits.clone()).len_val()).as_bool() {
        remainder = anb_big_mul_small(remainder.clone(), AnubisValue::Int(10));
        remainder = anb_big_add(remainder.clone(), anubis_mk_list(vec![anb_digit_value((digits.clone()).index_get(i.clone()))]));
        let mut q = AnubisValue::Int(0);
        while anubis_cmp(">=", anb_big_cmp(remainder.clone(), b.clone()), AnubisValue::Int(0)).as_bool() {
            remainder = anb_big_sub(remainder.clone(), b.clone());
            q = anubis_add(q.clone(), AnubisValue::Int(1));
        }
        quotient_text = anubis_add(quotient_text.clone(), anubis_str(q.clone()));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return AnubisValue::Struct { ty: "BigDivmod".to_string(), fields: vec![("quotient".to_string(), anb_big_from_text(quotient_text.clone())), ("remainder".to_string(), remainder.clone())] };
    AnubisValue::Int(0)
}

fn anb_rat_make(mut neg: AnubisValue, mut num: AnubisValue, mut den: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anb_big_is_zero(den.clone()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("exact division by zero; fail closed".to_string()));
    }
    if anb_big_is_zero(num.clone()).as_bool() {
        return AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), anubis_mk_list(vec![AnubisValue::Int(0)])), ("den".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)]))] };
    }
    let mut g = anb_big_gcd(num.clone(), den.clone());
    let mut reduced_num = (anb_big_divmod(num.clone(), g.clone())).field_get("quotient");
    let mut reduced_den = (anb_big_divmod(den.clone(), g.clone())).field_get("quotient");
    return AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), neg.clone()), ("num".to_string(), reduced_num.clone()), ("den".to_string(), reduced_den.clone())] };
    AnubisValue::Int(0)
}

fn anb_rat_neg(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut num = a.field_get("num");
    if anb_big_is_zero(num.clone()).as_bool() {
        return a.clone();
    }
    let mut flag = a.field_get("neg");
    return AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(!(flag.clone()).as_bool())), ("num".to_string(), a.field_get("num")), ("den".to_string(), a.field_get("den"))] };
    AnubisValue::Int(0)
}

fn anb_rat_add_impl(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut left = anb_big_mul(a.field_get("num"), b.field_get("den"));
    let mut right = anb_big_mul(b.field_get("num"), a.field_get("den"));
    let mut den = anb_big_mul(a.field_get("den"), b.field_get("den"));
    let mut a_neg = a.field_get("neg");
    let mut b_neg = b.field_get("neg");
    if anubis_cmp("==", a_neg.clone(), b_neg.clone()).as_bool() {
        return anb_rat_make(a_neg.clone(), anb_big_add(left.clone(), right.clone()), den.clone());
    }
    let mut comparison = anb_big_cmp(left.clone(), right.clone());
    if anubis_cmp("==", comparison.clone(), AnubisValue::Int(0)).as_bool() {
        return anb_rat_make(AnubisValue::Bool(false), anubis_mk_list(vec![AnubisValue::Int(0)]), anubis_mk_list(vec![AnubisValue::Int(1)]));
    }
    if anubis_cmp(">", comparison.clone(), AnubisValue::Int(0)).as_bool() {
        return anb_rat_make(a_neg.clone(), anb_big_sub(left.clone(), right.clone()), den.clone());
    }
    return anb_rat_make(b_neg.clone(), anb_big_sub(right.clone(), left.clone()), den.clone());
    AnubisValue::Int(0)
}

fn anb_rat_sub(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_rat_add_impl(a.clone(), anb_rat_neg(b.clone()));
    AnubisValue::Int(0)
}

fn anb_rat_mul(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut a_neg = a.field_get("neg");
    let mut b_neg = b.field_get("neg");
    return anb_rat_make(anubis_cmp("!=", a_neg.clone(), b_neg.clone()), anb_big_mul(a.field_get("num"), b.field_get("num")), anb_big_mul(a.field_get("den"), b.field_get("den")));
    AnubisValue::Int(0)
}

fn anb_rat_div(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut b_num = b.field_get("num");
    if anb_big_is_zero(b_num.clone()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("exact division by zero; fail closed".to_string()));
    }
    let mut a_neg = a.field_get("neg");
    let mut b_neg = b.field_get("neg");
    return anb_rat_make(anubis_cmp("!=", a_neg.clone(), b_neg.clone()), anb_big_mul(a.field_get("num"), b.field_get("den")), anb_big_mul(a.field_get("den"), b.field_get("num")));
    AnubisValue::Int(0)
}

fn anb_rat_pow(mut a: AnubisValue, mut exponent: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", exponent.clone(), AnubisValue::Int(0)).as_bool() {
        return AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)])), ("den".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)]))] };
    }
    let mut flip = anubis_cmp("<", exponent.clone(), AnubisValue::Int(0));
    let mut e = exponent.clone();
    if flip.clone().as_bool() {
        e = anubis_neg(e.clone());
    }
    if anubis_cmp(">", e.clone(), AnubisValue::Int(10000)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("rat: exponent is capped at 10000 (compute budget); fail closed".to_string()));
    }
    let mut a_num = a.field_get("num");
    if AnubisValue::Bool((flip.clone()).as_bool() && (anb_big_is_zero(a_num.clone())).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("exact division by zero; fail closed".to_string()));
    }
    let mut num = anubis_mk_list(vec![AnubisValue::Int(1)]);
    let mut den = anubis_mk_list(vec![AnubisValue::Int(1)]);
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), e.clone()).as_bool() {
        num = anb_big_mul(num.clone(), a.field_get("num"));
        den = anb_big_mul(den.clone(), a.field_get("den"));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    let mut base_neg = a.field_get("neg");
    let mut neg = AnubisValue::Bool((base_neg.clone()).as_bool() && (anubis_cmp("==", anubis_mod(e.clone(), AnubisValue::Int(2)), AnubisValue::Int(1))).as_bool());
    if flip.clone().as_bool() {
        return anb_rat_make(neg.clone(), den.clone(), num.clone());
    }
    return anb_rat_make(neg.clone(), num.clone(), den.clone());
    AnubisValue::Int(0)
}

fn anb_rat_from_num_text(mut text: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut mantissa = anubis_mk_str("".to_string());
    let mut frac_digits = AnubisValue::Int(0);
    let mut exp_value = AnubisValue::Int(0);
    let mut exp_neg = AnubisValue::Bool(false);
    let mut seen_dot = AnubisValue::Bool(false);
    let mut i = AnubisValue::Int(0);
    let mut n = (text.clone()).len_val();
    while anubis_cmp("<", i.clone(), n.clone()).as_bool() {
        let mut ch = (text.clone()).index_get(i.clone());
        if anubis_cmp("==", ch.clone(), anubis_mk_str(".".to_string())).as_bool() {
            seen_dot = AnubisValue::Bool(true);
            i = anubis_add(i.clone(), AnubisValue::Int(1));
            continue;
        }
        if AnubisValue::Bool((anubis_cmp("==", ch.clone(), anubis_mk_str("e".to_string()))).as_bool() || (anubis_cmp("==", ch.clone(), anubis_mk_str("E".to_string()))).as_bool()).as_bool() {
            i = anubis_add(i.clone(), AnubisValue::Int(1));
            if AnubisValue::Bool((anubis_cmp("<", i.clone(), n.clone())).as_bool() && (AnubisValue::Bool((anubis_cmp("==", (text.clone()).index_get(i.clone()), anubis_mk_str("+".to_string()))).as_bool() || (anubis_cmp("==", (text.clone()).index_get(i.clone()), anubis_mk_str("-".to_string()))).as_bool())).as_bool()).as_bool() {
                if anubis_cmp("==", (text.clone()).index_get(i.clone()), anubis_mk_str("-".to_string())).as_bool() {
                    exp_neg = AnubisValue::Bool(true);
                }
                i = anubis_add(i.clone(), AnubisValue::Int(1));
            }
            while anubis_cmp("<", i.clone(), n.clone()).as_bool() {
                exp_value = anubis_add(anubis_mul(exp_value.clone(), AnubisValue::Int(10)), anb_digit_value((text.clone()).index_get(i.clone())));
                i = anubis_add(i.clone(), AnubisValue::Int(1));
            }
            break;
        }
        mantissa = anubis_add(mantissa.clone(), ch.clone());
        if seen_dot.clone().as_bool() {
            frac_digits = anubis_add(frac_digits.clone(), AnubisValue::Int(1));
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    if anubis_cmp(">", exp_value.clone(), AnubisValue::Int(10000)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("rat: exponent is capped at 10000 (compute budget); fail closed".to_string()));
    }
    let mut shift = exp_value.clone();
    if exp_neg.clone().as_bool() {
        shift = anubis_neg(shift.clone());
    }
    let mut power = anubis_sub(shift.clone(), frac_digits.clone());
    let mut num = anb_big_from_text(mantissa.clone());
    let mut den = anubis_mk_list(vec![AnubisValue::Int(1)]);
    if anubis_cmp(">", power.clone(), AnubisValue::Int(0)).as_bool() {
        num = anb_big_mul(num.clone(), anb_big_pow(anubis_mk_list(vec![AnubisValue::Int(10)]), power.clone()));
    }
    if anubis_cmp("<", power.clone(), AnubisValue::Int(0)).as_bool() {
        den = anb_big_pow(anubis_mk_list(vec![AnubisValue::Int(10)]), anubis_neg(power.clone()));
    }
    return anb_rat_make(AnubisValue::Bool(false), num.clone(), den.clone());
    AnubisValue::Int(0)
}

fn anb_rat_exponent_value(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", node.index_get(AnubisValue::Int(0)), anubis_mk_str("neg".to_string())).as_bool() {
        return anubis_neg(anb_rat_exponent_value(node.index_get(AnubisValue::Int(1))));
    }
    if anubis_cmp("==", node.index_get(AnubisValue::Int(0)), anubis_mk_str("num".to_string())).as_bool() {
        let mut text = node.index_get(AnubisValue::Int(2));
        if anubis_cmp(">", (text.clone()).len_val(), AnubisValue::Int(5)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("rat: exponent is capped at 10000 (compute budget); fail closed".to_string()));
        }
        let mut i = AnubisValue::Int(0);
        while anubis_cmp("<", i.clone(), (text.clone()).len_val()).as_bool() {
            let mut ch = (text.clone()).index_get(i.clone());
            if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", ch.clone(), anubis_mk_str(".".to_string()))).as_bool() || (anubis_cmp("==", ch.clone(), anubis_mk_str("e".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", ch.clone(), anubis_mk_str("E".to_string()))).as_bool()).as_bool() {
                let _ = anubis_panic(anubis_mk_str("rat: ^ requires an integer exponent in exact mode; fail closed".to_string()));
            }
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        return anubis_parse_int(text.clone());
    }
    anubis_panic(anubis_mk_str("rat: ^ requires an integer exponent in exact mode; fail closed".to_string()))
}

fn anb_rat_eval_ast(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string())).as_bool() {
        return anb_rat_from_num_text(node.index_get(AnubisValue::Int(2)));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        return anb_rat_neg(anb_rat_eval_ast(node.index_get(AnubisValue::Int(1))));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string())).as_bool() {
        return anb_rat_add_impl(anb_rat_eval_ast(node.index_get(AnubisValue::Int(1))), anb_rat_eval_ast(node.index_get(AnubisValue::Int(2))));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string())).as_bool() {
        return anb_rat_sub(anb_rat_eval_ast(node.index_get(AnubisValue::Int(1))), anb_rat_eval_ast(node.index_get(AnubisValue::Int(2))));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string())).as_bool() {
        return anb_rat_mul(anb_rat_eval_ast(node.index_get(AnubisValue::Int(1))), anb_rat_eval_ast(node.index_get(AnubisValue::Int(2))));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string())).as_bool() {
        return anb_rat_div(anb_rat_eval_ast(node.index_get(AnubisValue::Int(1))), anb_rat_eval_ast(node.index_get(AnubisValue::Int(2))));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("pow".to_string())).as_bool() {
        return anb_rat_pow(anb_rat_eval_ast(node.index_get(AnubisValue::Int(1))), anb_rat_exponent_value(node.index_get(AnubisValue::Int(2))));
    }
    anubis_panic(anubis_mk_str("rat: exact mode supports integers, decimals, + - * / ^ with integer exponents, and parentheses only; fail closed".to_string()))
}

fn anb_rat_to_text(mut r: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut sign = anubis_mk_str("".to_string());
    let mut r_neg = r.field_get("neg");
    if r_neg.clone().as_bool() {
        sign = anubis_mk_str("-".to_string());
    }
    if anubis_cmp("==", anb_big_to_text(r.field_get("den")), anubis_mk_str("1".to_string())).as_bool() {
        return anubis_add(sign.clone(), anb_big_to_text(r.field_get("num")));
    }
    return anubis_add(anubis_add(anubis_add(sign.clone(), anb_big_to_text(r.field_get("num"))), anubis_mk_str("/".to_string())), anb_big_to_text(r.field_get("den")));
    AnubisValue::Int(0)
}

fn anb_rat_to_f64(mut r: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anb_big_is_zero(r.field_get("num")).as_bool() {
        return AnubisValue::Float(0f64);
    }
    let mut s = anubis_add(AnubisValue::Int(30), (anb_big_to_text(r.field_get("den"))).len_val());
    let mut scaled = anb_big_divmod(anb_big_mul(r.field_get("num"), anb_big_pow(anubis_mk_list(vec![AnubisValue::Int(10)]), s.clone())), r.field_get("den"));
    let mut text = anubis_add(anubis_add(anb_big_to_text(scaled.field_get("quotient")), anubis_mk_str("e-".to_string())), anubis_str(s.clone()));
    if r.field_get("neg").as_bool() {
        text = anubis_add(anubis_mk_str("-".to_string()), text.clone());
    }
    { let __anb_m4 = anubis_parse_float_opt(text.clone()); let mut __anb_r4 = AnubisValue::Int(0); let mut __anb_done4 = false; if !__anb_done4 { if matches!(&__anb_m4, AnubisValue::Enum { ty, tag, .. } if ty == "Option" && tag == "Some") { let __anb_m4_p0 = (match &__anb_m4 { AnubisValue::Enum { fields, .. } if fields.len() > 0 => fields[0].clone(), _ => AnubisValue::Int(0) }); let mut v = __anb_m4_p0.clone(); __anb_r4 = (v.clone()); __anb_done4 = true; } } if !__anb_done4 { if matches!(&__anb_m4, AnubisValue::Enum { ty, tag, .. } if ty == "Option" && tag == "None") { __anb_r4 = (anubis_panic(anubis_mk_str("rat: internal approx rendering parse failed; fail closed".to_string()))); __anb_done4 = true; } } if !__anb_done4 { panic!("ANUBIS_MATCH_UNMATCHED: no match arm matched value `{}` (add a `_` arm)", (__anb_m4).display_string()); } __anb_r4 }
}

fn anb_rat_zero() -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), anubis_mk_list(vec![AnubisValue::Int(0)])), ("den".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)]))] };
    AnubisValue::Int(0)
}

fn anb_rat_one() -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)])), ("den".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)]))] };
    AnubisValue::Int(0)
}

fn anb_rat_int(mut n: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", n.clone(), AnubisValue::Int(0)).as_bool() {
        return anb_rat_neg(anb_rat_from_num_text(anubis_str(anubis_neg(n.clone()))));
    }
    return anb_rat_from_num_text(anubis_str(n.clone()));
    AnubisValue::Int(0)
}

fn anb_rat_abs(mut r: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), r.field_get("num")), ("den".to_string(), r.field_get("den"))] };
    AnubisValue::Int(0)
}

fn anb_rat_cmp(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut d = anb_rat_sub(a.clone(), b.clone());
    if anb_big_is_zero(d.field_get("num")).as_bool() {
        return AnubisValue::Int(0);
    }
    if d.field_get("neg").as_bool() {
        return anubis_neg(AnubisValue::Int(1));
    }
    return AnubisValue::Int(1);
    AnubisValue::Int(0)
}

fn anb_rat_min(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<=", anb_rat_cmp(a.clone(), b.clone()), AnubisValue::Int(0)).as_bool() {
        return a.clone();
    }
    return b.clone();
    AnubisValue::Int(0)
}

fn anb_rat_max(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp(">=", anb_rat_cmp(a.clone(), b.clone()), AnubisValue::Int(0)).as_bool() {
        return a.clone();
    }
    return b.clone();
    AnubisValue::Int(0)
}

fn anb_rat_min4(mut a: AnubisValue, mut b: AnubisValue, mut c: AnubisValue, mut d: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_rat_min(anb_rat_min(a.clone(), b.clone()), anb_rat_min(c.clone(), d.clone()));
    AnubisValue::Int(0)
}

fn anb_rat_max4(mut a: AnubisValue, mut b: AnubisValue, mut c: AnubisValue, mut d: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_rat_max(anb_rat_max(a.clone(), b.clone()), anb_rat_max(c.clone(), d.clone()));
    AnubisValue::Int(0)
}

fn anb_cert_eps() -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)])), ("den".to_string(), anb_big_pow(anubis_mk_list(vec![AnubisValue::Int(10)]), AnubisValue::Int(15)))] };
    AnubisValue::Int(0)
}

fn anb_cert_tau() -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)])), ("den".to_string(), anb_big_pow(anubis_mk_list(vec![AnubisValue::Int(10)]), AnubisValue::Int(300)))] };
    AnubisValue::Int(0)
}

fn anb_cert_pad(mut v: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_rat_add_impl(anb_rat_mul(anb_cert_eps(), anb_rat_abs(v.clone())), anb_cert_tau());
    AnubisValue::Int(0)
}

fn anb_cert_pad_lo(mut v: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_rat_sub(v.clone(), anb_cert_pad(v.clone()));
    AnubisValue::Int(0)
}

fn anb_cert_pad_hi(mut v: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_rat_add_impl(v.clone(), anb_cert_pad(v.clone()));
    AnubisValue::Int(0)
}

fn anb_rat_floor(mut r: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut q = anb_big_divmod(r.field_get("num"), r.field_get("den"));
    if anb_big_is_zero(q.field_get("remainder")).as_bool() {
        if r.field_get("neg").as_bool() {
            return anb_rat_neg(AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), q.field_get("quotient")), ("den".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)]))] });
        }
        return AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), q.field_get("quotient")), ("den".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)]))] };
    }
    if r.field_get("neg").as_bool() {
        return anb_rat_neg(AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), anb_big_add(q.field_get("quotient"), anubis_mk_list(vec![AnubisValue::Int(1)]))), ("den".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)]))] });
    }
    return AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), q.field_get("quotient")), ("den".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)]))] };
    AnubisValue::Int(0)
}

fn anb_rat_ceil(mut r: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_rat_neg(anb_rat_floor(anb_rat_neg(r.clone())));
    AnubisValue::Int(0)
}

fn anb_rat_trunc(mut r: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut q = anb_big_divmod(r.field_get("num"), r.field_get("den"));
    if r.field_get("neg").as_bool() {
        return anb_rat_neg(AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), q.field_get("quotient")), ("den".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)]))] });
    }
    return AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), q.field_get("quotient")), ("den".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)]))] };
    AnubisValue::Int(0)
}

fn anb_rat_round_away(mut r: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut half = AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), r.field_get("neg")), ("num".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)])), ("den".to_string(), anubis_mk_list(vec![AnubisValue::Int(2)]))] };
    return anb_rat_trunc(anb_rat_add_impl(r.clone(), half.clone()));
    AnubisValue::Int(0)
}

fn anb_rat_mig(mut l: AnubisValue, mut u: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp("<=", anb_rat_cmp(l.clone(), anb_rat_zero()), AnubisValue::Int(0))).as_bool() && (anubis_cmp(">=", anb_rat_cmp(u.clone(), anb_rat_zero()), AnubisValue::Int(0))).as_bool()).as_bool() {
        return anb_rat_zero();
    }
    return anb_rat_min(anb_rat_abs(l.clone()), anb_rat_abs(u.clone()));
    AnubisValue::Int(0)
}

fn anb_rat_mag(mut l: AnubisValue, mut u: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_rat_max(anb_rat_abs(l.clone()), anb_rat_abs(u.clone()));
    AnubisValue::Int(0)
}

fn anb_cert_pair(mut lo: AnubisValue, mut hi: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_add(anubis_add(anb_rat_to_text(lo.clone()), anubis_mk_str(",".to_string())), anb_rat_to_text(hi.clone()));
    AnubisValue::Int(0)
}

fn anb_cert_leaf_line(mut id: AnubisValue, mut op: AnubisValue, mut out_lo: AnubisValue, mut out_hi: AnubisValue, mut extra: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("node ".to_string()), anubis_str(id.clone())), anubis_mk_str(" ".to_string())), op.clone()), anubis_mk_str(" children[] out[".to_string())), anb_cert_pair(out_lo.clone(), out_hi.clone())), anubis_mk_str("]".to_string())), extra.clone());
    AnubisValue::Int(0)
}

fn anb_cert_eval(mut node: AnubisValue, mut xlo: AnubisValue, mut xhi: AnubisValue, mut nodes: AnubisValue, mut next: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string())).as_bool() {
        let mut r = anb_rat_from_num_text(node.index_get(AnubisValue::Int(2)));
        let mut line = anb_cert_leaf_line(next.clone(), anubis_mk_str("num_exact".to_string()), r.clone(), r.clone(), anubis_add(anubis_add(anubis_add(anubis_mk_str(" val ".to_string()), anb_rat_to_text(r.clone())), anubis_mk_str(" name ".to_string())), node.index_get(AnubisValue::Int(2))));
        return AnubisValue::Struct { ty: "CE".to_string(), fields: vec![("lo".to_string(), r.clone()), ("hi".to_string(), r.clone()), ("id".to_string(), anubis_field_require_int(next.clone(), "id")), ("nodes".to_string(), anb_push_str(nodes.clone(), line.clone())), ("next".to_string(), anubis_field_require_int(anubis_add(next.clone(), AnubisValue::Int(1)), "next"))] };
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string())).as_bool() {
        if anubis_cmp("!=", node.index_get(AnubisValue::Int(1)), anubis_mk_str("x".to_string())).as_bool() {
            let _ = anubis_panic(anubis_mk_str("range-bound-cert: only x is bound; fail closed".to_string()));
        }
        let mut line = anb_cert_leaf_line(next.clone(), anubis_mk_str("var".to_string()), xlo.clone(), xhi.clone(), anubis_mk_str(" name x".to_string()));
        return AnubisValue::Struct { ty: "CE".to_string(), fields: vec![("lo".to_string(), xlo.clone()), ("hi".to_string(), xhi.clone()), ("id".to_string(), anubis_field_require_int(next.clone(), "id")), ("nodes".to_string(), anb_push_str(nodes.clone(), line.clone())), ("next".to_string(), anubis_field_require_int(anubis_add(next.clone(), AnubisValue::Int(1)), "next"))] };
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string())).as_bool() {
        let mut approx = anb_cert_const_rat(node.index_get(AnubisValue::Int(1)));
        let mut out_lo = anb_cert_pad_lo(approx.clone());
        let mut out_hi = anb_cert_pad_hi(approx.clone());
        let mut extra = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str(" val ".to_string()), anb_rat_to_text(approx.clone())), anubis_mk_str(" f[".to_string())), anb_cert_pair(approx.clone(), approx.clone())), anubis_mk_str("] name ".to_string())), node.index_get(AnubisValue::Int(1)));
        let mut line = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("node ".to_string()), anubis_str(next.clone())), anubis_mk_str(" const_rounded children[] out[".to_string())), anb_cert_pair(out_lo.clone(), out_hi.clone())), anubis_mk_str("]".to_string())), extra.clone());
        return AnubisValue::Struct { ty: "CE".to_string(), fields: vec![("lo".to_string(), out_lo.clone()), ("hi".to_string(), out_hi.clone()), ("id".to_string(), anubis_field_require_int(next.clone(), "id")), ("nodes".to_string(), anb_push_str(nodes.clone(), line.clone())), ("next".to_string(), anubis_field_require_int(anubis_add(next.clone(), AnubisValue::Int(1)), "next"))] };
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        let mut c = anb_cert_eval(node.index_get(AnubisValue::Int(1)), xlo.clone(), xhi.clone(), nodes.clone(), next.clone());
        let mut out_lo = anb_rat_neg(c.field_get("hi"));
        let mut out_hi = anb_rat_neg(c.field_get("lo"));
        let mut line = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("node ".to_string()), anubis_str(c.field_get("next"))), anubis_mk_str(" neg children[".to_string())), anubis_str(c.field_get("id"))), anubis_mk_str("] out[".to_string())), anb_cert_pair(out_lo.clone(), out_hi.clone())), anubis_mk_str("]".to_string()));
        return AnubisValue::Struct { ty: "CE".to_string(), fields: vec![("lo".to_string(), out_lo.clone()), ("hi".to_string(), out_hi.clone()), ("id".to_string(), anubis_field_require_int(c.field_get("next"), "id")), ("nodes".to_string(), anb_push_str(c.field_get("nodes"), line.clone())), ("next".to_string(), anubis_field_require_int(anubis_add(c.field_get("next"), AnubisValue::Int(1)), "next"))] };
    }
    if AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string()))).as_bool()).as_bool() {
        let mut l = anb_cert_eval(node.index_get(AnubisValue::Int(1)), xlo.clone(), xhi.clone(), nodes.clone(), next.clone());
        let mut r = anb_cert_eval(node.index_get(AnubisValue::Int(2)), xlo.clone(), xhi.clone(), l.field_get("nodes"), l.field_get("next"));
        return anb_cert_binary(tag.clone(), l.clone(), r.clone());
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("call".to_string())).as_bool() {
        return anb_cert_call(node.clone(), xlo.clone(), xhi.clone(), nodes.clone(), next.clone());
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("pow".to_string())).as_bool() {
        return anb_cert_pow(node.clone(), xlo.clone(), xhi.clone(), nodes.clone(), next.clone());
    }
    anubis_panic(anubis_add(anubis_add(anubis_mk_str("range-bound-cert: unsupported construct '".to_string()), tag.clone()), anubis_mk_str("'; fail closed (outside the certified fragment)".to_string())))
}

fn anb_cert_binary(mut tag: AnubisValue, mut l: AnubisValue, mut r: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut id = r.field_get("next");
    if anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string())).as_bool() {
        let mut flo = anb_rat_add_impl(l.field_get("lo"), r.field_get("lo"));
        let mut fhi = anb_rat_add_impl(l.field_get("hi"), r.field_get("hi"));
        let mut out_lo = anb_cert_pad_lo(flo.clone());
        let mut out_hi = anb_cert_pad_hi(fhi.clone());
        let mut line = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("node ".to_string()), anubis_str(id.clone())), anubis_mk_str(" add children[".to_string())), anubis_str(l.field_get("id"))), anubis_mk_str(",".to_string())), anubis_str(r.field_get("id"))), anubis_mk_str("] out[".to_string())), anb_cert_pair(out_lo.clone(), out_hi.clone())), anubis_mk_str("] f[".to_string())), anb_cert_pair(flo.clone(), fhi.clone())), anubis_mk_str("]".to_string()));
        return AnubisValue::Struct { ty: "CE".to_string(), fields: vec![("lo".to_string(), out_lo.clone()), ("hi".to_string(), out_hi.clone()), ("id".to_string(), anubis_field_require_int(id.clone(), "id")), ("nodes".to_string(), anb_push_str(r.field_get("nodes"), line.clone())), ("next".to_string(), anubis_field_require_int(anubis_add(id.clone(), AnubisValue::Int(1)), "next"))] };
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string())).as_bool() {
        let mut flo = anb_rat_sub(l.field_get("lo"), r.field_get("hi"));
        let mut fhi = anb_rat_sub(l.field_get("hi"), r.field_get("lo"));
        let mut out_lo = anb_cert_pad_lo(flo.clone());
        let mut out_hi = anb_cert_pad_hi(fhi.clone());
        let mut line = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("node ".to_string()), anubis_str(id.clone())), anubis_mk_str(" sub children[".to_string())), anubis_str(l.field_get("id"))), anubis_mk_str(",".to_string())), anubis_str(r.field_get("id"))), anubis_mk_str("] out[".to_string())), anb_cert_pair(out_lo.clone(), out_hi.clone())), anubis_mk_str("] f[".to_string())), anb_cert_pair(flo.clone(), fhi.clone())), anubis_mk_str("]".to_string()));
        return AnubisValue::Struct { ty: "CE".to_string(), fields: vec![("lo".to_string(), out_lo.clone()), ("hi".to_string(), out_hi.clone()), ("id".to_string(), anubis_field_require_int(id.clone(), "id")), ("nodes".to_string(), anb_push_str(r.field_get("nodes"), line.clone())), ("next".to_string(), anubis_field_require_int(anubis_add(id.clone(), AnubisValue::Int(1)), "next"))] };
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string())).as_bool() {
        let mut p1 = anb_rat_mul(l.field_get("lo"), r.field_get("lo"));
        let mut p2 = anb_rat_mul(l.field_get("lo"), r.field_get("hi"));
        let mut p3 = anb_rat_mul(l.field_get("hi"), r.field_get("lo"));
        let mut p4 = anb_rat_mul(l.field_get("hi"), r.field_get("hi"));
        let mut out_lo = anb_cert_pad_lo(anb_rat_min4(p1.clone(), p2.clone(), p3.clone(), p4.clone()));
        let mut out_hi = anb_cert_pad_hi(anb_rat_max4(p1.clone(), p2.clone(), p3.clone(), p4.clone()));
        let mut pstr = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anb_rat_to_text(p1.clone()), anubis_mk_str(",".to_string())), anb_rat_to_text(p2.clone())), anubis_mk_str(",".to_string())), anb_rat_to_text(p3.clone())), anubis_mk_str(",".to_string())), anb_rat_to_text(p4.clone()));
        let mut line = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("node ".to_string()), anubis_str(id.clone())), anubis_mk_str(" mul children[".to_string())), anubis_str(l.field_get("id"))), anubis_mk_str(",".to_string())), anubis_str(r.field_get("id"))), anubis_mk_str("] out[".to_string())), anb_cert_pair(out_lo.clone(), out_hi.clone())), anubis_mk_str("] p[".to_string())), pstr.clone()), anubis_mk_str("]".to_string()));
        return AnubisValue::Struct { ty: "CE".to_string(), fields: vec![("lo".to_string(), out_lo.clone()), ("hi".to_string(), out_hi.clone()), ("id".to_string(), anubis_field_require_int(id.clone(), "id")), ("nodes".to_string(), anb_push_str(r.field_get("nodes"), line.clone())), ("next".to_string(), anubis_field_require_int(anubis_add(id.clone(), AnubisValue::Int(1)), "next"))] };
    }
    let mut dsign = AnubisValue::Int(0);
    if anubis_cmp(">", anb_rat_cmp(r.field_get("lo"), anb_rat_zero()), AnubisValue::Int(0)).as_bool() {
        dsign = AnubisValue::Int(1);
    } else {
        if anubis_cmp("<", anb_rat_cmp(r.field_get("hi"), anb_rat_zero()), AnubisValue::Int(0)).as_bool() {
            dsign = anubis_neg(AnubisValue::Int(1));
        } else {
            let _ = anubis_panic(anubis_mk_str("range-bound-cert: division by an interval containing zero; fail closed".to_string()));
        }
    }
    let mut q1 = anb_rat_div(l.field_get("lo"), r.field_get("lo"));
    let mut q2 = anb_rat_div(l.field_get("lo"), r.field_get("hi"));
    let mut q3 = anb_rat_div(l.field_get("hi"), r.field_get("lo"));
    let mut q4 = anb_rat_div(l.field_get("hi"), r.field_get("hi"));
    let mut out_lo = anb_cert_pad_lo(anb_rat_min4(q1.clone(), q2.clone(), q3.clone(), q4.clone()));
    let mut out_hi = anb_cert_pad_hi(anb_rat_max4(q1.clone(), q2.clone(), q3.clone(), q4.clone()));
    let mut qstr = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anb_rat_to_text(q1.clone()), anubis_mk_str(",".to_string())), anb_rat_to_text(q2.clone())), anubis_mk_str(",".to_string())), anb_rat_to_text(q3.clone())), anubis_mk_str(",".to_string())), anb_rat_to_text(q4.clone()));
    let mut line = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("node ".to_string()), anubis_str(id.clone())), anubis_mk_str(" div children[".to_string())), anubis_str(l.field_get("id"))), anubis_mk_str(",".to_string())), anubis_str(r.field_get("id"))), anubis_mk_str("] out[".to_string())), anb_cert_pair(out_lo.clone(), out_hi.clone())), anubis_mk_str("] p[".to_string())), qstr.clone()), anubis_mk_str("] den ".to_string())), anubis_str(dsign.clone()));
    return AnubisValue::Struct { ty: "CE".to_string(), fields: vec![("lo".to_string(), out_lo.clone()), ("hi".to_string(), out_hi.clone()), ("id".to_string(), anubis_field_require_int(id.clone(), "id")), ("nodes".to_string(), anb_push_str(r.field_get("nodes"), line.clone())), ("next".to_string(), anubis_field_require_int(anubis_add(id.clone(), AnubisValue::Int(1)), "next"))] };
    AnubisValue::Int(0)
}

fn anb_push_str(mut xs: AnubisValue, mut s: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    xs.push_val(s.clone());
    return xs.clone();
    AnubisValue::Int(0)
}

fn anb_cert_const_rat(mut name: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", name.clone(), anubis_mk_str("pi".to_string())).as_bool() {
        return anb_rat_from_num_text(anubis_mk_str("3.14159265358979323846264338327950288".to_string()));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("e".to_string())).as_bool() {
        return anb_rat_from_num_text(anubis_mk_str("2.71828182845904523536028747135266250".to_string()));
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("tau".to_string())).as_bool() {
        return anb_rat_from_num_text(anubis_mk_str("6.28318530717958647692528676655900577".to_string()));
    }
    anubis_panic(anubis_add(anubis_add(anubis_mk_str("range-bound-cert: constant '".to_string()), name.clone()), anubis_mk_str("' is outside the certified fragment; fail closed".to_string())))
}

fn anb_cert_call(mut node: AnubisValue, mut xlo: AnubisValue, mut xhi: AnubisValue, mut nodes: AnubisValue, mut next: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut name = node.index_get(AnubisValue::Int(1));
    let mut args = node.index_get(AnubisValue::Int(2));
    if AnubisValue::Bool((anubis_cmp("==", name.clone(), anubis_mk_str("sin".to_string()))).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("cos".to_string()))).as_bool()).as_bool() {
        let mut c = anb_cert_eval(args.index_get(AnubisValue::Int(0)), xlo.clone(), xhi.clone(), nodes.clone(), next.clone());
        let mut out_lo = anb_rat_int(anubis_neg(AnubisValue::Int(1)));
        let mut out_hi = anb_rat_one();
        let mut line = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("node ".to_string()), anubis_str(c.field_get("next"))), anubis_mk_str(" ".to_string())), name.clone()), anubis_mk_str(" children[".to_string())), anubis_str(c.field_get("id"))), anubis_mk_str("] out[".to_string())), anb_cert_pair(out_lo.clone(), out_hi.clone())), anubis_mk_str("]".to_string()));
        return AnubisValue::Struct { ty: "CE".to_string(), fields: vec![("lo".to_string(), out_lo.clone()), ("hi".to_string(), out_hi.clone()), ("id".to_string(), anubis_field_require_int(c.field_get("next"), "id")), ("nodes".to_string(), anb_push_str(c.field_get("nodes"), line.clone())), ("next".to_string(), anubis_field_require_int(anubis_add(c.field_get("next"), AnubisValue::Int(1)), "next"))] };
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("abs".to_string())).as_bool() {
        let mut c = anb_cert_eval(args.index_get(AnubisValue::Int(0)), xlo.clone(), xhi.clone(), nodes.clone(), next.clone());
        let mut out_lo = anb_rat_zero();
        let mut out_hi = anb_rat_zero();
        if anubis_cmp(">=", anb_rat_cmp(c.field_get("lo"), anb_rat_zero()), AnubisValue::Int(0)).as_bool() {
            out_lo = c.field_get("lo");
            out_hi = c.field_get("hi");
        } else {
            if anubis_cmp("<=", anb_rat_cmp(c.field_get("hi"), anb_rat_zero()), AnubisValue::Int(0)).as_bool() {
                out_lo = anb_rat_neg(c.field_get("hi"));
                out_hi = anb_rat_neg(c.field_get("lo"));
            } else {
                out_lo = anb_rat_zero();
                out_hi = anb_rat_max(anb_rat_neg(c.field_get("lo")), c.field_get("hi"));
            }
        }
        let mut line = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("node ".to_string()), anubis_str(c.field_get("next"))), anubis_mk_str(" abs children[".to_string())), anubis_str(c.field_get("id"))), anubis_mk_str("] out[".to_string())), anb_cert_pair(out_lo.clone(), out_hi.clone())), anubis_mk_str("]".to_string()));
        return AnubisValue::Struct { ty: "CE".to_string(), fields: vec![("lo".to_string(), out_lo.clone()), ("hi".to_string(), out_hi.clone()), ("id".to_string(), anubis_field_require_int(c.field_get("next"), "id")), ("nodes".to_string(), anb_push_str(c.field_get("nodes"), line.clone())), ("next".to_string(), anubis_field_require_int(anubis_add(c.field_get("next"), AnubisValue::Int(1)), "next"))] };
    }
    if AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", name.clone(), anubis_mk_str("floor".to_string()))).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("ceil".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("round".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("trunc".to_string()))).as_bool()).as_bool() {
        let mut c = anb_cert_eval(args.index_get(AnubisValue::Int(0)), xlo.clone(), xhi.clone(), nodes.clone(), next.clone());
        let mut out_lo = anb_cert_int_op(name.clone(), c.field_get("lo"));
        let mut out_hi = anb_cert_int_op(name.clone(), c.field_get("hi"));
        let mut line = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("node ".to_string()), anubis_str(c.field_get("next"))), anubis_mk_str(" ".to_string())), name.clone()), anubis_mk_str(" children[".to_string())), anubis_str(c.field_get("id"))), anubis_mk_str("] out[".to_string())), anb_cert_pair(out_lo.clone(), out_hi.clone())), anubis_mk_str("]".to_string()));
        return AnubisValue::Struct { ty: "CE".to_string(), fields: vec![("lo".to_string(), out_lo.clone()), ("hi".to_string(), out_hi.clone()), ("id".to_string(), anubis_field_require_int(c.field_get("next"), "id")), ("nodes".to_string(), anb_push_str(c.field_get("nodes"), line.clone())), ("next".to_string(), anubis_field_require_int(anubis_add(c.field_get("next"), AnubisValue::Int(1)), "next"))] };
    }
    if AnubisValue::Bool((anubis_cmp("==", name.clone(), anubis_mk_str("min".to_string()))).as_bool() || (anubis_cmp("==", name.clone(), anubis_mk_str("max".to_string()))).as_bool()).as_bool() {
        let mut l = anb_cert_eval(args.index_get(AnubisValue::Int(0)), xlo.clone(), xhi.clone(), nodes.clone(), next.clone());
        let mut r = anb_cert_eval(args.index_get(AnubisValue::Int(1)), xlo.clone(), xhi.clone(), l.field_get("nodes"), l.field_get("next"));
        let mut id = r.field_get("next");
        let mut out_lo = anb_rat_min(l.field_get("lo"), r.field_get("lo"));
        let mut out_hi = anb_rat_min(l.field_get("hi"), r.field_get("hi"));
        if anubis_cmp("==", name.clone(), anubis_mk_str("max".to_string())).as_bool() {
            out_lo = anb_rat_max(l.field_get("lo"), r.field_get("lo"));
            out_hi = anb_rat_max(l.field_get("hi"), r.field_get("hi"));
        }
        let mut line = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("node ".to_string()), anubis_str(id.clone())), anubis_mk_str(" ".to_string())), name.clone()), anubis_mk_str(" children[".to_string())), anubis_str(l.field_get("id"))), anubis_mk_str(",".to_string())), anubis_str(r.field_get("id"))), anubis_mk_str("] out[".to_string())), anb_cert_pair(out_lo.clone(), out_hi.clone())), anubis_mk_str("]".to_string()));
        return AnubisValue::Struct { ty: "CE".to_string(), fields: vec![("lo".to_string(), out_lo.clone()), ("hi".to_string(), out_hi.clone()), ("id".to_string(), anubis_field_require_int(id.clone(), "id")), ("nodes".to_string(), anb_push_str(r.field_get("nodes"), line.clone())), ("next".to_string(), anubis_field_require_int(anubis_add(id.clone(), AnubisValue::Int(1)), "next"))] };
    }
    anubis_panic(anubis_add(anubis_add(anubis_mk_str("range-bound-cert: function '".to_string()), name.clone()), anubis_mk_str("' is a true-transcendental outside the certified fragment; fail closed".to_string())))
}

fn anb_cert_int_op(mut name: AnubisValue, mut r: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", name.clone(), anubis_mk_str("floor".to_string())).as_bool() {
        return anb_rat_floor(r.clone());
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("ceil".to_string())).as_bool() {
        return anb_rat_ceil(r.clone());
    }
    if anubis_cmp("==", name.clone(), anubis_mk_str("round".to_string())).as_bool() {
        return anb_rat_round_away(r.clone());
    }
    return anb_rat_trunc(r.clone());
    AnubisValue::Int(0)
}

fn anb_cert_exp_int(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", node.index_get(AnubisValue::Int(0)), anubis_mk_str("neg".to_string())).as_bool() {
        return anubis_neg(anb_cert_exp_int(node.index_get(AnubisValue::Int(1))));
    }
    if anubis_cmp("==", node.index_get(AnubisValue::Int(0)), anubis_mk_str("num".to_string())).as_bool() {
        let mut text = node.index_get(AnubisValue::Int(2));
        let mut i = AnubisValue::Int(0);
        while anubis_cmp("<", i.clone(), (text.clone()).len_val()).as_bool() {
            let mut ch = (text.clone()).index_get(i.clone());
            if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", ch.clone(), anubis_mk_str(".".to_string()))).as_bool() || (anubis_cmp("==", ch.clone(), anubis_mk_str("e".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", ch.clone(), anubis_mk_str("E".to_string()))).as_bool()).as_bool() {
                let _ = anubis_panic(anubis_mk_str("range-bound-cert: non-integer exponent outside the certified fragment; fail closed".to_string()));
            }
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        return anubis_parse_int(text.clone());
    }
    anubis_panic(anubis_mk_str("range-bound-cert: non-literal exponent outside the certified fragment; fail closed".to_string()))
}

fn anb_cert_pow(mut node: AnubisValue, mut xlo: AnubisValue, mut xhi: AnubisValue, mut nodes: AnubisValue, mut next: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut n = anb_cert_exp_int(node.index_get(AnubisValue::Int(2)));
    if anubis_cmp("<", n.clone(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("range-bound-cert: negative integer powers not yet in the certified emitter; fail closed".to_string()));
    }
    let mut exptok = anb_ast_to_text(node.index_get(AnubisValue::Int(2)));
    let mut c = anb_cert_eval(node.index_get(AnubisValue::Int(1)), xlo.clone(), xhi.clone(), nodes.clone(), next.clone());
    let mut id = c.field_get("next");
    if anubis_cmp("==", n.clone(), AnubisValue::Int(0)).as_bool() {
        let mut out_lo = anb_rat_one();
        let mut out_hi = anb_rat_one();
        let mut line = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("node ".to_string()), anubis_str(id.clone())), anubis_mk_str(" powZero children[".to_string())), anubis_str(c.field_get("id"))), anubis_mk_str("] out[".to_string())), anb_cert_pair(out_lo.clone(), out_hi.clone())), anubis_mk_str("] n 0 name ".to_string())), exptok.clone());
        return AnubisValue::Struct { ty: "CE".to_string(), fields: vec![("lo".to_string(), out_lo.clone()), ("hi".to_string(), out_hi.clone()), ("id".to_string(), anubis_field_require_int(id.clone(), "id")), ("nodes".to_string(), anb_push_str(c.field_get("nodes"), line.clone())), ("next".to_string(), anubis_field_require_int(anubis_add(id.clone(), AnubisValue::Int(1)), "next"))] };
    }
    let mut flo = anb_rat_zero();
    let mut fhi = anb_rat_zero();
    let mut op = anubis_mk_str("powOddPos".to_string());
    if anubis_cmp("==", anubis_mod(n.clone(), AnubisValue::Int(2)), AnubisValue::Int(0)).as_bool() {
        op = anubis_mk_str("powEvenPos".to_string());
        flo = anb_rat_pow(anb_rat_mig(c.field_get("lo"), c.field_get("hi")), n.clone());
        fhi = anb_rat_pow(anb_rat_mag(c.field_get("lo"), c.field_get("hi")), n.clone());
    } else {
        flo = anb_rat_pow(c.field_get("lo"), n.clone());
        fhi = anb_rat_pow(c.field_get("hi"), n.clone());
    }
    let mut out_lo = anb_cert_pad_lo(flo.clone());
    let mut out_hi = anb_cert_pad_hi(fhi.clone());
    let mut line = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("node ".to_string()), anubis_str(id.clone())), anubis_mk_str(" ".to_string())), op.clone()), anubis_mk_str(" children[".to_string())), anubis_str(c.field_get("id"))), anubis_mk_str("] out[".to_string())), anb_cert_pair(out_lo.clone(), out_hi.clone())), anubis_mk_str("] f[".to_string())), anb_cert_pair(flo.clone(), fhi.clone())), anubis_mk_str("] n ".to_string())), anubis_str(n.clone())), anubis_mk_str(" name ".to_string())), exptok.clone());
    return AnubisValue::Struct { ty: "CE".to_string(), fields: vec![("lo".to_string(), out_lo.clone()), ("hi".to_string(), out_hi.clone()), ("id".to_string(), anubis_field_require_int(id.clone(), "id")), ("nodes".to_string(), anb_push_str(c.field_get("nodes"), line.clone())), ("next".to_string(), anubis_field_require_int(anubis_add(id.clone(), AnubisValue::Int(1)), "next"))] };
    AnubisValue::Int(0)
}

fn anb_cert_parse_rat(mut s: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp(">", (s.clone()).len_val(), AnubisValue::Int(0))).as_bool() && (anubis_cmp("==", (s.clone()).index_get(AnubisValue::Int(0)), anubis_mk_str("-".to_string()))).as_bool()).as_bool() {
        let mut rest = anubis_mk_str("".to_string());
        let mut i = AnubisValue::Int(1);
        while anubis_cmp("<", i.clone(), (s.clone()).len_val()).as_bool() {
            rest = anubis_add(rest.clone(), (s.clone()).index_get(i.clone()));
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        return anb_rat_neg(anb_rat_from_num_text(rest.clone()));
    }
    return anb_rat_from_num_text(s.clone());
    AnubisValue::Int(0)
}

fn anb_run_range_bound_cert(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp("!=", (argv.clone()).len_val(), AnubisValue::Int(4))).as_bool() && (anubis_cmp("!=", (argv.clone()).len_val(), AnubisValue::Int(6))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("range-bound-cert requires <expr> <lo> <hi> [<evaluator-id> <request-commit>]".to_string()));
    }
    let mut source = argv.index_get(AnubisValue::Int(1));
    let mut xlo = anb_cert_parse_rat(argv.index_get(AnubisValue::Int(2)));
    let mut xhi = anb_cert_parse_rat(argv.index_get(AnubisValue::Int(3)));
    if anubis_cmp(">", anb_rat_cmp(xlo.clone(), xhi.clone()), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("range-bound-cert requires lo <= hi".to_string()));
    }
    let mut exe_id = anubis_mk_str("".to_string());
    let mut req_commit = anubis_mk_str("".to_string());
    if anubis_cmp("==", (argv.clone()).len_val(), AnubisValue::Int(6)).as_bool() {
        exe_id = argv.index_get(AnubisValue::Int(4));
        req_commit = argv.index_get(AnubisValue::Int(5));
    }
    let mut f = anb_simplify_bound(anb_parse_ast(source.clone()));
    let mut vars = anb_collect_vars(f.clone(), anubis_map_lit(vec![]));
    for mut nm in anubis_iter(vars.clone()) {
        if anubis_cmp("!=", nm.clone(), anubis_mk_str("x".to_string())).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_mk_str("range-bound-cert: unknown identifier '".to_string()), nm.clone()), anubis_mk_str("'; only x is bound".to_string())));
        }
    }
    let mut ce = anb_cert_eval(f.clone(), xlo.clone(), xhi.clone(), anubis_mk_list(vec![]), AnubisValue::Int(0));
    println!("{}", anubis_mk_str("jackal-eval-cert v2".to_string()).display_string());
    println!("{}", anubis_mk_str("model jackal-iv-model-v1".to_string()).display_string());
    println!("{}", anubis_add(anubis_mk_str("exe ".to_string()), exe_id.clone()).display_string());
    println!("{}", anubis_mk_str("status bounded".to_string()).display_string());
    println!("{}", anubis_add(anubis_mk_str("expr ".to_string()), anb_ast_sexp(f.clone())).display_string());
    println!("{}", anubis_add(anubis_mk_str("source ".to_string()), req_commit.clone()).display_string());
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_mk_str("input ".to_string()), anb_rat_to_text(xlo.clone())), anubis_mk_str(" ".to_string())), anb_rat_to_text(xhi.clone())).display_string());
    println!("{}", anubis_add(anubis_mk_str("root ".to_string()), anubis_str(ce.field_get("id"))).display_string());
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_mk_str("output ".to_string()), anb_rat_to_text(ce.field_get("lo"))), anubis_mk_str(" ".to_string())), anb_rat_to_text(ce.field_get("hi"))).display_string());
    for mut line in anubis_iter(ce.field_get("nodes")) {
        println!("{}", line.clone().display_string());
    }
    println!("{}", anubis_mk_str("end".to_string()).display_string());
    AnubisValue::Int(0)
}

fn anb_adaptive_eval(mut source: AnubisValue, mut at: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_evaluate_expression(source.clone(), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), at.clone())]));
    AnubisValue::Int(0)
}

fn anb_adaptive_step(mut source: AnubisValue, mut a: AnubisValue, mut b: AnubisValue, mut fa: AnubisValue, mut fm: AnubisValue, mut fb: AnubisValue, mut whole: AnubisValue, mut tol: AnubisValue, mut depth: AnubisValue, mut evals: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp(">", evals.clone(), AnubisValue::Int(100000)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("integrate-adaptive: evaluation budget (100000) exhausted before reaching tolerance; fail closed rather than print unearned confidence".to_string()));
    }
    if anubis_cmp(">", depth.clone(), AnubisValue::Int(48)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("integrate-adaptive: subdivision depth (48) exhausted before reaching tolerance; integrand structure is below resolvable scale; fail closed".to_string()));
    }
    let mut m = anubis_div(anubis_add(a.clone(), b.clone()), AnubisValue::Float(2f64));
    if AnubisValue::Bool((anubis_cmp("<=", m.clone(), a.clone())).as_bool() || (anubis_cmp(">=", m.clone(), b.clone())).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("integrate-adaptive: cannot subdivide below float64 resolution while still unconverged; fail closed".to_string()));
    }
    let mut lm = anubis_div(anubis_add(a.clone(), m.clone()), AnubisValue::Float(2f64));
    let mut rm = anubis_div(anubis_add(m.clone(), b.clone()), AnubisValue::Float(2f64));
    let mut flm = anb_adaptive_eval(source.clone(), lm.clone());
    let mut frm = anb_adaptive_eval(source.clone(), rm.clone());
    let mut left = anubis_div(anubis_mul(anubis_add(anubis_add(fa.clone(), anubis_mul(AnubisValue::Float(4f64), flm.clone())), fm.clone()), anubis_sub(m.clone(), a.clone())), AnubisValue::Float(6f64));
    let mut right = anubis_div(anubis_mul(anubis_add(anubis_add(fm.clone(), anubis_mul(AnubisValue::Float(4f64), frm.clone())), fb.clone()), anubis_sub(b.clone(), m.clone())), AnubisValue::Float(6f64));
    let mut split = anubis_add(left.clone(), right.clone());
    let mut delta = anubis_sub(split.clone(), whole.clone());
    if anubis_cmp("<=", anubis_abs(delta.clone()), anubis_mul(AnubisValue::Float(15f64), tol.clone())).as_bool() {
        return AnubisValue::Struct { ty: "AdaptiveResult".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(anubis_add(split.clone(), anubis_div(delta.clone(), AnubisValue::Float(15f64))), "value")), ("error".to_string(), anubis_field_coerce_float(anubis_div(anubis_abs(delta.clone()), AnubisValue::Float(15f64)), "error")), ("evals".to_string(), anubis_field_require_int(anubis_add(evals.clone(), AnubisValue::Int(2)), "evals"))] };
    }
    let mut first = anb_adaptive_step(source.clone(), a.clone(), m.clone(), fa.clone(), flm.clone(), fm.clone(), left.clone(), anubis_div(tol.clone(), AnubisValue::Float(2f64)), anubis_add(depth.clone(), AnubisValue::Int(1)), anubis_add(evals.clone(), AnubisValue::Int(2)));
    let mut second = anb_adaptive_step(source.clone(), m.clone(), b.clone(), fm.clone(), frm.clone(), fb.clone(), right.clone(), anubis_div(tol.clone(), AnubisValue::Float(2f64)), anubis_add(depth.clone(), AnubisValue::Int(1)), first.field_get("evals"));
    return AnubisValue::Struct { ty: "AdaptiveResult".to_string(), fields: vec![("value".to_string(), anubis_field_coerce_float(anubis_add(first.field_get("value"), second.field_get("value")), "value")), ("error".to_string(), anubis_field_coerce_float(anubis_add(first.field_get("error"), second.field_get("error")), "error")), ("evals".to_string(), anubis_field_require_int(second.field_get("evals"), "evals"))] };
    AnubisValue::Int(0)
}

fn anb_iv_bad(mut why: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(false)), ("lo".to_string(), anubis_field_coerce_float(AnubisValue::Float(0f64), "lo")), ("hi".to_string(), anubis_field_coerce_float(AnubisValue::Float(0f64), "hi")), ("why".to_string(), why.clone())] };
    AnubisValue::Int(0)
}

fn anb_iv_exact(mut v: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(v.clone(), "lo")), ("hi".to_string(), anubis_field_coerce_float(v.clone(), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    AnubisValue::Int(0)
}

fn anb_iv_out(mut lo: AnubisValue, mut hi: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp("!=", lo.clone(), lo.clone())).as_bool() || (anubis_cmp("!=", hi.clone(), hi.clone())).as_bool()).as_bool() {
        return anb_iv_bad(anubis_mk_str("non-finite value in interval arithmetic".to_string()));
    }
    if AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((anubis_cmp(">", lo.clone(), AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64))).as_bool() || (anubis_cmp("<", lo.clone(), anubis_neg(AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64)))).as_bool())).as_bool() || (anubis_cmp(">", hi.clone(), AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64))).as_bool())).as_bool() || (anubis_cmp("<", hi.clone(), anubis_neg(AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64)))).as_bool()).as_bool() {
        return anb_iv_bad(anubis_mk_str("interval endpoint overflow".to_string()));
    }
    let mut padded_lo = anubis_sub(lo.clone(), anubis_add(anubis_mul(anubis_abs(lo.clone()), AnubisValue::Float(0.000000000000001f64)), AnubisValue::Float(0.000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001f64)));
    let mut padded_hi = anubis_add(hi.clone(), anubis_add(anubis_mul(anubis_abs(hi.clone()), AnubisValue::Float(0.000000000000001f64)), AnubisValue::Float(0.000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001f64)));
    if AnubisValue::Bool((anubis_cmp("<", padded_lo.clone(), anubis_neg(AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64)))).as_bool() || (anubis_cmp(">", padded_hi.clone(), AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64))).as_bool()).as_bool() {
        return anb_iv_bad(anubis_mk_str("interval endpoint overflow".to_string()));
    }
    return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(padded_lo.clone(), "lo")), ("hi".to_string(), anubis_field_coerce_float(padded_hi.clone(), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    AnubisValue::Int(0)
}

fn anb_iv_add(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if AnubisValue::Bool(!(b.field_get("ok")).as_bool()).as_bool() {
        return b.clone();
    }
    return anb_iv_out(anubis_add(a.field_get("lo"), b.field_get("lo")), anubis_add(a.field_get("hi"), b.field_get("hi")));
    AnubisValue::Int(0)
}

fn anb_iv_sub(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if AnubisValue::Bool(!(b.field_get("ok")).as_bool()).as_bool() {
        return b.clone();
    }
    return anb_iv_out(anubis_sub(a.field_get("lo"), b.field_get("hi")), anubis_sub(a.field_get("hi"), b.field_get("lo")));
    AnubisValue::Int(0)
}

fn anb_iv_neg(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(anubis_neg(a.field_get("hi")), "lo")), ("hi".to_string(), anubis_field_coerce_float(anubis_neg(a.field_get("lo")), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    AnubisValue::Int(0)
}

fn anb_iv_mul(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if AnubisValue::Bool(!(b.field_get("ok")).as_bool()).as_bool() {
        return b.clone();
    }
    let mut p1 = anubis_mul(a.field_get("lo"), b.field_get("lo"));
    let mut p2 = anubis_mul(a.field_get("lo"), b.field_get("hi"));
    let mut p3 = anubis_mul(a.field_get("hi"), b.field_get("lo"));
    let mut p4 = anubis_mul(a.field_get("hi"), b.field_get("hi"));
    return anb_iv_out(anubis_min(vec![anubis_min(vec![p1.clone(), p2.clone()]), anubis_min(vec![p3.clone(), p4.clone()])]), anubis_max(vec![anubis_max(vec![p1.clone(), p2.clone()]), anubis_max(vec![p3.clone(), p4.clone()])]));
    AnubisValue::Int(0)
}

fn anb_iv_div(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if AnubisValue::Bool(!(b.field_get("ok")).as_bool()).as_bool() {
        return b.clone();
    }
    if AnubisValue::Bool((anubis_cmp("<=", b.field_get("lo"), AnubisValue::Float(0f64))).as_bool() && (anubis_cmp(">=", b.field_get("hi"), AnubisValue::Float(0f64))).as_bool()).as_bool() {
        return anb_iv_bad(anubis_mk_str("division by an interval containing zero".to_string()));
    }
    let mut q1 = anubis_div(a.field_get("lo"), b.field_get("lo"));
    let mut q2 = anubis_div(a.field_get("lo"), b.field_get("hi"));
    let mut q3 = anubis_div(a.field_get("hi"), b.field_get("lo"));
    let mut q4 = anubis_div(a.field_get("hi"), b.field_get("hi"));
    return anb_iv_out(anubis_min(vec![anubis_min(vec![q1.clone(), q2.clone()]), anubis_min(vec![q3.clone(), q4.clone()])]), anubis_max(vec![anubis_max(vec![q1.clone(), q2.clone()]), anubis_max(vec![q3.clone(), q4.clone()])]));
    AnubisValue::Int(0)
}

fn anb_iv_abs(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if anubis_cmp(">=", a.field_get("lo"), AnubisValue::Float(0f64)).as_bool() {
        return a.clone();
    }
    if anubis_cmp("<=", a.field_get("hi"), AnubisValue::Float(0f64)).as_bool() {
        return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(anubis_neg(a.field_get("hi")), "lo")), ("hi".to_string(), anubis_field_coerce_float(anubis_neg(a.field_get("lo")), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    }
    return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(AnubisValue::Float(0f64), "lo")), ("hi".to_string(), anubis_field_coerce_float(anubis_max(vec![anubis_neg(a.field_get("lo")), a.field_get("hi")]), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    AnubisValue::Int(0)
}

fn anb_iv_mag(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_max(vec![anubis_abs(a.field_get("lo")), anubis_abs(a.field_get("hi"))]);
    AnubisValue::Int(0)
}

fn anb_iv_mig(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp("<=", a.field_get("lo"), AnubisValue::Float(0f64))).as_bool() && (anubis_cmp(">=", a.field_get("hi"), AnubisValue::Float(0f64))).as_bool()).as_bool() {
        return AnubisValue::Float(0f64);
    }
    return anubis_min(vec![anubis_abs(a.field_get("lo")), anubis_abs(a.field_get("hi"))]);
    AnubisValue::Int(0)
}

fn anb_iv_pow_int(mut a: AnubisValue, mut n: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if anubis_cmp("==", n.clone(), AnubisValue::Int(0)).as_bool() {
        return anb_iv_exact(AnubisValue::Float(1f64));
    }
    let mut m = n.clone();
    let mut invert = AnubisValue::Bool(false);
    if anubis_cmp("<", m.clone(), AnubisValue::Int(0)).as_bool() {
        invert = AnubisValue::Bool(true);
        m = anubis_neg(m.clone());
    }
    let mut fm = anubis_add(AnubisValue::Float(0f64), m.clone());
    let mut core = anb_iv_exact(AnubisValue::Float(0f64));
    if anubis_cmp("==", anubis_mod(m.clone(), AnubisValue::Int(2)), AnubisValue::Int(0)).as_bool() {
        core = anb_iv_out(anubis_pow(anb_iv_mig(a.clone()), fm.clone()), anubis_pow(anb_iv_mag(a.clone()), fm.clone()));
    } else {
        core = anb_iv_out(anubis_pow(a.field_get("lo"), fm.clone()), anubis_pow(a.field_get("hi"), fm.clone()));
    }
    if AnubisValue::Bool(!(core.field_get("ok")).as_bool()).as_bool() {
        return anb_iv_bad(anubis_mk_str("overflow in x^n over the interval".to_string()));
    }
    if invert.clone().as_bool() {
        return anb_iv_div(anb_iv_exact(AnubisValue::Float(1f64)), core.clone());
    }
    return core.clone();
    AnubisValue::Int(0)
}

fn anb_iv_pow_general(mut b: AnubisValue, mut e: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(b.field_get("ok")).as_bool()).as_bool() {
        return b.clone();
    }
    if AnubisValue::Bool(!(e.field_get("ok")).as_bool()).as_bool() {
        return e.clone();
    }
    if anubis_cmp("<=", b.field_get("lo"), AnubisValue::Float(0f64)).as_bool() {
        return anb_iv_bad(anubis_mk_str("x^y with non-integer or interval exponent requires a certifiably positive base".to_string()));
    }
    let mut lnb = anb_iv_ln(b.clone());
    let mut prod = anb_iv_mul(e.clone(), lnb.clone());
    return anb_iv_exp(prod.clone());
    AnubisValue::Int(0)
}

fn anb_iv_sqrt(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if anubis_cmp("<", a.field_get("lo"), AnubisValue::Float(0f64)).as_bool() {
        return anb_iv_bad(anubis_mk_str("sqrt over an interval extending below zero".to_string()));
    }
    let mut out = anb_iv_out(anubis_sqrt(a.field_get("lo")), anubis_sqrt(a.field_get("hi")));
    if AnubisValue::Bool(!(out.field_get("ok")).as_bool()).as_bool() {
        return out.clone();
    }
    let mut lo = out.field_get("lo");
    if anubis_cmp("<", lo.clone(), AnubisValue::Float(0f64)).as_bool() {
        lo = AnubisValue::Float(0f64);
    }
    return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(lo.clone(), "lo")), ("hi".to_string(), anubis_field_coerce_float(out.field_get("hi"), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    AnubisValue::Int(0)
}

fn anb_iv_cbrt(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    return anb_iv_out(anubis_cbrt(a.field_get("lo")), anubis_cbrt(a.field_get("hi")));
    AnubisValue::Int(0)
}

fn anb_iv_exp(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    return anb_iv_out(anubis_exp(a.field_get("lo")), anubis_exp(a.field_get("hi")));
    AnubisValue::Int(0)
}

fn anb_iv_ln(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if anubis_cmp("<=", a.field_get("lo"), AnubisValue::Float(0f64)).as_bool() {
        return anb_iv_bad(anubis_mk_str("ln over an interval touching x <= 0".to_string()));
    }
    return anb_iv_out(anubis_ln(a.field_get("lo")), anubis_ln(a.field_get("hi")));
    AnubisValue::Int(0)
}

fn anb_iv_log10(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if anubis_cmp("<=", a.field_get("lo"), AnubisValue::Float(0f64)).as_bool() {
        return anb_iv_bad(anubis_mk_str("log10 over an interval touching x <= 0".to_string()));
    }
    return anb_iv_out(anubis_log10(a.field_get("lo")), anubis_log10(a.field_get("hi")));
    AnubisValue::Int(0)
}

fn anb_iv_log2(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if anubis_cmp("<=", a.field_get("lo"), AnubisValue::Float(0f64)).as_bool() {
        return anb_iv_bad(anubis_mk_str("log2 over an interval touching x <= 0".to_string()));
    }
    return anb_iv_out(anubis_log2(a.field_get("lo")), anubis_log2(a.field_get("hi")));
    AnubisValue::Int(0)
}

fn anb_crit_in(mut lo: AnubisValue, mut hi: AnubisValue, mut offset: AnubisValue, mut period: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut slack = anubis_add(anubis_mul(anubis_add(anubis_abs(lo.clone()), anubis_abs(hi.clone())), AnubisValue::Float(0.000000000001f64)), AnubisValue::Float(0.000000000001f64));
    let mut k = anubis_add(AnubisValue::Float(0f64), anubis_floor(anubis_div(anubis_sub(lo.clone(), offset.clone()), period.clone())));
    k = anubis_sub(k.clone(), AnubisValue::Float(1f64));
    let mut step = AnubisValue::Float(0f64);
    while anubis_cmp("<", step.clone(), AnubisValue::Float(5f64)).as_bool() {
        let mut cand = anubis_add(offset.clone(), anubis_mul(anubis_add(k.clone(), step.clone()), period.clone()));
        if AnubisValue::Bool((anubis_cmp(">=", cand.clone(), anubis_sub(lo.clone(), slack.clone()))).as_bool() && (anubis_cmp("<=", cand.clone(), anubis_add(hi.clone(), slack.clone()))).as_bool()).as_bool() {
            return AnubisValue::Bool(true);
        }
        step = anubis_add(step.clone(), AnubisValue::Float(1f64));
    }
    return AnubisValue::Bool(false);
    AnubisValue::Int(0)
}

fn anb_iv_sin(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    let mut twopi = AnubisValue::Float(6.283185307179586f64);
    if anubis_cmp(">=", anubis_sub(a.field_get("hi"), a.field_get("lo")), twopi.clone()).as_bool() {
        return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(anubis_neg(AnubisValue::Float(1f64)), "lo")), ("hi".to_string(), anubis_field_coerce_float(AnubisValue::Float(1f64), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    }
    let mut s1 = anubis_sin(a.field_get("lo"));
    let mut s2 = anubis_sin(a.field_get("hi"));
    let mut out = anb_iv_out(anubis_min(vec![s1.clone(), s2.clone()]), anubis_max(vec![s1.clone(), s2.clone()]));
    if AnubisValue::Bool(!(out.field_get("ok")).as_bool()).as_bool() {
        return out.clone();
    }
    let mut lo = out.field_get("lo");
    let mut hi = out.field_get("hi");
    if anb_crit_in(a.field_get("lo"), a.field_get("hi"), AnubisValue::Float(1.5707963267948966f64), twopi.clone()).as_bool() {
        hi = AnubisValue::Float(1f64);
    }
    if anb_crit_in(a.field_get("lo"), a.field_get("hi"), anubis_neg(AnubisValue::Float(1.5707963267948966f64)), twopi.clone()).as_bool() {
        lo = anubis_neg(AnubisValue::Float(1f64));
    }
    if anubis_cmp("<", lo.clone(), anubis_neg(AnubisValue::Float(1f64))).as_bool() {
        lo = anubis_neg(AnubisValue::Float(1f64));
    }
    if anubis_cmp(">", hi.clone(), AnubisValue::Float(1f64)).as_bool() {
        hi = AnubisValue::Float(1f64);
    }
    return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(lo.clone(), "lo")), ("hi".to_string(), anubis_field_coerce_float(hi.clone(), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    AnubisValue::Int(0)
}

fn anb_iv_cos(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    let mut twopi = AnubisValue::Float(6.283185307179586f64);
    if anubis_cmp(">=", anubis_sub(a.field_get("hi"), a.field_get("lo")), twopi.clone()).as_bool() {
        return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(anubis_neg(AnubisValue::Float(1f64)), "lo")), ("hi".to_string(), anubis_field_coerce_float(AnubisValue::Float(1f64), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    }
    let mut s1 = anubis_cos(a.field_get("lo"));
    let mut s2 = anubis_cos(a.field_get("hi"));
    let mut out = anb_iv_out(anubis_min(vec![s1.clone(), s2.clone()]), anubis_max(vec![s1.clone(), s2.clone()]));
    if AnubisValue::Bool(!(out.field_get("ok")).as_bool()).as_bool() {
        return out.clone();
    }
    let mut lo = out.field_get("lo");
    let mut hi = out.field_get("hi");
    if anb_crit_in(a.field_get("lo"), a.field_get("hi"), AnubisValue::Float(0f64), twopi.clone()).as_bool() {
        hi = AnubisValue::Float(1f64);
    }
    if anb_crit_in(a.field_get("lo"), a.field_get("hi"), AnubisValue::Float(3.141592653589793f64), twopi.clone()).as_bool() {
        lo = anubis_neg(AnubisValue::Float(1f64));
    }
    if anubis_cmp("<", lo.clone(), anubis_neg(AnubisValue::Float(1f64))).as_bool() {
        lo = anubis_neg(AnubisValue::Float(1f64));
    }
    if anubis_cmp(">", hi.clone(), AnubisValue::Float(1f64)).as_bool() {
        hi = AnubisValue::Float(1f64);
    }
    return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(lo.clone(), "lo")), ("hi".to_string(), anubis_field_coerce_float(hi.clone(), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    AnubisValue::Int(0)
}

fn anb_iv_tan(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    let mut period = AnubisValue::Float(3.141592653589793f64);
    if anubis_cmp(">=", anubis_sub(a.field_get("hi"), a.field_get("lo")), period.clone()).as_bool() {
        return anb_iv_bad(anubis_mk_str("tan over an interval containing a pole".to_string()));
    }
    if anb_crit_in(a.field_get("lo"), a.field_get("hi"), AnubisValue::Float(1.5707963267948966f64), period.clone()).as_bool() {
        return anb_iv_bad(anubis_mk_str("tan over an interval that may contain a pole".to_string()));
    }
    return anb_iv_out(anubis_tan(a.field_get("lo")), anubis_tan(a.field_get("hi")));
    AnubisValue::Int(0)
}

fn anb_iv_asin(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if AnubisValue::Bool((anubis_cmp("<", a.field_get("lo"), anubis_neg(AnubisValue::Float(1f64)))).as_bool() || (anubis_cmp(">", a.field_get("hi"), AnubisValue::Float(1f64))).as_bool()).as_bool() {
        return anb_iv_bad(anubis_mk_str("asin over an interval not certifiably within [-1,1]".to_string()));
    }
    return anb_iv_out(anubis_asin(a.field_get("lo")), anubis_asin(a.field_get("hi")));
    AnubisValue::Int(0)
}

fn anb_iv_acos(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if AnubisValue::Bool((anubis_cmp("<", a.field_get("lo"), anubis_neg(AnubisValue::Float(1f64)))).as_bool() || (anubis_cmp(">", a.field_get("hi"), AnubisValue::Float(1f64))).as_bool()).as_bool() {
        return anb_iv_bad(anubis_mk_str("acos over an interval not certifiably within [-1,1]".to_string()));
    }
    return anb_iv_out(anubis_acos(a.field_get("hi")), anubis_acos(a.field_get("lo")));
    AnubisValue::Int(0)
}

fn anb_iv_atan(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    return anb_iv_out(anubis_atan(a.field_get("lo")), anubis_atan(a.field_get("hi")));
    AnubisValue::Int(0)
}

fn anb_iv_floor_scalar(mut v: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp(">=", v.clone(), AnubisValue::Float(9007199254740992f64))).as_bool() || (anubis_cmp("<=", v.clone(), anubis_neg(AnubisValue::Float(9007199254740992f64)))).as_bool()).as_bool() {
        return v.clone();
    }
    return anubis_add(AnubisValue::Float(0f64), anubis_floor(v.clone()));
    AnubisValue::Int(0)
}

fn anb_iv_ceil_scalar(mut v: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp(">=", v.clone(), AnubisValue::Float(9007199254740992f64))).as_bool() || (anubis_cmp("<=", v.clone(), anubis_neg(AnubisValue::Float(9007199254740992f64)))).as_bool()).as_bool() {
        return v.clone();
    }
    return anubis_add(AnubisValue::Float(0f64), anubis_ceil(v.clone()));
    AnubisValue::Int(0)
}

fn anb_iv_round_scalar(mut v: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp(">=", v.clone(), AnubisValue::Float(9007199254740992f64))).as_bool() || (anubis_cmp("<=", v.clone(), anubis_neg(AnubisValue::Float(9007199254740992f64)))).as_bool()).as_bool() {
        return v.clone();
    }
    return anubis_add(AnubisValue::Float(0f64), anubis_round(v.clone()));
    AnubisValue::Int(0)
}

fn anb_iv_trunc_scalar(mut v: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp(">=", v.clone(), AnubisValue::Float(9007199254740992f64))).as_bool() || (anubis_cmp("<=", v.clone(), anubis_neg(AnubisValue::Float(9007199254740992f64)))).as_bool()).as_bool() {
        return v.clone();
    }
    return anubis_add(AnubisValue::Float(0f64), anubis_trunc(v.clone()));
    AnubisValue::Int(0)
}

fn anb_iv_hypot(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if AnubisValue::Bool(!(b.field_get("ok")).as_bool()).as_bool() {
        return b.clone();
    }
    return anb_iv_out(anubis_hypot(anb_iv_mig(a.clone()), anb_iv_mig(b.clone())), anubis_hypot(anb_iv_mag(a.clone()), anb_iv_mag(b.clone())));
    AnubisValue::Int(0)
}

fn anb_iv_atan2(mut y: AnubisValue, mut x: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(y.field_get("ok")).as_bool()).as_bool() {
        return y.clone();
    }
    if AnubisValue::Bool(!(x.field_get("ok")).as_bool()).as_bool() {
        return x.clone();
    }
    if anubis_cmp("<=", x.field_get("lo"), AnubisValue::Float(0f64)).as_bool() {
        return anb_iv_bad(anubis_mk_str("atan2 is certified only over a strictly positive x-interval in this lane".to_string()));
    }
    return anb_iv_atan(anb_iv_div(y.clone(), x.clone()));
    AnubisValue::Int(0)
}

fn anb_iv_min(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if AnubisValue::Bool(!(b.field_get("ok")).as_bool()).as_bool() {
        return b.clone();
    }
    return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(anubis_min(vec![a.field_get("lo"), b.field_get("lo")]), "lo")), ("hi".to_string(), anubis_field_coerce_float(anubis_min(vec![a.field_get("hi"), b.field_get("hi")]), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    AnubisValue::Int(0)
}

fn anb_iv_max(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool(!(a.field_get("ok")).as_bool()).as_bool() {
        return a.clone();
    }
    if AnubisValue::Bool(!(b.field_get("ok")).as_bool()).as_bool() {
        return b.clone();
    }
    return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(anubis_max(vec![a.field_get("lo"), b.field_get("lo")]), "lo")), ("hi".to_string(), anubis_field_coerce_float(anubis_max(vec![a.field_get("hi"), b.field_get("hi")]), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    AnubisValue::Int(0)
}

fn anb_iv_from_literal(mut v: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", v.clone(), anubis_trunc(v.clone()))).as_bool() && (anubis_cmp("<", v.clone(), AnubisValue::Float(9007199254740992f64))).as_bool())).as_bool() && (anubis_cmp(">", v.clone(), anubis_neg(AnubisValue::Float(9007199254740992f64)))).as_bool()).as_bool() {
        return anb_iv_exact(v.clone());
    }
    return anb_iv_out(v.clone(), v.clone());
    AnubisValue::Int(0)
}

fn anb_ieval(mut node: AnubisValue, mut xlo: AnubisValue, mut xhi: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string())).as_bool() {
        return anb_iv_from_literal(node.index_get(AnubisValue::Int(1)));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string())).as_bool() {
        return anb_iv_from_literal(anb_constant_value(node.index_get(AnubisValue::Int(1))));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string())).as_bool() {
        let mut var_name = node.index_get(AnubisValue::Int(1));
        if anubis_cmp("==", var_name.clone(), anubis_mk_str("x".to_string())).as_bool() {
            return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(xlo.clone(), "lo")), ("hi".to_string(), anubis_field_coerce_float(xhi.clone(), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
        }
        return anb_iv_bad(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("unknown identifier '".to_string())), var_name.clone()), anubis_mk_str("' (only x is bound)".to_string())));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        let mut inner = anb_ieval(node.index_get(AnubisValue::Int(1)), xlo.clone(), xhi.clone());
        return anb_iv_neg(inner.clone());
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("call".to_string())).as_bool() {
        let mut name = node.index_get(AnubisValue::Int(1));
        let mut arguments = node.index_get(AnubisValue::Int(2));
        let mut first = anb_ieval(arguments.index_get(AnubisValue::Int(0)), xlo.clone(), xhi.clone());
        if anubis_cmp("==", (arguments.clone()).len_val(), AnubisValue::Int(2)).as_bool() {
            let mut second = anb_ieval(arguments.index_get(AnubisValue::Int(1)), xlo.clone(), xhi.clone());
            if anubis_cmp("==", name.clone(), anubis_mk_str("hypot".to_string())).as_bool() {
                return anb_iv_hypot(first.clone(), second.clone());
            }
            if anubis_cmp("==", name.clone(), anubis_mk_str("pow".to_string())).as_bool() {
                if AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((second.field_get("ok")).as_bool() && (anubis_cmp("==", second.field_get("lo"), second.field_get("hi"))).as_bool())).as_bool() && (anubis_cmp("==", second.field_get("lo"), anubis_trunc(second.field_get("lo")))).as_bool())).as_bool() && (anubis_cmp("<=", second.field_get("lo"), AnubisValue::Float(4096f64))).as_bool())).as_bool() && (anubis_cmp(">=", second.field_get("lo"), anubis_neg(AnubisValue::Float(4096f64)))).as_bool()).as_bool() {
                    return anb_iv_pow_int(first.clone(), anubis_int(second.field_get("lo")));
                }
                return anb_iv_pow_general(first.clone(), second.clone());
            }
            if anubis_cmp("==", name.clone(), anubis_mk_str("atan2".to_string())).as_bool() {
                return anb_iv_atan2(first.clone(), second.clone());
            }
            if anubis_cmp("==", name.clone(), anubis_mk_str("min".to_string())).as_bool() {
                return anb_iv_min(first.clone(), second.clone());
            }
            if anubis_cmp("==", name.clone(), anubis_mk_str("max".to_string())).as_bool() {
                return anb_iv_max(first.clone(), second.clone());
            }
            return anb_iv_bad(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("no certified interval model for '".to_string())), name.clone()), anubis_mk_str("'".to_string())));
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("sin".to_string())).as_bool() {
            return anb_iv_sin(first.clone());
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("cos".to_string())).as_bool() {
            return anb_iv_cos(first.clone());
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("tan".to_string())).as_bool() {
            return anb_iv_tan(first.clone());
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("asin".to_string())).as_bool() {
            return anb_iv_asin(first.clone());
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("acos".to_string())).as_bool() {
            return anb_iv_acos(first.clone());
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("atan".to_string())).as_bool() {
            return anb_iv_atan(first.clone());
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("sqrt".to_string())).as_bool() {
            return anb_iv_sqrt(first.clone());
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("cbrt".to_string())).as_bool() {
            return anb_iv_cbrt(first.clone());
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("ln".to_string())).as_bool() {
            return anb_iv_ln(first.clone());
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("log10".to_string())).as_bool() {
            return anb_iv_log10(first.clone());
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("log2".to_string())).as_bool() {
            return anb_iv_log2(first.clone());
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("exp".to_string())).as_bool() {
            return anb_iv_exp(first.clone());
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("abs".to_string())).as_bool() {
            return anb_iv_abs(first.clone());
        }
        if AnubisValue::Bool(!(first.field_get("ok")).as_bool()).as_bool() {
            return first.clone();
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("floor".to_string())).as_bool() {
            return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(anb_iv_floor_scalar(first.field_get("lo")), "lo")), ("hi".to_string(), anubis_field_coerce_float(anb_iv_floor_scalar(first.field_get("hi")), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("ceil".to_string())).as_bool() {
            return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(anb_iv_ceil_scalar(first.field_get("lo")), "lo")), ("hi".to_string(), anubis_field_coerce_float(anb_iv_ceil_scalar(first.field_get("hi")), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("round".to_string())).as_bool() {
            return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(anb_iv_round_scalar(first.field_get("lo")), "lo")), ("hi".to_string(), anubis_field_coerce_float(anb_iv_round_scalar(first.field_get("hi")), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
        }
        if anubis_cmp("==", name.clone(), anubis_mk_str("trunc".to_string())).as_bool() {
            return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(anb_iv_trunc_scalar(first.field_get("lo")), "lo")), ("hi".to_string(), anubis_field_coerce_float(anb_iv_trunc_scalar(first.field_get("hi")), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
        }
        return anb_iv_bad(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("no certified interval model for '".to_string())), name.clone()), anubis_mk_str("'".to_string())));
    }
    let mut left = anb_ieval(node.index_get(AnubisValue::Int(1)), xlo.clone(), xhi.clone());
    let mut right = anb_ieval(node.index_get(AnubisValue::Int(2)), xlo.clone(), xhi.clone());
    if anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string())).as_bool() {
        return anb_iv_add(left.clone(), right.clone());
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string())).as_bool() {
        return anb_iv_sub(left.clone(), right.clone());
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string())).as_bool() {
        return anb_iv_mul(left.clone(), right.clone());
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string())).as_bool() {
        return anb_iv_div(left.clone(), right.clone());
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mod".to_string())).as_bool() {
        return anb_iv_bad(anubis_mk_str("'%' has no certified interval model; fail closed".to_string()));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("pow".to_string())).as_bool() {
        if AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((right.field_get("ok")).as_bool() && (anubis_cmp("==", right.field_get("lo"), right.field_get("hi"))).as_bool())).as_bool() && (anubis_cmp("==", right.field_get("lo"), anubis_trunc(right.field_get("lo")))).as_bool())).as_bool() && (anubis_cmp("<=", right.field_get("lo"), AnubisValue::Float(4096f64))).as_bool())).as_bool() && (anubis_cmp(">=", right.field_get("lo"), anubis_neg(AnubisValue::Float(4096f64)))).as_bool()).as_bool() {
            return anb_iv_pow_int(left.clone(), anubis_int(right.field_get("lo")));
        }
        return anb_iv_pow_general(left.clone(), right.clone());
    }
    return anb_iv_bad(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("internal error: unknown AST node '".to_string())), tag.clone()), anubis_mk_str("'".to_string())));
    AnubisValue::Int(0)
}

fn anb_ast_size(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string()))).as_bool()).as_bool() {
        return AnubisValue::Int(1);
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        return anubis_add(AnubisValue::Int(1), anb_ast_size(node.index_get(AnubisValue::Int(1))));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("call".to_string())).as_bool() {
        let mut arguments = node.index_get(AnubisValue::Int(2));
        let mut total = AnubisValue::Int(1);
        let mut i = AnubisValue::Int(0);
        while anubis_cmp("<", i.clone(), (arguments.clone()).len_val()).as_bool() {
            total = anubis_add(total.clone(), anb_ast_size(arguments.index_get(i.clone())));
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        return total.clone();
    }
    return anubis_add(anubis_add(AnubisValue::Int(1), anb_ast_size(node.index_get(AnubisValue::Int(1)))), anb_ast_size(node.index_get(AnubisValue::Int(2))));
    AnubisValue::Int(0)
}

fn anb_iv_intersect_enclosures(mut piece: AnubisValue, mut candidate: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut ilo = anubis_max(vec![piece.field_get("lo"), candidate.field_get("lo")]);
    let mut ihi = anubis_min(vec![piece.field_get("hi"), candidate.field_get("hi")]);
    if anubis_cmp(">", ilo.clone(), ihi.clone()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("integrate-bound: internal soundness invariant violated (disjoint enclosures); fail closed".to_string()));
    }
    return AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(ilo.clone(), "lo")), ("hi".to_string(), anubis_field_coerce_float(ihi.clone(), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    AnubisValue::Int(0)
}

fn anb_bound_step(mut f: AnubisValue, mut f1: AnubisValue, mut f2: AnubisValue, mut f3: AnubisValue, mut f4: AnubisValue, mut taylor_degree: AnubisValue, mut a_edge: AnubisValue, mut b_edge: AnubisValue, mut span: AnubisValue, mut tol: AnubisValue, mut depth: AnubisValue, mut nodes: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp(">", nodes.clone(), AnubisValue::Int(60000)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("integrate-bound: subdivision budget (60000 subintervals) exhausted before certifying the requested tolerance; fail closed rather than print an unearned bound (try a larger tolerance, or integrate-adaptive for a non-certified estimate)".to_string()));
    }
    let mut F = anb_ieval(f.clone(), a_edge.clone(), b_edge.clone());
    if anubis_cmp(">", depth.clone(), AnubisValue::Int(60)).as_bool() {
        if AnubisValue::Bool(!(F.field_get("ok")).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("integrate-bound: cannot certify: ".to_string())), F.field_get("why")), anubis_mk_str(" persists after 60 subdivision levels near x=".to_string())), anb_number_text(a_edge.clone())), anubis_mk_str("; the integrand is not certifiably bounded on the requested interval; fail closed".to_string())));
        }
        let _ = anubis_panic(anubis_mk_str("integrate-bound: subdivision depth (60) exhausted before certifying the requested tolerance; integrand structure is below certifiable scale; fail closed".to_string()));
    }
    let mut h = anubis_sub(b_edge.clone(), a_edge.clone());
    let mut local_tol = anubis_div(anubis_mul(tol.clone(), h.clone()), span.clone());
    let mut hI = anb_iv_out(h.clone(), h.clone());
    let mut piece = anb_iv_bad(anubis_mk_str("uncomputed".to_string()));
    let mut used_taylor = AnubisValue::Bool(false);
    if F.field_get("ok").as_bool() {
        piece = anb_iv_mul(hI.clone(), F.clone());
    }
    if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp(">=", taylor_degree.clone(), AnubisValue::Int(2))).as_bool() && (F.field_get("ok")).as_bool())).as_bool() && (piece.field_get("ok")).as_bool()).as_bool() {
        let mut m = anubis_div(anubis_add(a_edge.clone(), b_edge.clone()), AnubisValue::Float(2f64));
        let mut mI = anb_iv_out(m.clone(), m.clone());
        let mut Fm = anb_ieval(f.clone(), mI.field_get("lo"), mI.field_get("hi"));
        let mut F1 = anb_ieval(f1.clone(), a_edge.clone(), b_edge.clone());
        let mut F2 = anb_ieval(f2.clone(), a_edge.clone(), b_edge.clone());
        if AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((mI.field_get("ok")).as_bool() && (Fm.field_get("ok")).as_bool())).as_bool() && (F1.field_get("ok")).as_bool())).as_bool() && (F2.field_get("ok")).as_bool()).as_bool() {
            let mut h3 = anb_iv_mul(hI.clone(), anb_iv_mul(hI.clone(), hI.clone()));
            let mut base = anb_iv_mul(hI.clone(), Fm.clone());
            let mut tried4 = AnubisValue::Bool(false);
            if anubis_cmp(">=", taylor_degree.clone(), AnubisValue::Int(4)).as_bool() {
                let mut F2m = anb_ieval(f2.clone(), mI.field_get("lo"), mI.field_get("hi"));
                let mut F3 = anb_ieval(f3.clone(), a_edge.clone(), b_edge.clone());
                let mut F4 = anb_ieval(f4.clone(), a_edge.clone(), b_edge.clone());
                if AnubisValue::Bool((AnubisValue::Bool((F2m.field_get("ok")).as_bool() && (F3.field_get("ok")).as_bool())).as_bool() && (F4.field_get("ok")).as_bool()).as_bool() {
                    let mut h5 = anb_iv_mul(h3.clone(), anb_iv_mul(hI.clone(), hI.clone()));
                    let mut mid_term = anb_iv_div(anb_iv_mul(h3.clone(), F2m.clone()), anb_iv_exact(AnubisValue::Float(24f64)));
                    let mut rem4 = anb_iv_div(anb_iv_mul(h5.clone(), F4.clone()), anb_iv_exact(AnubisValue::Float(1920f64)));
                    if AnubisValue::Bool((mid_term.field_get("ok")).as_bool() && (rem4.field_get("ok")).as_bool()).as_bool() {
                        let mut t4 = anb_iv_add(base.clone(), anb_iv_add(mid_term.clone(), rem4.clone()));
                        if t4.field_get("ok").as_bool() {
                            piece = anb_iv_intersect_enclosures(piece.clone(), t4.clone());
                            used_taylor = AnubisValue::Bool(true);
                            tried4 = AnubisValue::Bool(true);
                        }
                    }
                }
            }
            if AnubisValue::Bool(!(tried4.clone()).as_bool()).as_bool() {
                let mut rem2 = anb_iv_div(anb_iv_mul(h3.clone(), F2.clone()), anb_iv_exact(AnubisValue::Float(24f64)));
                if rem2.field_get("ok").as_bool() {
                    let mut t2 = anb_iv_add(base.clone(), rem2.clone());
                    if t2.field_get("ok").as_bool() {
                        piece = anb_iv_intersect_enclosures(piece.clone(), t2.clone());
                        used_taylor = AnubisValue::Bool(true);
                    }
                }
            }
        }
    }
    if piece.field_get("ok").as_bool() {
        if anubis_cmp("<=", anubis_sub(piece.field_get("hi"), piece.field_get("lo")), anubis_mul(AnubisValue::Float(0.9f64), local_tol.clone())).as_bool() {
            let mut t_count = AnubisValue::Int(0);
            let mut r_count = AnubisValue::Int(0);
            if used_taylor.clone().as_bool() {
                t_count = AnubisValue::Int(1);
            } else {
                r_count = AnubisValue::Int(1);
            }
            return AnubisValue::Struct { ty: "BoundResult".to_string(), fields: vec![("lo".to_string(), anubis_field_coerce_float(piece.field_get("lo"), "lo")), ("hi".to_string(), anubis_field_coerce_float(piece.field_get("hi"), "hi")), ("nodes".to_string(), anubis_field_require_int(anubis_add(nodes.clone(), AnubisValue::Int(1)), "nodes")), ("taylored".to_string(), anubis_field_require_int(t_count.clone(), "taylored")), ("ranged".to_string(), anubis_field_require_int(r_count.clone(), "ranged"))] };
        }
    }
    let mut mid = anubis_div(anubis_add(a_edge.clone(), b_edge.clone()), AnubisValue::Float(2f64));
    if AnubisValue::Bool((anubis_cmp("<=", mid.clone(), a_edge.clone())).as_bool() || (anubis_cmp(">=", mid.clone(), b_edge.clone())).as_bool()).as_bool() {
        if AnubisValue::Bool(!(F.field_get("ok")).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("integrate-bound: cannot certify: ".to_string())), F.field_get("why")), anubis_mk_str(" persists at float64 resolution near x=".to_string())), anb_number_text(a_edge.clone())), anubis_mk_str("; the integrand is not certifiably bounded on the requested interval; fail closed".to_string())));
        }
        let _ = anubis_panic(anubis_mk_str("integrate-bound: cannot subdivide below float64 resolution while the local enclosure still exceeds tolerance; fail closed".to_string()));
    }
    let mut first = anb_bound_step(f.clone(), f1.clone(), f2.clone(), f3.clone(), f4.clone(), taylor_degree.clone(), a_edge.clone(), mid.clone(), span.clone(), tol.clone(), anubis_add(depth.clone(), AnubisValue::Int(1)), anubis_add(nodes.clone(), AnubisValue::Int(1)));
    let mut second = anb_bound_step(f.clone(), f1.clone(), f2.clone(), f3.clone(), f4.clone(), taylor_degree.clone(), mid.clone(), b_edge.clone(), span.clone(), tol.clone(), anubis_add(depth.clone(), AnubisValue::Int(1)), first.field_get("nodes"));
    let mut left_piece = AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(first.field_get("lo"), "lo")), ("hi".to_string(), anubis_field_coerce_float(first.field_get("hi"), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    let mut right_piece = AnubisValue::Struct { ty: "IBox".to_string(), fields: vec![("ok".to_string(), AnubisValue::Bool(true)), ("lo".to_string(), anubis_field_coerce_float(second.field_get("lo"), "lo")), ("hi".to_string(), anubis_field_coerce_float(second.field_get("hi"), "hi")), ("why".to_string(), anubis_mk_str("".to_string()))] };
    let mut summed = anb_iv_add(left_piece.clone(), right_piece.clone());
    if AnubisValue::Bool(!(summed.field_get("ok")).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("integrate-bound: non-finite accumulation; fail closed".to_string()));
    }
    return AnubisValue::Struct { ty: "BoundResult".to_string(), fields: vec![("lo".to_string(), anubis_field_coerce_float(summed.field_get("lo"), "lo")), ("hi".to_string(), anubis_field_coerce_float(summed.field_get("hi"), "hi")), ("nodes".to_string(), anubis_field_require_int(second.field_get("nodes"), "nodes")), ("taylored".to_string(), anubis_field_require_int(anubis_add(first.field_get("taylored"), second.field_get("taylored")), "taylored")), ("ranged".to_string(), anubis_field_require_int(anubis_add(first.field_get("ranged"), second.field_get("ranged")), "ranged"))] };
    AnubisValue::Int(0)
}

fn anb_int_make(mut neg: AnubisValue, mut mag: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anb_big_is_zero(mag.clone()).as_bool() {
        return AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), anubis_mk_list(vec![AnubisValue::Int(0)])), ("den".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)]))] };
    }
    return AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), neg.clone()), ("num".to_string(), mag.clone()), ("den".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)]))] };
    AnubisValue::Int(0)
}

fn anb_int_from_text(mut text: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", (text.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("exact-int: empty integer input; fail closed".to_string()));
    }
    let mut neg = AnubisValue::Bool(false);
    let mut start = AnubisValue::Int(0);
    if anubis_cmp("==", (text.clone()).index_get(AnubisValue::Int(0)), anubis_mk_str("-".to_string())).as_bool() {
        neg = AnubisValue::Bool(true);
        start = AnubisValue::Int(1);
    }
    let mut digits = anubis_mk_str("".to_string());
    let mut i = start.clone();
    while anubis_cmp("<", i.clone(), (text.clone()).len_val()).as_bool() {
        digits = anubis_add(digits.clone(), (text.clone()).index_get(i.clone()));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    if anubis_cmp("==", (digits.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("exact-int: sign without digits; fail closed".to_string()));
    }
    if anubis_cmp(">", (digits.clone()).len_val(), AnubisValue::Int(4096)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("exact-int: input exceeds 4096 decimal digits; fail closed (int-budget)".to_string()));
    }
    return anb_int_make(neg.clone(), anb_big_from_text(digits.clone()));
    AnubisValue::Int(0)
}

fn anb_int_to_text(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_rat_to_text(a.clone());
    AnubisValue::Int(0)
}

fn anb_int_add(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut a_neg = a.field_get("neg");
    let mut b_neg = b.field_get("neg");
    if anubis_cmp("==", a_neg.clone(), b_neg.clone()).as_bool() {
        return anb_int_make(a_neg.clone(), anb_big_add(a.field_get("num"), b.field_get("num")));
    }
    let mut comparison = anb_big_cmp(a.field_get("num"), b.field_get("num"));
    if anubis_cmp("==", comparison.clone(), AnubisValue::Int(0)).as_bool() {
        return anb_int_make(AnubisValue::Bool(false), anubis_mk_list(vec![AnubisValue::Int(0)]));
    }
    if anubis_cmp(">", comparison.clone(), AnubisValue::Int(0)).as_bool() {
        return anb_int_make(a_neg.clone(), anb_big_sub(a.field_get("num"), b.field_get("num")));
    }
    return anb_int_make(b_neg.clone(), anb_big_sub(b.field_get("num"), a.field_get("num")));
    AnubisValue::Int(0)
}

fn anb_int_sub(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_int_add(a.clone(), anb_rat_neg(b.clone()));
    AnubisValue::Int(0)
}

fn anb_int_mul(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anb_big_is_zero(a.field_get("num"))).as_bool() || (anb_big_is_zero(b.field_get("num"))).as_bool()).as_bool() {
        return anb_int_make(AnubisValue::Bool(false), anubis_mk_list(vec![AnubisValue::Int(0)]));
    }
    let mut a_neg = a.field_get("neg");
    let mut b_neg = b.field_get("neg");
    return anb_int_make(anubis_cmp("!=", a_neg.clone(), b_neg.clone()), anb_big_mul(a.field_get("num"), b.field_get("num")));
    AnubisValue::Int(0)
}

fn anb_int_cmp(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut a_neg = a.field_get("neg");
    let mut b_neg = b.field_get("neg");
    if anubis_cmp("!=", a_neg.clone(), b_neg.clone()).as_bool() {
        if a_neg.clone().as_bool() {
            return anubis_neg(AnubisValue::Int(1));
        }
        return AnubisValue::Int(1);
    }
    let mut c = anb_big_cmp(a.field_get("num"), b.field_get("num"));
    if a_neg.clone().as_bool() {
        return anubis_neg(c.clone());
    }
    return c.clone();
    AnubisValue::Int(0)
}

fn anb_int_divmod(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anb_big_is_zero(b.field_get("num")).as_bool() {
        let _ = anubis_panic(anubis_mk_str("exact division by zero; fail closed".to_string()));
    }
    let mut dm = anb_big_divmod(a.field_get("num"), b.field_get("num"));
    let mut qm = dm.field_get("quotient");
    let mut rm = dm.field_get("remainder");
    let mut a_neg = a.field_get("neg");
    let mut b_neg = b.field_get("neg");
    if AnubisValue::Bool(!(a_neg.clone()).as_bool()).as_bool() {
        return AnubisValue::Struct { ty: "IntDivmod".to_string(), fields: vec![("q".to_string(), anb_int_make(b_neg.clone(), qm.clone())), ("r".to_string(), anb_int_make(AnubisValue::Bool(false), rm.clone()))] };
    }
    if anb_big_is_zero(rm.clone()).as_bool() {
        return AnubisValue::Struct { ty: "IntDivmod".to_string(), fields: vec![("q".to_string(), anb_int_make(AnubisValue::Bool(!(b_neg.clone()).as_bool()), qm.clone())), ("r".to_string(), anb_int_make(AnubisValue::Bool(false), anubis_mk_list(vec![AnubisValue::Int(0)])))] };
    }
    return AnubisValue::Struct { ty: "IntDivmod".to_string(), fields: vec![("q".to_string(), anb_int_make(AnubisValue::Bool(!(b_neg.clone()).as_bool()), anb_big_add(qm.clone(), anubis_mk_list(vec![AnubisValue::Int(1)])))), ("r".to_string(), anb_int_make(AnubisValue::Bool(false), anb_big_sub(b.field_get("num"), rm.clone())))] };
    AnubisValue::Int(0)
}

fn anb_int_mod(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return (anb_int_divmod(a.clone(), b.clone())).field_get("r");
    AnubisValue::Int(0)
}

fn anb_int_xgcd(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut old_r = a.clone();
    let mut cur_r = b.clone();
    let mut old_u = anb_rat_one();
    let mut cur_u = anb_rat_zero();
    let mut old_v = anb_rat_zero();
    let mut cur_v = anb_rat_one();
    while AnubisValue::Bool(!(anb_big_is_zero(cur_r.field_get("num"))).as_bool()).as_bool() {
        let mut dm = anb_int_divmod(old_r.clone(), cur_r.clone());
        let mut q = dm.field_get("q");
        let mut next_r = dm.field_get("r");
        let mut next_u = anb_int_sub(old_u.clone(), anb_int_mul(q.clone(), cur_u.clone()));
        let mut next_v = anb_int_sub(old_v.clone(), anb_int_mul(q.clone(), cur_v.clone()));
        old_r = cur_r.clone();
        cur_r = next_r.clone();
        old_u = cur_u.clone();
        cur_u = next_u.clone();
        old_v = cur_v.clone();
        cur_v = next_v.clone();
    }
    if old_r.field_get("neg").as_bool() {
        return AnubisValue::Struct { ty: "Xgcd".to_string(), fields: vec![("g".to_string(), anb_rat_neg(old_r.clone())), ("u".to_string(), anb_rat_neg(old_u.clone())), ("v".to_string(), anb_rat_neg(old_v.clone()))] };
    }
    return AnubisValue::Struct { ty: "Xgcd".to_string(), fields: vec![("g".to_string(), old_r.clone()), ("u".to_string(), old_u.clone()), ("v".to_string(), old_v.clone())] };
    AnubisValue::Int(0)
}

fn anb_big_from_small(mut v: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", v.clone(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("internal error: big_from_small on a negative value; fail closed".to_string()));
    }
    let mut limbs = anubis_mk_list(vec![]);
    let mut x = v.clone();
    while anubis_cmp(">", x.clone(), AnubisValue::Int(0)).as_bool() {
        limbs.push_val(anubis_mod(x.clone(), AnubisValue::Int(1000000000)));
        x = anubis_div(x.clone(), AnubisValue::Int(1000000000));
    }
    if anubis_cmp("==", (limbs.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        limbs.push_val(AnubisValue::Int(0));
    }
    return limbs.clone();
    AnubisValue::Int(0)
}

fn anb_big_to_i64_or_neg(mut a: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", (a.clone()).len_val(), AnubisValue::Int(1)).as_bool() {
        return a.index_get(AnubisValue::Int(0));
    }
    if anubis_cmp("==", (a.clone()).len_val(), AnubisValue::Int(2)).as_bool() {
        return anubis_add(anubis_mul(a.index_get(AnubisValue::Int(1)), AnubisValue::Int(1000000000)), a.index_get(AnubisValue::Int(0)));
    }
    return anubis_neg(AnubisValue::Int(1));
    AnubisValue::Int(0)
}

fn anb_big_mod(mut a: AnubisValue, mut m: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return (anb_big_divmod(a.clone(), m.clone())).field_get("remainder");
    AnubisValue::Int(0)
}

fn anb_big_diff(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp(">=", anb_big_cmp(a.clone(), b.clone()), AnubisValue::Int(0)).as_bool() {
        return anb_big_sub(a.clone(), b.clone());
    }
    return anb_big_sub(b.clone(), a.clone());
    AnubisValue::Int(0)
}

fn anb_big_modpow(mut base: AnubisValue, mut exponent: AnubisValue, mut modulus: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", anb_big_cmp(modulus.clone(), anubis_mk_list(vec![AnubisValue::Int(1)])), AnubisValue::Int(0)).as_bool() {
        return anubis_mk_list(vec![AnubisValue::Int(0)]);
    }
    let mut result = anubis_mk_list(vec![AnubisValue::Int(1)]);
    let mut b = anb_big_mod(base.clone(), modulus.clone());
    let mut e = exponent.clone();
    while AnubisValue::Bool(!(anb_big_is_zero(e.clone())).as_bool()).as_bool() {
        if AnubisValue::Bool(!(anb_big_is_even(e.clone())).as_bool()).as_bool() {
            result = anb_big_mod(anb_big_mul(result.clone(), b.clone()), modulus.clone());
        }
        b = anb_big_mod(anb_big_mul(b.clone(), b.clone()), modulus.clone());
        e = anb_big_half(e.clone());
    }
    return result.clone();
    AnubisValue::Int(0)
}

fn anb_int_modpow(mut base: AnubisValue, mut exponent: AnubisValue, mut modulus: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if exponent.field_get("neg").as_bool() {
        let _ = anubis_panic(anubis_mk_str("mod-pow: exponent must be nonnegative; fail closed".to_string()));
    }
    if AnubisValue::Bool((modulus.field_get("neg")).as_bool() || (anb_big_is_zero(modulus.field_get("num"))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("mod-pow: modulus must be >= 1; fail closed".to_string()));
    }
    let mut b0 = anb_int_mod(base.clone(), modulus.clone());
    return anb_int_make(AnubisValue::Bool(false), anb_big_modpow(b0.field_get("num"), exponent.field_get("num"), modulus.field_get("num")));
    AnubisValue::Int(0)
}

fn anb_int_modinv(mut a: AnubisValue, mut modulus: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((modulus.field_get("neg")).as_bool() || (anubis_cmp("<", anb_big_cmp(modulus.field_get("num"), anubis_mk_list(vec![AnubisValue::Int(2)])), AnubisValue::Int(0))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("mod-inv: modulus must be >= 2; fail closed".to_string()));
    }
    let mut x = anb_int_xgcd(a.clone(), modulus.clone());
    let mut g = x.field_get("g");
    if AnubisValue::Bool((g.field_get("neg")).as_bool() || (anubis_cmp("!=", anb_big_cmp(g.field_get("num"), anubis_mk_list(vec![AnubisValue::Int(1)])), AnubisValue::Int(0))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("mod-inv: gcd(a, m) != 1, no inverse exists; fail closed (mod-inv-not-coprime)".to_string()));
    }
    return anb_int_mod(x.field_get("u"), modulus.clone());
    AnubisValue::Int(0)
}

fn anb_crt_combine(mut rs: AnubisValue, mut ms: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut n = (ms.clone()).len_val();
    if AnubisValue::Bool((anubis_cmp("<", n.clone(), AnubisValue::Int(2))).as_bool() || (anubis_cmp(">", n.clone(), AnubisValue::Int(16))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("crt requires between 2 and 16 residue/modulus pairs; fail closed (int-budget)".to_string()));
    }
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), n.clone()).as_bool() {
        let mut m = ms.index_get(i.clone());
        if AnubisValue::Bool((m.field_get("neg")).as_bool() || (anubis_cmp("<", anb_big_cmp(m.field_get("num"), anubis_mk_list(vec![AnubisValue::Int(2)])), AnubisValue::Int(0))).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("crt: each modulus must be >= 2; fail closed".to_string()));
        }
        let mut j = anubis_add(i.clone(), AnubisValue::Int(1));
        while anubis_cmp("<", j.clone(), n.clone()).as_bool() {
            let mut mj = ms.index_get(j.clone());
            if anubis_cmp("!=", anb_big_cmp(anb_big_gcd(m.field_get("num"), mj.field_get("num")), anubis_mk_list(vec![AnubisValue::Int(1)])), AnubisValue::Int(0)).as_bool() {
                let _ = anubis_panic(anubis_mk_str("crt: moduli are not pairwise coprime; fail closed (crt-not-coprime)".to_string()));
            }
            j = anubis_add(j.clone(), AnubisValue::Int(1));
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    let mut x = anb_int_mod(rs.index_get(AnubisValue::Int(0)), ms.index_get(AnubisValue::Int(0)));
    let mut acc = ms.index_get(AnubisValue::Int(0));
    i = AnubisValue::Int(1);
    while anubis_cmp("<", i.clone(), n.clone()).as_bool() {
        let mut mi = ms.index_get(i.clone());
        let mut diff = anb_int_sub(rs.index_get(i.clone()), x.clone());
        let mut inv = anb_int_modinv(acc.clone(), mi.clone());
        let mut t = anb_int_mod(anb_int_mul(diff.clone(), inv.clone()), mi.clone());
        x = anb_int_add(x.clone(), anb_int_mul(acc.clone(), t.clone()));
        acc = anb_int_mul(acc.clone(), mi.clone());
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return AnubisValue::Struct { ty: "CrtResult".to_string(), fields: vec![("x".to_string(), x.clone()), ("modulus".to_string(), acc.clone())] };
    AnubisValue::Int(0)
}

fn anb_jstr(mut s: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_add(anubis_add(anubis_mk_str("\"".to_string()), s.clone()), anubis_mk_str("\"".to_string()));
    AnubisValue::Int(0)
}

fn anb_jkv(mut key: AnubisValue, mut value_json: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_add(anubis_add(anubis_add(anubis_mk_str("\"".to_string()), key.clone()), anubis_mk_str("\":".to_string())), value_json.clone());
    AnubisValue::Int(0)
}

fn anb_cert_envelope(mut kind: AnubisValue, mut claim_json: AnubisValue, mut witness_json: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("exact-cert={\"claim\":".to_string()), claim_json.clone()), anubis_mk_str(",\"kind\":\"".to_string())), kind.clone()), anubis_mk_str("\",\"schema\":\"jackal-exact-cert-v1\",\"witness\":".to_string())), witness_json.clone()), anubis_mk_str("}".to_string()));
    AnubisValue::Int(0)
}

fn anb_cert_safe_expr(mut text: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut safe = anubis_mk_str("0123456789.eE x+-*/^()".to_string());
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (text.clone()).len_val()).as_bool() {
        if AnubisValue::Bool(!(anb_char_in(safe.clone(), (text.clone()).index_get(i.clone()))).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("exact-cert: expression contains a character outside the safe charset; fail closed (cert-charset)".to_string()));
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return text.clone();
    AnubisValue::Int(0)
}

fn anb_rat_from_frac_text(mut text: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", (text.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("exact-alg: empty rational input; fail closed".to_string()));
    }
    let mut neg = AnubisValue::Bool(false);
    let mut start = AnubisValue::Int(0);
    if anubis_cmp("==", (text.clone()).index_get(AnubisValue::Int(0)), anubis_mk_str("-".to_string())).as_bool() {
        neg = AnubisValue::Bool(true);
        start = AnubisValue::Int(1);
    }
    let mut body = anubis_mk_str("".to_string());
    let mut i = start.clone();
    while anubis_cmp("<", i.clone(), (text.clone()).len_val()).as_bool() {
        body = anubis_add(body.clone(), (text.clone()).index_get(i.clone()));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    if anubis_cmp("==", (body.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("exact-alg: sign without digits; fail closed".to_string()));
    }
    if anubis_cmp(">", (body.clone()).len_val(), AnubisValue::Int(4096)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("exact-alg: rational input exceeds 4096 decimal digits; fail closed (int-budget)".to_string()));
    }
    let mut slash = anubis_neg(AnubisValue::Int(1));
    i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (body.clone()).len_val()).as_bool() {
        if anubis_cmp("==", (body.clone()).index_get(i.clone()), anubis_mk_str("/".to_string())).as_bool() {
            if anubis_cmp(">=", slash.clone(), AnubisValue::Int(0)).as_bool() {
                let _ = anubis_panic(anubis_mk_str("exact-alg: malformed rational (multiple '/'); fail closed".to_string()));
            }
            slash = i.clone();
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    let mut value = anb_rat_zero();
    if anubis_cmp("<", slash.clone(), AnubisValue::Int(0)).as_bool() {
        let mut dots = AnubisValue::Int(0);
        i = AnubisValue::Int(0);
        while anubis_cmp("<", i.clone(), (body.clone()).len_val()).as_bool() {
            let mut ch = (body.clone()).index_get(i.clone());
            if anubis_cmp("==", ch.clone(), anubis_mk_str(".".to_string())).as_bool() {
                dots = anubis_add(dots.clone(), AnubisValue::Int(1));
            } else {
                if AnubisValue::Bool(!(anb_is_digit_char(ch.clone())).as_bool()).as_bool() {
                    let _ = anubis_panic(anubis_mk_str("exact-alg: malformed rational literal; fail closed".to_string()));
                }
            }
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp(">", dots.clone(), AnubisValue::Int(1))).as_bool() || (anubis_cmp("==", (body.clone()).index_get(AnubisValue::Int(0)), anubis_mk_str(".".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", (body.clone()).index_get(anubis_sub((body.clone()).len_val(), AnubisValue::Int(1))), anubis_mk_str(".".to_string()))).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("exact-alg: malformed rational literal; fail closed".to_string()));
        }
        value = anb_rat_from_num_text(body.clone());
    } else {
        let mut numer = anubis_mk_str("".to_string());
        let mut denom = anubis_mk_str("".to_string());
        i = AnubisValue::Int(0);
        while anubis_cmp("<", i.clone(), slash.clone()).as_bool() {
            numer = anubis_add(numer.clone(), (body.clone()).index_get(i.clone()));
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        i = anubis_add(slash.clone(), AnubisValue::Int(1));
        while anubis_cmp("<", i.clone(), (body.clone()).len_val()).as_bool() {
            denom = anubis_add(denom.clone(), (body.clone()).index_get(i.clone()));
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        if AnubisValue::Bool((anubis_cmp("==", (numer.clone()).len_val(), AnubisValue::Int(0))).as_bool() || (anubis_cmp("==", (denom.clone()).len_val(), AnubisValue::Int(0))).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("exact-alg: malformed rational; fail closed".to_string()));
        }
        value = anb_rat_make(AnubisValue::Bool(false), anb_big_from_text(numer.clone()), anb_big_from_text(denom.clone()));
    }
    if neg.clone().as_bool() {
        return anb_rat_neg(value.clone());
    }
    return value.clone();
    AnubisValue::Int(0)
}

fn anb_rat_sign(mut r: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anb_big_is_zero(r.field_get("num")).as_bool() {
        return AnubisValue::Int(0);
    }
    if r.field_get("neg").as_bool() {
        return anubis_neg(AnubisValue::Int(1));
    }
    return AnubisValue::Int(1);
    AnubisValue::Int(0)
}

fn anb_rat_half_point(mut lo: AnubisValue, mut hi: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_rat_mul(anb_rat_add_impl(lo.clone(), hi.clone()), AnubisValue::Struct { ty: "Rational".to_string(), fields: vec![("neg".to_string(), AnubisValue::Bool(false)), ("num".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)])), ("den".to_string(), anubis_mk_list(vec![AnubisValue::Int(2)]))] });
    AnubisValue::Int(0)
}

fn anb_rat_digit_guard(mut r: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp(">", (anb_big_to_text(r.field_get("num"))).len_val(), AnubisValue::Int(4096))).as_bool() || (anubis_cmp(">", (anb_big_to_text(r.field_get("den"))).len_val(), AnubisValue::Int(4096))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("poly: coefficient exceeds 4096 decimal digits; fail closed (poly-budget)".to_string()));
    }
    return r.clone();
    AnubisValue::Int(0)
}

fn anb_poly_norm(mut p: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    while AnubisValue::Bool((anubis_cmp(">", (p.clone()).len_val(), AnubisValue::Int(1))).as_bool() && (anb_big_is_zero((p.index_get(anubis_sub((p.clone()).len_val(), AnubisValue::Int(1)))).field_get("num"))).as_bool()).as_bool() {
        let _ = anubis_pop(&mut p);
    }
    return p.clone();
    AnubisValue::Int(0)
}

fn anb_poly_zero() -> AnubisValue {
    __anb_stack_guard();
    return anubis_mk_list(vec![anb_rat_zero()]);
    AnubisValue::Int(0)
}

fn anb_poly_is_zero(mut p: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return AnubisValue::Bool((anubis_cmp("==", (p.clone()).len_val(), AnubisValue::Int(1))).as_bool() && (anb_big_is_zero((p.index_get(AnubisValue::Int(0))).field_get("num"))).as_bool());
    AnubisValue::Int(0)
}

fn anb_poly_deg(mut p: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anb_poly_is_zero(p.clone()).as_bool() {
        return anubis_neg(AnubisValue::Int(1));
    }
    return anubis_sub((p.clone()).len_val(), AnubisValue::Int(1));
    AnubisValue::Int(0)
}

fn anb_poly_add(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut result = anubis_mk_list(vec![]);
    let mut n = (a.clone()).len_val();
    if anubis_cmp(">", (b.clone()).len_val(), n.clone()).as_bool() {
        n = (b.clone()).len_val();
    }
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), n.clone()).as_bool() {
        let mut x = anb_rat_zero();
        if anubis_cmp("<", i.clone(), (a.clone()).len_val()).as_bool() {
            x = a.index_get(i.clone());
        }
        let mut y = anb_rat_zero();
        if anubis_cmp("<", i.clone(), (b.clone()).len_val()).as_bool() {
            y = b.index_get(i.clone());
        }
        result.push_val(anb_rat_add_impl(x.clone(), y.clone()));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return anb_poly_norm(result.clone());
    AnubisValue::Int(0)
}

fn anb_poly_neg(mut p: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut result = anubis_mk_list(vec![]);
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (p.clone()).len_val()).as_bool() {
        result.push_val(anb_rat_neg(p.index_get(i.clone())));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return result.clone();
    AnubisValue::Int(0)
}

fn anb_poly_sub(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anb_poly_add(a.clone(), anb_poly_neg(b.clone()));
    AnubisValue::Int(0)
}

fn anb_poly_mul(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anb_poly_is_zero(a.clone())).as_bool() || (anb_poly_is_zero(b.clone())).as_bool()).as_bool() {
        return anb_poly_zero();
    }
    let mut dd = anubis_sub(anubis_add((a.clone()).len_val(), (b.clone()).len_val()), AnubisValue::Int(2));
    if anubis_cmp(">", dd.clone(), AnubisValue::Int(64)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("poly: expanded degree exceeds the cap of 64; fail closed (poly-budget)".to_string()));
    }
    let mut result = anubis_mk_list(vec![]);
    let mut t = AnubisValue::Int(0);
    while anubis_cmp("<=", t.clone(), dd.clone()).as_bool() {
        result.push_val(anb_rat_zero());
        t = anubis_add(t.clone(), AnubisValue::Int(1));
    }
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (a.clone()).len_val()).as_bool() {
        let mut j = AnubisValue::Int(0);
        while anubis_cmp("<", j.clone(), (b.clone()).len_val()).as_bool() {
            result.set_at(&[AnubisPathSeg::Index(anubis_add(i.clone(), j.clone()))], anb_rat_add_impl(result.index_get(anubis_add(i.clone(), j.clone())), anb_rat_mul(a.index_get(i.clone()), b.index_get(j.clone()))));
            j = anubis_add(j.clone(), AnubisValue::Int(1));
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return anb_poly_norm(result.clone());
    AnubisValue::Int(0)
}

fn anb_poly_scale_div(mut p: AnubisValue, mut c: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut result = anubis_mk_list(vec![]);
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (p.clone()).len_val()).as_bool() {
        result.push_val(anb_rat_div(p.index_get(i.clone()), c.clone()));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return anb_poly_norm(result.clone());
    AnubisValue::Int(0)
}

fn anb_poly_pow(mut p: AnubisValue, mut n: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", n.clone(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("poly: negative exponent outside the polynomial fragment; fail closed (poly-fragment)".to_string()));
    }
    let mut result = anubis_mk_list(vec![anb_rat_one()]);
    let mut base = p.clone();
    let mut e = n.clone();
    while anubis_cmp(">", e.clone(), AnubisValue::Int(0)).as_bool() {
        if anubis_cmp("==", anubis_mod(e.clone(), AnubisValue::Int(2)), AnubisValue::Int(1)).as_bool() {
            result = anb_poly_mul(result.clone(), base.clone());
        }
        e = anubis_div(e.clone(), AnubisValue::Int(2));
        if anubis_cmp(">", e.clone(), AnubisValue::Int(0)).as_bool() {
            base = anb_poly_mul(base.clone(), base.clone());
        }
    }
    return result.clone();
    AnubisValue::Int(0)
}

fn anb_poly_divmod(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anb_poly_is_zero(b.clone()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("poly: division by the zero polynomial; fail closed".to_string()));
    }
    if AnubisValue::Bool((anb_poly_is_zero(a.clone())).as_bool() || (anubis_cmp("<", (a.clone()).len_val(), (b.clone()).len_val())).as_bool()).as_bool() {
        return AnubisValue::Struct { ty: "PolyDivmod".to_string(), fields: vec![("q".to_string(), anb_poly_zero()), ("r".to_string(), a.clone())] };
    }
    let mut qlen = anubis_add(anubis_sub((a.clone()).len_val(), (b.clone()).len_val()), AnubisValue::Int(1));
    let mut q = anubis_mk_list(vec![]);
    let mut t = AnubisValue::Int(0);
    while anubis_cmp("<", t.clone(), qlen.clone()).as_bool() {
        q.push_val(anb_rat_zero());
        t = anubis_add(t.clone(), AnubisValue::Int(1));
    }
    let mut rem = a.clone();
    let mut blead = b.index_get(anubis_sub((b.clone()).len_val(), AnubisValue::Int(1)));
    let mut i = anubis_sub(qlen.clone(), AnubisValue::Int(1));
    while anubis_cmp(">=", i.clone(), AnubisValue::Int(0)).as_bool() {
        if anubis_cmp("==", (rem.clone()).len_val(), anubis_add((b.clone()).len_val(), i.clone())).as_bool() {
            let mut coeff = anb_rat_div(rem.index_get(anubis_sub((rem.clone()).len_val(), AnubisValue::Int(1))), blead.clone());
            q.set_at(&[AnubisPathSeg::Index(i.clone())], coeff.clone());
            let mut j = AnubisValue::Int(0);
            while anubis_cmp("<", j.clone(), (b.clone()).len_val()).as_bool() {
                rem.set_at(&[AnubisPathSeg::Index(anubis_add(i.clone(), j.clone()))], anb_rat_sub(rem.index_get(anubis_add(i.clone(), j.clone())), anb_rat_mul(coeff.clone(), b.index_get(j.clone()))));
                j = anubis_add(j.clone(), AnubisValue::Int(1));
            }
            rem = anb_poly_norm(rem.clone());
        }
        i = anubis_sub(i.clone(), AnubisValue::Int(1));
    }
    return AnubisValue::Struct { ty: "PolyDivmod".to_string(), fields: vec![("q".to_string(), anb_poly_norm(q.clone())), ("r".to_string(), anb_poly_norm(rem.clone()))] };
    AnubisValue::Int(0)
}

fn anb_poly_monic(mut p: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anb_poly_is_zero(p.clone()).as_bool() {
        return p.clone();
    }
    let mut lead = p.index_get(anubis_sub((p.clone()).len_val(), AnubisValue::Int(1)));
    return anb_poly_scale_div(p.clone(), lead.clone());
    AnubisValue::Int(0)
}

fn anb_poly_gcd(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut x = a.clone();
    let mut y = b.clone();
    while AnubisValue::Bool(!(anb_poly_is_zero(y.clone())).as_bool()).as_bool() {
        let mut dm = anb_poly_divmod(x.clone(), y.clone());
        x = y.clone();
        y = dm.field_get("r");
    }
    return anb_poly_monic(x.clone());
    AnubisValue::Int(0)
}

fn anb_poly_eval(mut p: AnubisValue, mut v: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut acc = anb_rat_zero();
    let mut i = anubis_sub((p.clone()).len_val(), AnubisValue::Int(1));
    while anubis_cmp(">=", i.clone(), AnubisValue::Int(0)).as_bool() {
        acc = anb_rat_add_impl(anb_rat_mul(acc.clone(), v.clone()), p.index_get(i.clone()));
        i = anubis_sub(i.clone(), AnubisValue::Int(1));
    }
    return acc.clone();
    AnubisValue::Int(0)
}

fn anb_poly_deriv(mut p: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<=", (p.clone()).len_val(), AnubisValue::Int(1)).as_bool() {
        return anb_poly_zero();
    }
    let mut result = anubis_mk_list(vec![]);
    let mut i = AnubisValue::Int(1);
    while anubis_cmp("<", i.clone(), (p.clone()).len_val()).as_bool() {
        result.push_val(anb_rat_mul(p.index_get(i.clone()), anb_rat_int(i.clone())));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return anb_poly_norm(result.clone());
    AnubisValue::Int(0)
}

fn anb_poly_equal(mut a: AnubisValue, mut b: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("!=", (a.clone()).len_val(), (b.clone()).len_val()).as_bool() {
        return AnubisValue::Bool(false);
    }
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (a.clone()).len_val()).as_bool() {
        if anubis_cmp("!=", anb_rat_cmp(a.index_get(i.clone()), b.index_get(i.clone())), AnubisValue::Int(0)).as_bool() {
            return AnubisValue::Bool(false);
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return AnubisValue::Bool(true);
    AnubisValue::Int(0)
}

fn anb_poly_coeffs_text(mut p: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut text = anubis_mk_str("".to_string());
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (p.clone()).len_val()).as_bool() {
        let _ = anb_rat_digit_guard(p.index_get(i.clone()));
        if anubis_cmp(">", i.clone(), AnubisValue::Int(0)).as_bool() {
            text = anubis_add(text.clone(), anubis_mk_str(",".to_string()));
        }
        text = anubis_add(text.clone(), anb_rat_to_text(p.index_get(i.clone())));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return text.clone();
    AnubisValue::Int(0)
}

fn anb_json_coeff_array(mut p: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut text = anubis_mk_str("[".to_string());
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (p.clone()).len_val()).as_bool() {
        let _ = anb_rat_digit_guard(p.index_get(i.clone()));
        if anubis_cmp(">", i.clone(), AnubisValue::Int(0)).as_bool() {
            text = anubis_add(text.clone(), anubis_mk_str(",".to_string()));
        }
        text = anubis_add(anubis_add(anubis_add(text.clone(), anubis_mk_str("\"".to_string())), anb_rat_to_text(p.index_get(i.clone()))), anubis_mk_str("\"".to_string()));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return anubis_add(text.clone(), anubis_mk_str("]".to_string()));
    AnubisValue::Int(0)
}

fn anb_poly_exponent_literal(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("!=", node.index_get(AnubisValue::Int(0)), anubis_mk_str("num".to_string())).as_bool() {
        let _ = anubis_panic(anubis_mk_str("poly: ^ exponent must be a nonnegative integer literal; fail closed (poly-fragment)".to_string()));
    }
    let mut value = anb_rat_from_num_text(node.index_get(AnubisValue::Int(2)));
    if anubis_cmp("!=", anb_big_cmp(value.field_get("den"), anubis_mk_list(vec![AnubisValue::Int(1)])), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("poly: ^ exponent must be a nonnegative integer literal; fail closed (poly-fragment)".to_string()));
    }
    if anubis_cmp(">", anb_big_cmp(value.field_get("num"), anubis_mk_list(vec![AnubisValue::Int(64)])), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("poly: ^ exponent exceeds the cap of 64; fail closed (poly-budget)".to_string()));
    }
    return (value.field_get("num")).index_get(AnubisValue::Int(0));
    AnubisValue::Int(0)
}

fn anb_poly_lower(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string())).as_bool() {
        return AnubisValue::Struct { ty: "PolyBox".to_string(), fields: vec![("coeffs".to_string(), anubis_mk_list(vec![anb_rat_from_num_text(node.index_get(AnubisValue::Int(2)))]))] };
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string())).as_bool() {
        if anubis_cmp("!=", node.index_get(AnubisValue::Int(1)), anubis_mk_str("x".to_string())).as_bool() {
            let _ = anubis_panic(anubis_mk_str("poly: only the variable x is admitted; fail closed (poly-fragment)".to_string()));
        }
        return AnubisValue::Struct { ty: "PolyBox".to_string(), fields: vec![("coeffs".to_string(), anubis_mk_list(vec![anb_rat_zero(), anb_rat_one()]))] };
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        let mut inner = anb_poly_lower(node.index_get(AnubisValue::Int(1)));
        let mut ic = inner.field_get("coeffs");
        return AnubisValue::Struct { ty: "PolyBox".to_string(), fields: vec![("coeffs".to_string(), anb_poly_neg(ic.clone()))] };
    }
    if AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string()))).as_bool()).as_bool() {
        let mut left = anb_poly_lower(node.index_get(AnubisValue::Int(1)));
        let mut right = anb_poly_lower(node.index_get(AnubisValue::Int(2)));
        let mut lc = left.field_get("coeffs");
        let mut rc = right.field_get("coeffs");
        if anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string())).as_bool() {
            return AnubisValue::Struct { ty: "PolyBox".to_string(), fields: vec![("coeffs".to_string(), anb_poly_add(lc.clone(), rc.clone()))] };
        }
        if anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string())).as_bool() {
            return AnubisValue::Struct { ty: "PolyBox".to_string(), fields: vec![("coeffs".to_string(), anb_poly_sub(lc.clone(), rc.clone()))] };
        }
        if anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string())).as_bool() {
            return AnubisValue::Struct { ty: "PolyBox".to_string(), fields: vec![("coeffs".to_string(), anb_poly_mul(lc.clone(), rc.clone()))] };
        }
        if anubis_cmp("!=", (rc.clone()).len_val(), AnubisValue::Int(1)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("poly: division only by a constant subexpression in the polynomial fragment; fail closed (poly-fragment)".to_string()));
        }
        if anb_big_is_zero((rc.index_get(AnubisValue::Int(0))).field_get("num")).as_bool() {
            let _ = anubis_panic(anubis_mk_str("poly: division by a zero constant; fail closed (poly-fragment)".to_string()));
        }
        return AnubisValue::Struct { ty: "PolyBox".to_string(), fields: vec![("coeffs".to_string(), anb_poly_scale_div(lc.clone(), rc.index_get(AnubisValue::Int(0))))] };
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("pow".to_string())).as_bool() {
        let mut base = anb_poly_lower(node.index_get(AnubisValue::Int(1)));
        let mut bc = base.field_get("coeffs");
        let mut e = anb_poly_exponent_literal(node.index_get(AnubisValue::Int(2)));
        return AnubisValue::Struct { ty: "PolyBox".to_string(), fields: vec![("coeffs".to_string(), anb_poly_pow(bc.clone(), e.clone()))] };
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mod".to_string())).as_bool() {
        let _ = anubis_panic(anubis_mk_str("poly: '%' is outside the polynomial fragment; fail closed (poly-fragment)".to_string()));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string())).as_bool() {
        let _ = anubis_panic(anubis_mk_str("poly: named constants are outside the polynomial fragment; fail closed (poly-fragment)".to_string()));
    }
    anubis_panic(anubis_mk_str("poly: functions are outside the polynomial fragment; fail closed (poly-fragment)".to_string()))
}

fn anb_rf_lower(mut node: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut tag = node.index_get(AnubisValue::Int(0));
    if anubis_cmp("==", tag.clone(), anubis_mk_str("num".to_string())).as_bool() {
        return AnubisValue::Struct { ty: "RatFunc".to_string(), fields: vec![("num".to_string(), anubis_mk_list(vec![anb_rat_from_num_text(node.index_get(AnubisValue::Int(2)))])), ("den".to_string(), anubis_mk_list(vec![anb_rat_one()]))] };
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("var".to_string())).as_bool() {
        if anubis_cmp("!=", node.index_get(AnubisValue::Int(1)), anubis_mk_str("x".to_string())).as_bool() {
            let _ = anubis_panic(anubis_mk_str("ratfunc: only the variable x is admitted; fail closed (poly-fragment)".to_string()));
        }
        return AnubisValue::Struct { ty: "RatFunc".to_string(), fields: vec![("num".to_string(), anubis_mk_list(vec![anb_rat_zero(), anb_rat_one()])), ("den".to_string(), anubis_mk_list(vec![anb_rat_one()]))] };
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("neg".to_string())).as_bool() {
        let mut inner = anb_rf_lower(node.index_get(AnubisValue::Int(1)));
        let mut inum = inner.field_get("num");
        let mut iden = inner.field_get("den");
        return AnubisValue::Struct { ty: "RatFunc".to_string(), fields: vec![("num".to_string(), anb_poly_neg(inum.clone())), ("den".to_string(), iden.clone())] };
    }
    if AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string()))).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", tag.clone(), anubis_mk_str("div".to_string()))).as_bool()).as_bool() {
        let mut left = anb_rf_lower(node.index_get(AnubisValue::Int(1)));
        let mut right = anb_rf_lower(node.index_get(AnubisValue::Int(2)));
        let mut ln = left.field_get("num");
        let mut ld = left.field_get("den");
        let mut rn = right.field_get("num");
        let mut rd = right.field_get("den");
        if anubis_cmp("==", tag.clone(), anubis_mk_str("add".to_string())).as_bool() {
            let mut cross_a = anb_poly_mul(ln.clone(), rd.clone());
            let mut cross_b = anb_poly_mul(rn.clone(), ld.clone());
            return AnubisValue::Struct { ty: "RatFunc".to_string(), fields: vec![("num".to_string(), anb_poly_add(cross_a.clone(), cross_b.clone())), ("den".to_string(), anb_poly_mul(ld.clone(), rd.clone()))] };
        }
        if anubis_cmp("==", tag.clone(), anubis_mk_str("sub".to_string())).as_bool() {
            let mut cross_a = anb_poly_mul(ln.clone(), rd.clone());
            let mut cross_b = anb_poly_mul(rn.clone(), ld.clone());
            return AnubisValue::Struct { ty: "RatFunc".to_string(), fields: vec![("num".to_string(), anb_poly_sub(cross_a.clone(), cross_b.clone())), ("den".to_string(), anb_poly_mul(ld.clone(), rd.clone()))] };
        }
        if anubis_cmp("==", tag.clone(), anubis_mk_str("mul".to_string())).as_bool() {
            return AnubisValue::Struct { ty: "RatFunc".to_string(), fields: vec![("num".to_string(), anb_poly_mul(ln.clone(), rn.clone())), ("den".to_string(), anb_poly_mul(ld.clone(), rd.clone()))] };
        }
        if anb_poly_is_zero(rn.clone()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("ratfunc: division by the zero polynomial; fail closed (ratfunc-zero-den)".to_string()));
        }
        return AnubisValue::Struct { ty: "RatFunc".to_string(), fields: vec![("num".to_string(), anb_poly_mul(ln.clone(), rd.clone())), ("den".to_string(), anb_poly_mul(ld.clone(), rn.clone()))] };
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("pow".to_string())).as_bool() {
        let mut base = anb_rf_lower(node.index_get(AnubisValue::Int(1)));
        let mut bn = base.field_get("num");
        let mut bd = base.field_get("den");
        let mut e = anb_poly_exponent_literal(node.index_get(AnubisValue::Int(2)));
        return AnubisValue::Struct { ty: "RatFunc".to_string(), fields: vec![("num".to_string(), anb_poly_pow(bn.clone(), e.clone())), ("den".to_string(), anb_poly_pow(bd.clone(), e.clone()))] };
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("mod".to_string())).as_bool() {
        let _ = anubis_panic(anubis_mk_str("ratfunc: '%' is outside the rational-function fragment; fail closed (poly-fragment)".to_string()));
    }
    if anubis_cmp("==", tag.clone(), anubis_mk_str("const".to_string())).as_bool() {
        let _ = anubis_panic(anubis_mk_str("ratfunc: named constants are outside the rational-function fragment; fail closed (poly-fragment)".to_string()));
    }
    anubis_panic(anubis_mk_str("ratfunc: functions are outside the rational-function fragment; fail closed (poly-fragment)".to_string()))
}

fn anb_rf_canon(mut f: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut p = f.field_get("num");
    let mut q = f.field_get("den");
    if anb_poly_is_zero(q.clone()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("ratfunc: zero denominator; fail closed (ratfunc-zero-den)".to_string()));
    }
    if anb_poly_is_zero(p.clone()).as_bool() {
        return AnubisValue::Struct { ty: "RatFunc".to_string(), fields: vec![("num".to_string(), anb_poly_zero()), ("den".to_string(), anubis_mk_list(vec![anb_rat_one()]))] };
    }
    let mut g = anb_poly_gcd(p.clone(), q.clone());
    let mut pd = anb_poly_divmod(p.clone(), g.clone());
    let mut qd = anb_poly_divmod(q.clone(), g.clone());
    if AnubisValue::Bool((AnubisValue::Bool(!(anb_poly_is_zero(pd.field_get("r"))).as_bool())).as_bool() || (AnubisValue::Bool(!(anb_poly_is_zero(qd.field_get("r"))).as_bool())).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("ratfunc: internal gcd division invariant violated; fail closed".to_string()));
    }
    let mut pr = pd.field_get("q");
    let mut qr = qd.field_get("q");
    let mut lead = qr.index_get(anubis_sub((qr.clone()).len_val(), AnubisValue::Int(1)));
    return AnubisValue::Struct { ty: "RatFunc".to_string(), fields: vec![("num".to_string(), anb_poly_scale_div(pr.clone(), lead.clone())), ("den".to_string(), anb_poly_scale_div(qr.clone(), lead.clone()))] };
    AnubisValue::Int(0)
}

fn anb_poly_squarefree(mut p: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anb_poly_is_zero(p.clone()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("roots: the zero polynomial vanishes everywhere; fail closed (roots-zero-poly)".to_string()));
    }
    let mut d = anb_poly_deriv(p.clone());
    let mut g = anb_poly_gcd(p.clone(), d.clone());
    let mut dm = anb_poly_divmod(p.clone(), g.clone());
    if AnubisValue::Bool(!(anb_poly_is_zero(dm.field_get("r"))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("roots: internal squarefree division invariant violated; fail closed".to_string()));
    }
    return anb_poly_monic(dm.field_get("q"));
    AnubisValue::Int(0)
}

fn anb_sturm_chain(mut s: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut chain = anubis_mk_list(vec![s.clone()]);
    let mut d = anb_poly_deriv(s.clone());
    if anb_poly_is_zero(d.clone()).as_bool() {
        return chain.clone();
    }
    chain.push_val(d.clone());
    while AnubisValue::Bool(true).as_bool() {
        let mut a = chain.index_get(anubis_sub((chain.clone()).len_val(), AnubisValue::Int(2)));
        let mut b = chain.index_get(anubis_sub((chain.clone()).len_val(), AnubisValue::Int(1)));
        let mut dm = anb_poly_divmod(a.clone(), b.clone());
        let mut r = dm.field_get("r");
        if anb_poly_is_zero(r.clone()).as_bool() {
            break;
        }
        chain.push_val(anb_poly_neg(r.clone()));
        if anubis_cmp(">", (chain.clone()).len_val(), AnubisValue::Int(130)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("roots: Sturm chain exceeded its budget; fail closed (roots-budget)".to_string()));
        }
    }
    return chain.clone();
    AnubisValue::Int(0)
}

fn anb_sturm_variations(mut chain: AnubisValue, mut t: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut count = AnubisValue::Int(0);
    let mut prev = AnubisValue::Int(0);
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (chain.clone()).len_val()).as_bool() {
        let mut s = anb_rat_sign(anb_poly_eval(chain.index_get(i.clone()), t.clone()));
        if anubis_cmp("!=", s.clone(), AnubisValue::Int(0)).as_bool() {
            if AnubisValue::Bool((anubis_cmp("!=", prev.clone(), AnubisValue::Int(0))).as_bool() && (anubis_cmp("!=", s.clone(), prev.clone())).as_bool()).as_bool() {
                count = anubis_add(count.clone(), AnubisValue::Int(1));
            }
            prev = s.clone();
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return count.clone();
    AnubisValue::Int(0)
}

fn anb_cauchy_bound(mut s: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut lead = s.index_get(anubis_sub((s.clone()).len_val(), AnubisValue::Int(1)));
    let mut best = anb_rat_zero();
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), anubis_sub((s.clone()).len_val(), AnubisValue::Int(1))).as_bool() {
        let mut q = anb_rat_abs(anb_rat_div(s.index_get(i.clone()), lead.clone()));
        if anubis_cmp(">", anb_rat_cmp(q.clone(), best.clone()), AnubisValue::Int(0)).as_bool() {
            best = q.clone();
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return anb_rat_add_impl(anb_rat_one(), best.clone());
    AnubisValue::Int(0)
}

fn anb_sturm_refine(mut chain: AnubisValue, mut iv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut lo = iv.field_get("lo");
    let mut hi = iv.field_get("hi");
    let mut mid = anb_rat_half_point(lo.clone(), hi.clone());
    let mut c = anubis_sub(anb_sturm_variations(chain.clone(), lo.clone()), anb_sturm_variations(chain.clone(), mid.clone()));
    if anubis_cmp("==", c.clone(), AnubisValue::Int(1)).as_bool() {
        return AnubisValue::Struct { ty: "RootIv".to_string(), fields: vec![("lo".to_string(), lo.clone()), ("hi".to_string(), mid.clone()), ("count".to_string(), anubis_field_require_int(AnubisValue::Int(1), "count")), ("depth".to_string(), anubis_field_require_int(anubis_add(iv.field_get("depth"), AnubisValue::Int(1)), "depth"))] };
    }
    return AnubisValue::Struct { ty: "RootIv".to_string(), fields: vec![("lo".to_string(), mid.clone()), ("hi".to_string(), hi.clone()), ("count".to_string(), anubis_field_require_int(AnubisValue::Int(1), "count")), ("depth".to_string(), anubis_field_require_int(anubis_add(iv.field_get("depth"), AnubisValue::Int(1)), "depth"))] };
    AnubisValue::Int(0)
}

fn anb_sturm_isolate_all(mut chain: AnubisValue, mut s: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut out = anubis_mk_list(vec![]);
    if anubis_cmp("<=", (s.clone()).len_val(), AnubisValue::Int(1)).as_bool() {
        return out.clone();
    }
    let mut bound = anb_cauchy_bound(s.clone());
    let mut neg_b = anb_rat_neg(bound.clone());
    let mut k = anubis_sub(anb_sturm_variations(chain.clone(), neg_b.clone()), anb_sturm_variations(chain.clone(), bound.clone()));
    if anubis_cmp("==", k.clone(), AnubisValue::Int(0)).as_bool() {
        return out.clone();
    }
    let mut stack = anubis_mk_list(vec![AnubisValue::Struct { ty: "RootIv".to_string(), fields: vec![("lo".to_string(), neg_b.clone()), ("hi".to_string(), bound.clone()), ("count".to_string(), anubis_field_require_int(k.clone(), "count")), ("depth".to_string(), anubis_field_require_int(AnubisValue::Int(0), "depth"))] }]);
    while anubis_cmp(">", (stack.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        let mut iv = stack.index_get(anubis_sub((stack.clone()).len_val(), AnubisValue::Int(1)));
        let _ = anubis_pop(&mut stack);
        let mut c = iv.field_get("count");
        if anubis_cmp("==", c.clone(), AnubisValue::Int(1)).as_bool() {
            out.push_val(iv.clone());
            continue;
        }
        if anubis_cmp(">=", iv.field_get("depth"), AnubisValue::Int(64)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("roots: bisection exceeded depth 64; fail closed (roots-budget)".to_string()));
        }
        let mut lo = iv.field_get("lo");
        let mut hi = iv.field_get("hi");
        let mut mid = anb_rat_half_point(lo.clone(), hi.clone());
        let mut vlo = anb_sturm_variations(chain.clone(), lo.clone());
        let mut vmid = anb_sturm_variations(chain.clone(), mid.clone());
        let mut vhi = anb_sturm_variations(chain.clone(), hi.clone());
        let mut left_count = anubis_sub(vlo.clone(), vmid.clone());
        let mut right_count = anubis_sub(vmid.clone(), vhi.clone());
        if anubis_cmp("!=", anubis_add(left_count.clone(), right_count.clone()), c.clone()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("roots: internal Sturm-count invariant violated; fail closed".to_string()));
        }
        let mut d1 = anubis_add(iv.field_get("depth"), AnubisValue::Int(1));
        if anubis_cmp(">", right_count.clone(), AnubisValue::Int(0)).as_bool() {
            stack.push_val(AnubisValue::Struct { ty: "RootIv".to_string(), fields: vec![("lo".to_string(), mid.clone()), ("hi".to_string(), hi.clone()), ("count".to_string(), anubis_field_require_int(right_count.clone(), "count")), ("depth".to_string(), anubis_field_require_int(d1.clone(), "depth"))] });
        }
        if anubis_cmp(">", left_count.clone(), AnubisValue::Int(0)).as_bool() {
            stack.push_val(AnubisValue::Struct { ty: "RootIv".to_string(), fields: vec![("lo".to_string(), lo.clone()), ("hi".to_string(), mid.clone()), ("count".to_string(), anubis_field_require_int(left_count.clone(), "count")), ("depth".to_string(), anubis_field_require_int(d1.clone(), "depth"))] });
        }
    }
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (out.clone()).len_val()).as_bool() {
        let mut guard = AnubisValue::Int(0);
        while anubis_cmp("==", anb_rat_sign(anb_poly_eval(s.clone(), (out.index_get(i.clone())).field_get("lo"))), AnubisValue::Int(0)).as_bool() {
            out.set_at(&[AnubisPathSeg::Index(i.clone())], anb_sturm_refine(chain.clone(), out.index_get(i.clone())));
            guard = anubis_add(guard.clone(), AnubisValue::Int(1));
            if anubis_cmp(">", guard.clone(), AnubisValue::Int(64)).as_bool() {
                let _ = anubis_panic(anubis_mk_str("roots: endpoint refinement exceeded its budget; fail closed (roots-budget)".to_string()));
            }
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    i = AnubisValue::Int(0);
    while anubis_cmp("<", anubis_add(i.clone(), AnubisValue::Int(1)), (out.clone()).len_val()).as_bool() {
        let mut guard = AnubisValue::Int(0);
        while anubis_cmp(">=", anb_rat_cmp((out.index_get(i.clone())).field_get("hi"), (out.index_get(anubis_add(i.clone(), AnubisValue::Int(1)))).field_get("lo")), AnubisValue::Int(0)).as_bool() {
            out.set_at(&[AnubisPathSeg::Index(i.clone())], anb_sturm_refine(chain.clone(), out.index_get(i.clone())));
            out.set_at(&[AnubisPathSeg::Index(anubis_add(i.clone(), AnubisValue::Int(1)))], anb_sturm_refine(chain.clone(), out.index_get(anubis_add(i.clone(), AnubisValue::Int(1)))));
            guard = anubis_add(guard.clone(), AnubisValue::Int(1));
            if anubis_cmp(">", guard.clone(), AnubisValue::Int(64)).as_bool() {
                let _ = anubis_panic(anubis_mk_str("roots: interval separation exceeded its budget; fail closed (roots-budget)".to_string()));
            }
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return out.clone();
    AnubisValue::Int(0)
}

fn anb_alg_cmp_order(mut p_expr: AnubisValue, mut a1_text: AnubisValue, mut b1_text: AnubisValue, mut q_expr: AnubisValue, mut a2_text: AnubisValue, mut b2_text: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut pb = anb_poly_lower(anb_parse_ast(p_expr.clone()));
    let mut qb = anb_poly_lower(anb_parse_ast(q_expr.clone()));
    let mut s1 = anb_poly_squarefree(pb.field_get("coeffs"));
    let mut s2 = anb_poly_squarefree(qb.field_get("coeffs"));
    let mut ch1 = anb_sturm_chain(s1.clone());
    let mut ch2 = anb_sturm_chain(s2.clone());
    let mut a1 = anb_rat_from_frac_text(a1_text.clone());
    let mut b1 = anb_rat_from_frac_text(b1_text.clone());
    let mut a2 = anb_rat_from_frac_text(a2_text.clone());
    let mut b2 = anb_rat_from_frac_text(b2_text.clone());
    if AnubisValue::Bool((anubis_cmp("!=", anubis_sub(anb_sturm_variations(ch1.clone(), a1.clone()), anb_sturm_variations(ch1.clone(), b1.clone())), AnubisValue::Int(1))).as_bool() || (anubis_cmp("==", anb_rat_sign(anb_poly_eval(s1.clone(), a1.clone())), AnubisValue::Int(0))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("alg-cmp: the first interval does not isolate exactly one root of its polynomial; fail closed (alg-cmp-not-isolating)".to_string()));
    }
    if AnubisValue::Bool((anubis_cmp("!=", anubis_sub(anb_sturm_variations(ch2.clone(), a2.clone()), anb_sturm_variations(ch2.clone(), b2.clone())), AnubisValue::Int(1))).as_bool() || (anubis_cmp("==", anb_rat_sign(anb_poly_eval(s2.clone(), a2.clone())), AnubisValue::Int(0))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("alg-cmp: the second interval does not isolate exactly one root of its polynomial; fail closed (alg-cmp-not-isolating)".to_string()));
    }
    let mut g = anb_poly_gcd(s1.clone(), s2.clone());
    if anubis_cmp(">", (g.clone()).len_val(), AnubisValue::Int(1)).as_bool() {
        let mut lo = anb_rat_max(a1.clone(), a2.clone());
        let mut hi = anb_rat_min(b1.clone(), b2.clone());
        if anubis_cmp("<", anb_rat_cmp(lo.clone(), hi.clone()), AnubisValue::Int(0)).as_bool() {
            let mut chg = anb_sturm_chain(g.clone());
            if anubis_cmp(">=", anubis_sub(anb_sturm_variations(chg.clone(), lo.clone()), anb_sturm_variations(chg.clone(), hi.clone())), AnubisValue::Int(1)).as_bool() {
                return anubis_mk_str("equal".to_string());
            }
        }
    }
    let mut i1 = AnubisValue::Struct { ty: "RootIv".to_string(), fields: vec![("lo".to_string(), a1.clone()), ("hi".to_string(), b1.clone()), ("count".to_string(), anubis_field_require_int(AnubisValue::Int(1), "count")), ("depth".to_string(), anubis_field_require_int(AnubisValue::Int(0), "depth"))] };
    let mut i2 = AnubisValue::Struct { ty: "RootIv".to_string(), fields: vec![("lo".to_string(), a2.clone()), ("hi".to_string(), b2.clone()), ("count".to_string(), anubis_field_require_int(AnubisValue::Int(1), "count")), ("depth".to_string(), anubis_field_require_int(AnubisValue::Int(0), "depth"))] };
    let mut steps = AnubisValue::Int(0);
    while anubis_cmp("<", steps.clone(), AnubisValue::Int(200)).as_bool() {
        if anubis_cmp("<=", anb_rat_cmp(i1.field_get("hi"), i2.field_get("lo")), AnubisValue::Int(0)).as_bool() {
            return anubis_mk_str("less".to_string());
        }
        if anubis_cmp("<=", anb_rat_cmp(i2.field_get("hi"), i1.field_get("lo")), AnubisValue::Int(0)).as_bool() {
            return anubis_mk_str("greater".to_string());
        }
        i1 = anb_sturm_refine(ch1.clone(), i1.clone());
        i2 = anb_sturm_refine(ch2.clone(), i2.clone());
        steps = anubis_add(steps.clone(), AnubisValue::Int(1));
    }
    anubis_panic(anubis_mk_str("alg-cmp: 200-bisection budget exhausted; fail closed (alg-cmp-budget)".to_string()))
}

fn anb_smallest_small_divisor(mut n: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", (anb_big_divmod_small(n.clone(), AnubisValue::Int(2))).field_get("remainder"), AnubisValue::Int(0)).as_bool() {
        return AnubisValue::Struct { ty: "SmallDiv".to_string(), fields: vec![("divisor".to_string(), anubis_field_require_int(AnubisValue::Int(2), "divisor")), ("found".to_string(), AnubisValue::Bool(true)), ("proven_prime".to_string(), AnubisValue::Bool(false))] };
    }
    let mut cap = anb_big_to_i64_or_neg(n.clone());
    let mut d = AnubisValue::Int(3);
    while anubis_cmp("<=", d.clone(), AnubisValue::Int(1000000)).as_bool() {
        if AnubisValue::Bool((anubis_cmp(">=", cap.clone(), AnubisValue::Int(0))).as_bool() && (anubis_cmp(">", anubis_mul(d.clone(), d.clone()), cap.clone())).as_bool()).as_bool() {
            return AnubisValue::Struct { ty: "SmallDiv".to_string(), fields: vec![("divisor".to_string(), anubis_field_require_int(AnubisValue::Int(0), "divisor")), ("found".to_string(), AnubisValue::Bool(false)), ("proven_prime".to_string(), AnubisValue::Bool(true))] };
        }
        if anubis_cmp("==", (anb_big_divmod_small(n.clone(), d.clone())).field_get("remainder"), AnubisValue::Int(0)).as_bool() {
            return AnubisValue::Struct { ty: "SmallDiv".to_string(), fields: vec![("divisor".to_string(), anubis_field_require_int(d.clone(), "divisor")), ("found".to_string(), AnubisValue::Bool(true)), ("proven_prime".to_string(), AnubisValue::Bool(false))] };
        }
        d = anubis_add(d.clone(), AnubisValue::Int(2));
    }
    return AnubisValue::Struct { ty: "SmallDiv".to_string(), fields: vec![("divisor".to_string(), anubis_field_require_int(AnubisValue::Int(0), "divisor")), ("found".to_string(), AnubisValue::Bool(false)), ("proven_prime".to_string(), AnubisValue::Bool(false))] };
    AnubisValue::Int(0)
}

fn anb_mr_is_probable_prime(mut n: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", anb_big_cmp(n.clone(), anubis_mk_list(vec![AnubisValue::Int(2)])), AnubisValue::Int(0)).as_bool() {
        return AnubisValue::Bool(false);
    }
    if AnubisValue::Bool((anubis_cmp("==", anb_big_cmp(n.clone(), anubis_mk_list(vec![AnubisValue::Int(2)])), AnubisValue::Int(0))).as_bool() || (anubis_cmp("==", anb_big_cmp(n.clone(), anubis_mk_list(vec![AnubisValue::Int(3)])), AnubisValue::Int(0))).as_bool()).as_bool() {
        return AnubisValue::Bool(true);
    }
    if anb_big_is_even(n.clone()).as_bool() {
        return AnubisValue::Bool(false);
    }
    let mut n1 = anb_big_sub(n.clone(), anubis_mk_list(vec![AnubisValue::Int(1)]));
    let mut d = n1.clone();
    let mut s = AnubisValue::Int(0);
    while anb_big_is_even(d.clone()).as_bool() {
        d = anb_big_half(d.clone());
        s = anubis_add(s.clone(), AnubisValue::Int(1));
    }
    let mut witnesses = anubis_mk_list(vec![AnubisValue::Int(2), AnubisValue::Int(3), AnubisValue::Int(5), AnubisValue::Int(7), AnubisValue::Int(11), AnubisValue::Int(13), AnubisValue::Int(17), AnubisValue::Int(19), AnubisValue::Int(23), AnubisValue::Int(29), AnubisValue::Int(31), AnubisValue::Int(37)]);
    let mut wi = AnubisValue::Int(0);
    while anubis_cmp("<", wi.clone(), (witnesses.clone()).len_val()).as_bool() {
        let mut ar = anb_big_mod(anb_big_from_small(witnesses.index_get(wi.clone())), n.clone());
        wi = anubis_add(wi.clone(), AnubisValue::Int(1));
        if anb_big_is_zero(ar.clone()).as_bool() {
            continue;
        }
        let mut x = anb_big_modpow(ar.clone(), d.clone(), n.clone());
        if AnubisValue::Bool((anubis_cmp("==", anb_big_cmp(x.clone(), anubis_mk_list(vec![AnubisValue::Int(1)])), AnubisValue::Int(0))).as_bool() || (anubis_cmp("==", anb_big_cmp(x.clone(), n1.clone()), AnubisValue::Int(0))).as_bool()).as_bool() {
            continue;
        }
        let mut r = AnubisValue::Int(1);
        let mut saw_minus_one = AnubisValue::Bool(false);
        while anubis_cmp("<", r.clone(), s.clone()).as_bool() {
            x = anb_big_mod(anb_big_mul(x.clone(), x.clone()), n.clone());
            if anubis_cmp("==", anb_big_cmp(x.clone(), n1.clone()), AnubisValue::Int(0)).as_bool() {
                saw_minus_one = AnubisValue::Bool(true);
                break;
            }
            r = anubis_add(r.clone(), AnubisValue::Int(1));
        }
        if AnubisValue::Bool(!(saw_minus_one.clone()).as_bool()).as_bool() {
            return AnubisValue::Bool(false);
        }
    }
    return AnubisValue::Bool(true);
    AnubisValue::Int(0)
}

fn anb_pollard_rho(mut n: AnubisValue, mut budget_start: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut used = budget_start.clone();
    let mut c = AnubisValue::Int(1);
    while anubis_cmp("<=", c.clone(), AnubisValue::Int(20)).as_bool() {
        let mut cb = anb_big_from_small(c.clone());
        let mut y = anubis_mk_list(vec![AnubisValue::Int(2)]);
        let mut r = AnubisValue::Int(1);
        let mut q = anubis_mk_list(vec![AnubisValue::Int(1)]);
        let mut g = anubis_mk_list(vec![AnubisValue::Int(1)]);
        let mut x = anubis_mk_list(vec![AnubisValue::Int(2)]);
        let mut ys = anubis_mk_list(vec![AnubisValue::Int(2)]);
        while anubis_cmp("==", anb_big_cmp(g.clone(), anubis_mk_list(vec![AnubisValue::Int(1)])), AnubisValue::Int(0)).as_bool() {
            x = y.clone();
            let mut i = AnubisValue::Int(0);
            while anubis_cmp("<", i.clone(), r.clone()).as_bool() {
                y = anb_big_mod(anb_big_add(anb_big_mod(anb_big_mul(y.clone(), y.clone()), n.clone()), cb.clone()), n.clone());
                i = anubis_add(i.clone(), AnubisValue::Int(1));
            }
            used = anubis_add(used.clone(), r.clone());
            if anubis_cmp(">", used.clone(), AnubisValue::Int(200000)).as_bool() {
                return AnubisValue::Struct { ty: "RhoResult".to_string(), fields: vec![("divisor".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)])), ("ok".to_string(), AnubisValue::Bool(false)), ("used".to_string(), anubis_field_require_int(used.clone(), "used"))] };
            }
            let mut k = AnubisValue::Int(0);
            while AnubisValue::Bool((anubis_cmp("<", k.clone(), r.clone())).as_bool() && (anubis_cmp("==", anb_big_cmp(g.clone(), anubis_mk_list(vec![AnubisValue::Int(1)])), AnubisValue::Int(0))).as_bool()).as_bool() {
                ys = y.clone();
                let mut lim = AnubisValue::Int(128);
                if anubis_cmp("<", anubis_sub(r.clone(), k.clone()), lim.clone()).as_bool() {
                    lim = anubis_sub(r.clone(), k.clone());
                }
                let mut j = AnubisValue::Int(0);
                while anubis_cmp("<", j.clone(), lim.clone()).as_bool() {
                    y = anb_big_mod(anb_big_add(anb_big_mod(anb_big_mul(y.clone(), y.clone()), n.clone()), cb.clone()), n.clone());
                    let mut diff = anb_big_diff(x.clone(), y.clone());
                    if AnubisValue::Bool(!(anb_big_is_zero(diff.clone())).as_bool()).as_bool() {
                        q = anb_big_mod(anb_big_mul(q.clone(), diff.clone()), n.clone());
                    }
                    j = anubis_add(j.clone(), AnubisValue::Int(1));
                }
                g = anb_big_gcd(q.clone(), n.clone());
                k = anubis_add(k.clone(), lim.clone());
                used = anubis_add(used.clone(), lim.clone());
                if anubis_cmp(">", used.clone(), AnubisValue::Int(200000)).as_bool() {
                    return AnubisValue::Struct { ty: "RhoResult".to_string(), fields: vec![("divisor".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)])), ("ok".to_string(), AnubisValue::Bool(false)), ("used".to_string(), anubis_field_require_int(used.clone(), "used"))] };
                }
            }
            r = anubis_mul(r.clone(), AnubisValue::Int(2));
        }
        if anubis_cmp("==", anb_big_cmp(g.clone(), n.clone()), AnubisValue::Int(0)).as_bool() {
            g = anubis_mk_list(vec![AnubisValue::Int(1)]);
            while anubis_cmp("==", anb_big_cmp(g.clone(), anubis_mk_list(vec![AnubisValue::Int(1)])), AnubisValue::Int(0)).as_bool() {
                ys = anb_big_mod(anb_big_add(anb_big_mod(anb_big_mul(ys.clone(), ys.clone()), n.clone()), cb.clone()), n.clone());
                let mut diff = anb_big_diff(x.clone(), ys.clone());
                if anb_big_is_zero(diff.clone()).as_bool() {
                    break;
                }
                g = anb_big_gcd(diff.clone(), n.clone());
                used = anubis_add(used.clone(), AnubisValue::Int(1));
                if anubis_cmp(">", used.clone(), AnubisValue::Int(200000)).as_bool() {
                    return AnubisValue::Struct { ty: "RhoResult".to_string(), fields: vec![("divisor".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)])), ("ok".to_string(), AnubisValue::Bool(false)), ("used".to_string(), anubis_field_require_int(used.clone(), "used"))] };
                }
            }
        }
        if AnubisValue::Bool((anubis_cmp(">", anb_big_cmp(g.clone(), anubis_mk_list(vec![AnubisValue::Int(1)])), AnubisValue::Int(0))).as_bool() && (anubis_cmp("<", anb_big_cmp(g.clone(), n.clone()), AnubisValue::Int(0))).as_bool()).as_bool() {
            return AnubisValue::Struct { ty: "RhoResult".to_string(), fields: vec![("divisor".to_string(), g.clone()), ("ok".to_string(), AnubisValue::Bool(true)), ("used".to_string(), anubis_field_require_int(used.clone(), "used"))] };
        }
        c = anubis_add(c.clone(), AnubisValue::Int(1));
    }
    return AnubisValue::Struct { ty: "RhoResult".to_string(), fields: vec![("divisor".to_string(), anubis_mk_list(vec![AnubisValue::Int(1)])), ("ok".to_string(), AnubisValue::Bool(false)), ("used".to_string(), anubis_field_require_int(used.clone(), "used"))] };
    AnubisValue::Int(0)
}

fn anb_sort_bigs(mut xs: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut i = AnubisValue::Int(1);
    while anubis_cmp("<", i.clone(), (xs.clone()).len_val()).as_bool() {
        let mut j = i.clone();
        while AnubisValue::Bool((anubis_cmp(">", j.clone(), AnubisValue::Int(0))).as_bool() && (anubis_cmp(">", anb_big_cmp(xs.index_get(anubis_sub(j.clone(), AnubisValue::Int(1))), xs.index_get(j.clone())), AnubisValue::Int(0))).as_bool()).as_bool() {
            let mut tmp = xs.index_get(anubis_sub(j.clone(), AnubisValue::Int(1)));
            xs.set_at(&[AnubisPathSeg::Index(anubis_sub(j.clone(), AnubisValue::Int(1)))], xs.index_get(j.clone()));
            xs.set_at(&[AnubisPathSeg::Index(j.clone())], tmp.clone());
            j = anubis_sub(j.clone(), AnubisValue::Int(1));
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return xs.clone();
    AnubisValue::Int(0)
}

fn anb_factor_grouped(mut m: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", anb_big_cmp(m.clone(), anubis_mk_list(vec![AnubisValue::Int(2)])), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("prime-cert: internal factor target below 2; fail closed".to_string()));
    }
    let mut primes = anubis_mk_list(vec![]);
    let mut rest = m.clone();
    while anb_big_is_even(rest.clone()).as_bool() {
        primes.push_val(anubis_mk_list(vec![AnubisValue::Int(2)]));
        rest = anb_big_half(rest.clone());
    }
    let mut d = AnubisValue::Int(3);
    while AnubisValue::Bool((anubis_cmp("<=", d.clone(), AnubisValue::Int(1000000))).as_bool() && (anubis_cmp("!=", anb_big_cmp(rest.clone(), anubis_mk_list(vec![AnubisValue::Int(1)])), AnubisValue::Int(0))).as_bool()).as_bool() {
        let mut cap = anb_big_to_i64_or_neg(rest.clone());
        if AnubisValue::Bool((anubis_cmp(">=", cap.clone(), AnubisValue::Int(0))).as_bool() && (anubis_cmp(">", anubis_mul(d.clone(), d.clone()), cap.clone())).as_bool()).as_bool() {
            break;
        }
        let mut dm = anb_big_divmod_small(rest.clone(), d.clone());
        if anubis_cmp("==", dm.field_get("remainder"), AnubisValue::Int(0)).as_bool() {
            primes.push_val(anb_big_from_small(d.clone()));
            rest = dm.field_get("quotient");
        } else {
            d = anubis_add(d.clone(), AnubisValue::Int(2));
        }
    }
    if anubis_cmp("!=", anb_big_cmp(rest.clone(), anubis_mk_list(vec![AnubisValue::Int(1)])), AnubisValue::Int(0)).as_bool() {
        let mut stack = anubis_mk_list(vec![rest.clone()]);
        let mut budget = AnubisValue::Int(0);
        let mut rounds = AnubisValue::Int(0);
        while anubis_cmp(">", (stack.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
            rounds = anubis_add(rounds.clone(), AnubisValue::Int(1));
            if anubis_cmp(">", rounds.clone(), AnubisValue::Int(128)).as_bool() {
                let _ = anubis_panic(anubis_mk_str("prime-cert: factoring exceeded its budget; fail closed (prime-cert-budget)".to_string()));
            }
            let mut f = stack.index_get(anubis_sub((stack.clone()).len_val(), AnubisValue::Int(1)));
            let _ = anubis_pop(&mut stack);
            if anb_mr_is_probable_prime(f.clone()).as_bool() {
                primes.push_val(f.clone());
                continue;
            }
            let mut rho = anb_pollard_rho(f.clone(), budget.clone());
            budget = rho.field_get("used");
            if AnubisValue::Bool(!(rho.field_get("ok")).as_bool()).as_bool() {
                let _ = anubis_panic(anubis_mk_str("prime-cert: factoring exceeded its budget; fail closed (prime-cert-budget)".to_string()));
            }
            let mut d1 = rho.field_get("divisor");
            let mut dm2 = anb_big_divmod(f.clone(), d1.clone());
            if AnubisValue::Bool(!(anb_big_is_zero(dm2.field_get("remainder"))).as_bool()).as_bool() {
                let _ = anubis_panic(anubis_mk_str("prime-cert: internal rho divisor invariant violated; fail closed".to_string()));
            }
            stack.push_val(d1.clone());
            stack.push_val(dm2.field_get("quotient"));
        }
    }
    let mut sorted = anb_sort_bigs(primes.clone());
    let mut grouped = anubis_mk_list(vec![]);
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (sorted.clone()).len_val()).as_bool() {
        let mut q = sorted.index_get(i.clone());
        let mut e = AnubisValue::Int(1);
        while AnubisValue::Bool((anubis_cmp("<", anubis_add(i.clone(), AnubisValue::Int(1)), (sorted.clone()).len_val())).as_bool() && (anubis_cmp("==", anb_big_cmp(sorted.index_get(anubis_add(i.clone(), AnubisValue::Int(1))), q.clone()), AnubisValue::Int(0))).as_bool()).as_bool() {
            e = anubis_add(e.clone(), AnubisValue::Int(1));
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        grouped.push_val(AnubisValue::Struct { ty: "FactorPair".to_string(), fields: vec![("q".to_string(), q.clone()), ("e".to_string(), anubis_field_require_int(e.clone(), "e"))] });
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return grouped.clone();
    AnubisValue::Int(0)
}

fn anb_find_divisor(mut n: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut sd = anb_smallest_small_divisor(n.clone());
    if sd.field_get("found").as_bool() {
        return anb_big_from_small(sd.field_get("divisor"));
    }
    if sd.field_get("proven_prime").as_bool() {
        let _ = anubis_panic(anubis_mk_str("prime-cert: internal contradiction (screen says composite, trial says prime); fail closed".to_string()));
    }
    let mut rho = anb_pollard_rho(n.clone(), AnubisValue::Int(0));
    if AnubisValue::Bool(!(rho.field_get("ok")).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("prime-cert: could not exhibit a divisor within budget; fail closed (prime-cert-budget)".to_string()));
    }
    return rho.field_get("divisor");
    AnubisValue::Int(0)
}

fn anb_find_pratt_witness(mut n: AnubisValue, mut n1: AnubisValue, mut fs: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut a = AnubisValue::Int(2);
    while anubis_cmp("<=", a.clone(), AnubisValue::Int(201)).as_bool() {
        let mut ab = anb_big_mod(anb_big_from_small(a.clone()), n.clone());
        if AnubisValue::Bool(!(anb_big_is_zero(ab.clone())).as_bool()).as_bool() {
            if anubis_cmp("==", anb_big_cmp(anb_big_modpow(ab.clone(), n1.clone(), n.clone()), anubis_mk_list(vec![AnubisValue::Int(1)])), AnubisValue::Int(0)).as_bool() {
                let mut ok = AnubisValue::Bool(true);
                let mut i = AnubisValue::Int(0);
                while anubis_cmp("<", i.clone(), (fs.clone()).len_val()).as_bool() {
                    let mut fp = fs.index_get(i.clone());
                    let mut t = (anb_big_divmod(n1.clone(), fp.field_get("q"))).field_get("quotient");
                    if anubis_cmp("==", anb_big_cmp(anb_big_modpow(ab.clone(), t.clone(), n.clone()), anubis_mk_list(vec![AnubisValue::Int(1)])), AnubisValue::Int(0)).as_bool() {
                        ok = AnubisValue::Bool(false);
                        break;
                    }
                    i = anubis_add(i.clone(), AnubisValue::Int(1));
                }
                if ok.clone().as_bool() {
                    return a.clone();
                }
            }
        }
        a = anubis_add(a.clone(), AnubisValue::Int(1));
    }
    anubis_panic(anubis_mk_str("prime-cert: witness search exhausted 200 candidates; fail closed (prime-cert-budget)".to_string()))
}

fn anb_pratt_build(mut n: AnubisValue, mut depth: AnubisValue, mut nodes_before: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp(">", depth.clone(), AnubisValue::Int(64)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("prime-cert: Pratt recursion exceeded depth 64; fail closed (prime-cert-budget)".to_string()));
    }
    let mut nodes = anubis_add(nodes_before.clone(), AnubisValue::Int(1));
    if anubis_cmp(">", nodes.clone(), AnubisValue::Int(512)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("prime-cert: Pratt tree exceeded 512 nodes; fail closed (prime-cert-budget)".to_string()));
    }
    if anubis_cmp("<=", anb_big_cmp(n.clone(), anubis_mk_list(vec![AnubisValue::Int(3)])), AnubisValue::Int(0)).as_bool() {
        return AnubisValue::Struct { ty: "PrattBuild".to_string(), fields: vec![("json".to_string(), anubis_mk_str("{\"a\":\"1\",\"factors\":[]}".to_string())), ("nodes".to_string(), anubis_field_require_int(nodes.clone(), "nodes"))] };
    }
    let mut n1 = anb_big_sub(n.clone(), anubis_mk_list(vec![AnubisValue::Int(1)]));
    let mut fs = anb_factor_grouped(n1.clone());
    let mut a_val = anb_find_pratt_witness(n.clone(), n1.clone(), fs.clone());
    let mut parts = anubis_mk_str("".to_string());
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (fs.clone()).len_val()).as_bool() {
        let mut fp = fs.index_get(i.clone());
        let mut qb = fp.field_get("q");
        let mut sub_json = anubis_mk_str("null".to_string());
        if anubis_cmp("!=", anb_big_cmp(qb.clone(), anubis_mk_list(vec![AnubisValue::Int(2)])), AnubisValue::Int(0)).as_bool() {
            let mut child = anb_pratt_build(qb.clone(), anubis_add(depth.clone(), AnubisValue::Int(1)), nodes.clone());
            let mut cj = child.field_get("json");
            nodes = child.field_get("nodes");
            sub_json = cj.clone();
        }
        if anubis_cmp(">", i.clone(), AnubisValue::Int(0)).as_bool() {
            parts = anubis_add(parts.clone(), anubis_mk_str(",".to_string()));
        }
        parts = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(parts.clone(), anubis_mk_str("{\"cert\":".to_string())), sub_json.clone()), anubis_mk_str(",\"e\":\"".to_string())), anubis_str(fp.field_get("e"))), anubis_mk_str("\",\"q\":\"".to_string())), anb_big_to_text(qb.clone())), anubis_mk_str("\"}".to_string()));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return AnubisValue::Struct { ty: "PrattBuild".to_string(), fields: vec![("json".to_string(), anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{\"a\":\"".to_string()), anubis_str(a_val.clone())), anubis_mk_str("\",\"factors\":[".to_string())), parts.clone()), anubis_mk_str("]}".to_string()))), ("nodes".to_string(), anubis_field_require_int(nodes.clone(), "nodes"))] };
    AnubisValue::Int(0)
}

fn anb_cmd_canon(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
    let mut sexp = anb_ast_sexp(anb_parse_ast(argv.index_get(AnubisValue::Int(1))));
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact canonical=".to_string())), sexp.clone()), anubis_mk_str(" sha256=".to_string())), anubis_sha256(sexp.clone())).display_string());
    AnubisValue::Int(0)
}

fn anb_cmd_xgcd(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
    let mut a = anb_int_from_text(argv.index_get(AnubisValue::Int(1)));
    let mut b = anb_int_from_text(argv.index_get(AnubisValue::Int(2)));
    let mut x = anb_int_xgcd(a.clone(), b.clone());
    let mut gt = anb_int_to_text(x.field_get("g"));
    let mut ut = anb_int_to_text(x.field_get("u"));
    let mut vt = anb_int_to_text(x.field_get("v"));
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact g=".to_string())), gt.clone()), anubis_mk_str(" u=".to_string())), ut.clone()), anubis_mk_str(" v=".to_string())), vt.clone()).display_string());
    let mut claim = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("a".to_string()), anb_jstr(anb_int_to_text(a.clone())))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("b".to_string()), anb_jstr(anb_int_to_text(b.clone())))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("g".to_string()), anb_jstr(gt.clone()))), anubis_mk_str("}".to_string()));
    let mut witness = anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("u".to_string()), anb_jstr(ut.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("v".to_string()), anb_jstr(vt.clone()))), anubis_mk_str("}".to_string()));
    println!("{}", anb_cert_envelope(anubis_mk_str("xgcd".to_string()), claim.clone(), witness.clone()).display_string());
    AnubisValue::Int(0)
}

fn anb_cmd_mod_pow(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(4));
    let mut base = anb_int_from_text(argv.index_get(AnubisValue::Int(1)));
    let mut exponent = anb_int_from_text(argv.index_get(AnubisValue::Int(2)));
    let mut modulus = anb_int_from_text(argv.index_get(AnubisValue::Int(3)));
    let mut r = anb_int_modpow(base.clone(), exponent.clone(), modulus.clone());
    let mut rt = anb_int_to_text(r.clone());
    println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact r=".to_string())), rt.clone()).display_string());
    let mut claim = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("base".to_string()), anb_jstr(anb_int_to_text(base.clone())))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("exp".to_string()), anb_jstr(anb_int_to_text(exponent.clone())))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("mod".to_string()), anb_jstr(anb_int_to_text(modulus.clone())))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("r".to_string()), anb_jstr(rt.clone()))), anubis_mk_str("}".to_string()));
    println!("{}", anb_cert_envelope(anubis_mk_str("mod-pow".to_string()), claim.clone(), anubis_mk_str("{}".to_string())).display_string());
    AnubisValue::Int(0)
}

fn anb_require_abs_representable(mut value: AnubisValue, mut name: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", value.clone(), anubis_neg(AnubisValue::Int(9223372036854775808u64 as i64))).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("int-min-unrepresentable: ".to_string())), name.clone()), anubis_mk_str(" is i64::MIN, whose magnitude is not representable in i64; fail closed".to_string())));
    }
    AnubisValue::Int(0)
}

fn anb_require_hex64(mut text: AnubisValue, mut name: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("!=", (text.clone()).len_val(), AnubisValue::Int(64)).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-hex64: ".to_string())), name.clone()), anubis_mk_str(" must be exactly 64 hex digits; fail closed".to_string())));
    }
    let mut safe = anubis_mk_str("0123456789abcdef".to_string());
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (text.clone()).len_val()).as_bool() {
        if AnubisValue::Bool(!(anb_char_in(safe.clone(), (text.clone()).index_get(i.clone()))).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-hex64: ".to_string())), name.clone()), anubis_mk_str(" contains a non-lowercase-hex byte; fail closed".to_string())));
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    AnubisValue::Int(0)
}

fn anb_require_relpath(mut text: AnubisValue, mut name: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", (text.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-path: ".to_string())), name.clone()), anubis_mk_str(" must not be empty; fail closed".to_string())));
    }
    if anubis_cmp(">", (text.clone()).len_val(), AnubisValue::Int(512)).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-path: ".to_string())), name.clone()), anubis_mk_str(" exceeds 512 bytes; fail closed".to_string())));
    }
    if anubis_cmp("==", (text.clone()).index_get(AnubisValue::Int(0)), anubis_mk_str("/".to_string())).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-path: ".to_string())), name.clone()), anubis_mk_str(" must be repository-relative; fail closed".to_string())));
    }
    let mut safe = anubis_mk_str("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/".to_string());
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (text.clone()).len_val()).as_bool() {
        if AnubisValue::Bool(!(anb_char_in(safe.clone(), (text.clone()).index_get(i.clone()))).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-path: ".to_string())), name.clone()), anubis_mk_str(" contains a byte outside the safe path charset; fail closed".to_string())));
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    let mut j = AnubisValue::Int(0);
    while anubis_cmp("<", anubis_add(j.clone(), AnubisValue::Int(1)), (text.clone()).len_val()).as_bool() {
        if anubis_cmp("==", (text.clone()).index_get(j.clone()), anubis_mk_str(".".to_string())).as_bool() {
            if anubis_cmp("==", (text.clone()).index_get(anubis_add(j.clone(), AnubisValue::Int(1))), anubis_mk_str(".".to_string())).as_bool() {
                let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-path: ".to_string())), name.clone()), anubis_mk_str(" must not contain a parent traversal; fail closed".to_string())));
            }
        }
        j = anubis_add(j.clone(), AnubisValue::Int(1));
    }
    AnubisValue::Int(0)
}

fn anb_require_symbol(mut text: AnubisValue, mut name: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", (text.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-symbol: ".to_string())), name.clone()), anubis_mk_str(" must not be empty; fail closed".to_string())));
    }
    if anubis_cmp(">", (text.clone()).len_val(), AnubisValue::Int(256)).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-symbol: ".to_string())), name.clone()), anubis_mk_str(" exceeds 256 bytes; fail closed".to_string())));
    }
    let mut safe = anubis_mk_str("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_".to_string());
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (text.clone()).len_val()).as_bool() {
        if AnubisValue::Bool(!(anb_char_in(safe.clone(), (text.clone()).index_get(i.clone()))).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-symbol: ".to_string())), name.clone()), anubis_mk_str(" contains a byte outside [A-Za-z0-9_]; fail closed".to_string())));
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    AnubisValue::Int(0)
}

fn anb_require_canonical_uint(mut text: AnubisValue, mut name: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", (text.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-uint: ".to_string())), name.clone()), anubis_mk_str(" must not be empty; fail closed".to_string())));
    }
    if anubis_cmp(">", (text.clone()).len_val(), AnubisValue::Int(18)).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-uint: ".to_string())), name.clone()), anubis_mk_str(" exceeds the 18-digit budget; fail closed".to_string())));
    }
    let mut digits = anubis_mk_str("0123456789".to_string());
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (text.clone()).len_val()).as_bool() {
        if AnubisValue::Bool(!(anb_char_in(digits.clone(), (text.clone()).index_get(i.clone()))).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-uint: ".to_string())), name.clone()), anubis_mk_str(" is not a canonical decimal integer; fail closed".to_string())));
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    if anubis_cmp(">", (text.clone()).len_val(), AnubisValue::Int(1)).as_bool() {
        if anubis_cmp("==", (text.clone()).index_get(AnubisValue::Int(0)), anubis_mk_str("0".to_string())).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-uint: ".to_string())), name.clone()), anubis_mk_str(" has a leading zero; fail closed".to_string())));
        }
    }
    AnubisValue::Int(0)
}

fn anb_require_quotable_text(mut text: AnubisValue, mut name: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", (text.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-text: ".to_string())), name.clone()), anubis_mk_str(" must not be empty; fail closed".to_string())));
    }
    if anubis_cmp(">", (text.clone()).len_val(), AnubisValue::Int(2048)).as_bool() {
        let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-text: ".to_string())), name.clone()), anubis_mk_str(" exceeds 2048 bytes; fail closed".to_string())));
    }
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (text.clone()).len_val()).as_bool() {
        let mut c = (text.clone()).index_get(i.clone());
        if anubis_cmp("==", c.clone(), anubis_mk_str("\"".to_string())).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-text: ".to_string())), name.clone()), anubis_mk_str(" contains a double quote; fail closed".to_string())));
        }
        if anubis_cmp("==", c.clone(), anubis_mk_str("\\".to_string())).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("prog-text: ".to_string())), name.clone()), anubis_mk_str(" contains a backslash; fail closed".to_string())));
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    AnubisValue::Int(0)
}

fn anb_test_exists_envelope(mut kind: AnubisValue, mut claim_json: AnubisValue, mut witness_json: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("test-exists-cert={\"claim\":".to_string()), claim_json.clone()), anubis_mk_str(",\"kind\":\"".to_string())), kind.clone()), anubis_mk_str("\",\"schema\":\"jackal-test-exists-cert-v1\",\"witness\":".to_string())), witness_json.clone()), anubis_mk_str("}".to_string()));
    AnubisValue::Int(0)
}

fn anb_cmd_test_exists(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(6));
    let mut file_path = argv.index_get(AnubisValue::Int(1));
    let mut file_sha256 = argv.index_get(AnubisValue::Int(2));
    let mut symbol = argv.index_get(AnubisValue::Int(3));
    let mut declaration_line = argv.index_get(AnubisValue::Int(4));
    let mut declaration_count = argv.index_get(AnubisValue::Int(5));
    let _ = anb_require_relpath(file_path.clone(), anubis_mk_str("file_path".to_string()));
    let _ = anb_require_hex64(file_sha256.clone(), anubis_mk_str("file_sha256".to_string()));
    let _ = anb_require_symbol(symbol.clone(), anubis_mk_str("symbol".to_string()));
    let _ = anb_require_canonical_uint(declaration_line.clone(), anubis_mk_str("declaration_line".to_string()));
    let _ = anb_require_canonical_uint(declaration_count.clone(), anubis_mk_str("declaration_count".to_string()));
    if anubis_cmp("==", declaration_line.clone(), anubis_mk_str("0".to_string())).as_bool() {
        let _ = anubis_panic(anubis_mk_str("prog-uint: declaration_line is 1-based and must not be 0; fail closed".to_string()));
    }
    if anubis_cmp("==", declaration_count.clone(), anubis_mk_str("0".to_string())).as_bool() {
        let _ = anubis_panic(anubis_mk_str("prog-absent: declaration_count is 0, which is an absence, not an existence claim; fail closed".to_string()));
    }
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=structural-exact symbol=".to_string())), symbol.clone()), anubis_mk_str(" line=".to_string())), declaration_line.clone()), anubis_mk_str(" count=".to_string())), declaration_count.clone()).display_string());
    println!("{}", anubis_mk_str("consequence=informational note=a-test-existing-is-not-evidence-the-code-is-correct".to_string()).display_string());
    let mut claim = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("declaration_count".to_string()), anb_jstr(declaration_count.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("declaration_line".to_string()), anb_jstr(declaration_line.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("file_path".to_string()), anb_jstr(file_path.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("file_sha256".to_string()), anb_jstr(file_sha256.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("symbol".to_string()), anb_jstr(symbol.clone()))), anubis_mk_str("}".to_string()));
    println!("{}", anb_test_exists_envelope(anubis_mk_str("test-exists".to_string()), claim.clone(), anubis_mk_str("{}".to_string())).display_string());
    AnubisValue::Int(0)
}

fn anb_cmd_claim_cites_test(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(7));
    let mut doc_path = argv.index_get(AnubisValue::Int(1));
    let mut doc_sha256 = argv.index_get(AnubisValue::Int(2));
    let mut claim_text = argv.index_get(AnubisValue::Int(3));
    let mut test_path = argv.index_get(AnubisValue::Int(4));
    let mut test_sha256 = argv.index_get(AnubisValue::Int(5));
    let mut symbol = argv.index_get(AnubisValue::Int(6));
    let _ = anb_require_relpath(doc_path.clone(), anubis_mk_str("doc_path".to_string()));
    let _ = anb_require_hex64(doc_sha256.clone(), anubis_mk_str("doc_sha256".to_string()));
    let _ = anb_require_quotable_text(claim_text.clone(), anubis_mk_str("claim_text".to_string()));
    let _ = anb_require_relpath(test_path.clone(), anubis_mk_str("test_path".to_string()));
    let _ = anb_require_hex64(test_sha256.clone(), anubis_mk_str("test_sha256".to_string()));
    let _ = anb_require_symbol(symbol.clone(), anubis_mk_str("symbol".to_string()));
    println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=structural-exact cited_symbol=".to_string())), symbol.clone()).display_string());
    println!("{}", anubis_mk_str("consequence=informational note=citation-resolves-it-does-not-establish-the-cited-test-covers-the-claim".to_string()).display_string());
    let mut claim = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("claim_text".to_string()), anb_jstr(claim_text.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("doc_path".to_string()), anb_jstr(doc_path.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("doc_sha256".to_string()), anb_jstr(doc_sha256.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("symbol".to_string()), anb_jstr(symbol.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("test_path".to_string()), anb_jstr(test_path.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("test_sha256".to_string()), anb_jstr(test_sha256.clone()))), anubis_mk_str("}".to_string()));
    println!("{}", anb_test_exists_envelope(anubis_mk_str("claim-cites-test".to_string()), claim.clone(), anubis_mk_str("{}".to_string())).display_string());
    AnubisValue::Int(0)
}

fn anb_ascii_lower(mut text: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut upper = anubis_mk_str("ABCDEFGHIJKLMNOPQRSTUVWXYZ".to_string());
    let mut lower = anubis_mk_str("abcdefghijklmnopqrstuvwxyz".to_string());
    let mut out = anubis_mk_str("".to_string());
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (text.clone()).len_val()).as_bool() {
        let mut c = (text.clone()).index_get(i.clone());
        let mut j = AnubisValue::Int(0);
        let mut mapped = c.clone();
        while anubis_cmp("<", j.clone(), (upper.clone()).len_val()).as_bool() {
            if anubis_cmp("==", c.clone(), (upper.clone()).index_get(j.clone())).as_bool() {
                mapped = (lower.clone()).index_get(j.clone());
            }
            j = anubis_add(j.clone(), AnubisValue::Int(1));
        }
        out = anubis_add(out.clone(), mapped.clone());
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    return out.clone();
    AnubisValue::Int(0)
}

fn anb_text_contains(mut haystack: AnubisValue, mut needle: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("==", (needle.clone()).len_val(), AnubisValue::Int(0)).as_bool() {
        return AnubisValue::Bool(true);
    }
    if anubis_cmp(">", (needle.clone()).len_val(), (haystack.clone()).len_val()).as_bool() {
        return AnubisValue::Bool(false);
    }
    let mut start = AnubisValue::Int(0);
    while anubis_cmp("<=", anubis_add(start.clone(), (needle.clone()).len_val()), (haystack.clone()).len_val()).as_bool() {
        let mut k = AnubisValue::Int(0);
        let mut matched = AnubisValue::Bool(true);
        while anubis_cmp("<", k.clone(), (needle.clone()).len_val()).as_bool() {
            if anubis_cmp("!=", (haystack.clone()).index_get(anubis_add(start.clone(), k.clone())), (needle.clone()).index_get(k.clone())).as_bool() {
                matched = AnubisValue::Bool(false);
                k = (needle.clone()).len_val();
            } else {
                k = anubis_add(k.clone(), AnubisValue::Int(1));
            }
        }
        if matched.clone().as_bool() {
            return AnubisValue::Bool(true);
        }
        start = anubis_add(start.clone(), AnubisValue::Int(1));
    }
    return AnubisValue::Bool(false);
    AnubisValue::Int(0)
}

fn anb_require_measurable_criterion(mut criterion: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let mut lowered = anb_ascii_lower(criterion.clone());
    let mut banned = anubis_mk_list(vec![anubis_mk_str("better".to_string()), anubis_mk_str("best".to_string()), anubis_mk_str("worse".to_string()), anubis_mk_str("worst".to_string()), anubis_mk_str("good".to_string()), anubis_mk_str("bad".to_string()), anubis_mk_str("should".to_string()), anubis_mk_str("prefer".to_string()), anubis_mk_str("worth".to_string()), anubis_mk_str("moral".to_string()), anubis_mk_str("ethical".to_string()), anubis_mk_str("fair".to_string()), anubis_mk_str("right".to_string()), anubis_mk_str("wrong".to_string()), anubis_mk_str("beauty".to_string()), anubis_mk_str("nicer".to_string()), anubis_mk_str("nicest".to_string()), anubis_mk_str("superior".to_string()), anubis_mk_str("inferior".to_string()), anubis_mk_str("ought".to_string())]);
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (banned.clone()).len_val()).as_bool() {
        if anb_text_contains(lowered.clone(), banned.index_get(i.clone())).as_bool() {
            let _ = anubis_panic(anubis_mk_str("decision-value-judgment: criterion names a value judgment, not a measurable quantity; fail closed".to_string()));
        }
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    AnubisValue::Int(0)
}

fn anb_decision_envelope(mut claim_json: AnubisValue, mut witness_json: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    return anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("decision-cert={\"claim\":".to_string()), claim_json.clone()), anubis_mk_str(",\"kind\":\"decision-rank\",\"schema\":\"jackal-decision-cert-v1\",\"witness\":".to_string())), witness_json.clone()), anubis_mk_str("}".to_string()));
    AnubisValue::Int(0)
}

fn anb_cmd_decision_rank(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", (argv.clone()).len_val(), AnubisValue::Int(8)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("pack-request-arity: decision-rank requires an id, a criterion, a sense, and at least two label/value pairs; fail closed".to_string()));
    }
    if anubis_cmp(">", (argv.clone()).len_val(), AnubisValue::Int(16)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("pack-request-arity: decision-rank accepts at most 6 options; fail closed".to_string()));
    }
    if anubis_cmp("!=", anubis_mod(anubis_sub((argv.clone()).len_val(), AnubisValue::Int(4)), AnubisValue::Int(2)), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("pack-request-arity: decision-rank requires label/value pairs; fail closed".to_string()));
    }
    let mut decision_id = argv.index_get(AnubisValue::Int(1));
    let mut criterion = argv.index_get(AnubisValue::Int(2));
    let mut sense = argv.index_get(AnubisValue::Int(3));
    let _ = anb_require_symbol(decision_id.clone(), anubis_mk_str("decision_id".to_string()));
    let _ = anb_require_symbol(criterion.clone(), anubis_mk_str("criterion".to_string()));
    let _ = anb_require_measurable_criterion(criterion.clone());
    if anubis_cmp("!=", sense.clone(), anubis_mk_str("max".to_string())).as_bool() {
        if anubis_cmp("!=", sense.clone(), anubis_mk_str("min".to_string())).as_bool() {
            let _ = anubis_panic(anubis_mk_str("decision-sense-unknown: sense must be exactly \"max\" or \"min\"; fail closed".to_string()));
        }
    }
    let mut labels = anubis_mk_list(vec![]);
    let mut values = anubis_mk_list(vec![]);
    let mut i = AnubisValue::Int(4);
    while anubis_cmp("<", i.clone(), (argv.clone()).len_val()).as_bool() {
        let mut label = argv.index_get(i.clone());
        let mut raw = argv.index_get(anubis_add(i.clone(), AnubisValue::Int(1)));
        let _ = anb_require_symbol(label.clone(), anubis_mk_str("option_label".to_string()));
        let mut j = AnubisValue::Int(0);
        while anubis_cmp("<", j.clone(), (labels.clone()).len_val()).as_bool() {
            if anubis_cmp("==", labels.index_get(j.clone()), label.clone()).as_bool() {
                let _ = anubis_panic(anubis_mk_str("decision-duplicate-label: option labels must be distinct; fail closed".to_string()));
            }
            j = anubis_add(j.clone(), AnubisValue::Int(1));
        }
        labels.push_val(label.clone());
        values.push_val(anb_int_from_text(raw.clone()));
        i = anubis_add(i.clone(), AnubisValue::Int(2));
    }
    let mut best = AnubisValue::Int(0);
    let mut k = AnubisValue::Int(1);
    while anubis_cmp("<", k.clone(), (labels.clone()).len_val()).as_bool() {
        if anubis_cmp("==", sense.clone(), anubis_mk_str("max".to_string())).as_bool() {
            if anubis_cmp(">", anb_int_cmp(values.index_get(k.clone()), values.index_get(best.clone())), AnubisValue::Int(0)).as_bool() {
                best = k.clone();
            }
        } else {
            if anubis_cmp(">", anb_int_cmp(values.index_get(best.clone()), values.index_get(k.clone())), AnubisValue::Int(0)).as_bool() {
                best = k.clone();
            }
        }
        k = anubis_add(k.clone(), AnubisValue::Int(1));
    }
    let mut runner = anubis_neg(AnubisValue::Int(1));
    let mut m = AnubisValue::Int(0);
    while anubis_cmp("<", m.clone(), (labels.clone()).len_val()).as_bool() {
        if anubis_cmp("!=", m.clone(), best.clone()).as_bool() {
            if anubis_cmp("==", runner.clone(), anubis_neg(AnubisValue::Int(1))).as_bool() {
                runner = m.clone();
            } else {
                if anubis_cmp("==", sense.clone(), anubis_mk_str("max".to_string())).as_bool() {
                    if anubis_cmp(">", anb_int_cmp(values.index_get(m.clone()), values.index_get(runner.clone())), AnubisValue::Int(0)).as_bool() {
                        runner = m.clone();
                    }
                } else {
                    if anubis_cmp(">", anb_int_cmp(values.index_get(runner.clone()), values.index_get(m.clone())), AnubisValue::Int(0)).as_bool() {
                        runner = m.clone();
                    }
                }
            }
        }
        m = anubis_add(m.clone(), AnubisValue::Int(1));
    }
    let mut margin = anb_int_sub(values.index_get(best.clone()), values.index_get(runner.clone()));
    if anubis_cmp("==", sense.clone(), anubis_mk_str("min".to_string())).as_bool() {
        margin = anb_int_sub(values.index_get(runner.clone()), values.index_get(best.clone()));
    }
    if anubis_cmp("==", anb_int_cmp(margin.clone(), anb_int_from_text(anubis_mk_str("0".to_string()))), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("decision-margin-zero: the top two options tie on the declared criterion; fail closed".to_string()));
    }
    let mut options_json = anubis_mk_str("[".to_string());
    let mut n = AnubisValue::Int(0);
    while anubis_cmp("<", n.clone(), (labels.clone()).len_val()).as_bool() {
        if anubis_cmp(">", n.clone(), AnubisValue::Int(0)).as_bool() {
            options_json = anubis_add(options_json.clone(), anubis_mk_str(",".to_string()));
        }
        options_json = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(options_json.clone(), anubis_mk_str("{".to_string())), anb_jkv(anubis_mk_str("label".to_string()), anb_jstr(labels.index_get(n.clone())))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("value".to_string()), anb_jstr(anb_int_to_text(values.index_get(n.clone()))))), anubis_mk_str("}".to_string()));
        n = anubis_add(n.clone(), AnubisValue::Int(1));
    }
    options_json = anubis_add(options_json.clone(), anubis_mk_str("]".to_string()));
    let mut selected = labels.index_get(best.clone());
    let mut margin_text = anb_int_to_text(margin.clone());
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact selected=".to_string())), selected.clone()), anubis_mk_str(" margin=".to_string())), margin_text.clone()).display_string());
    println!("{}", anubis_mk_str("consequence=decision-boundary note=the-declared-criterion-remains-the-callers-this-is-not-a-claim-it-is-the-right-one".to_string()).display_string());
    let mut claim = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("criterion".to_string()), anb_jstr(criterion.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("decision_id".to_string()), anb_jstr(decision_id.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("margin".to_string()), anb_jstr(margin_text.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("options".to_string()), options_json.clone())), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("runner_up".to_string()), anb_jstr(labels.index_get(runner.clone())))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("selected".to_string()), anb_jstr(selected.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("sense".to_string()), anb_jstr(sense.clone()))), anubis_mk_str("}".to_string()));
    println!("{}", anb_decision_envelope(claim.clone(), anubis_mk_str("{}".to_string())).display_string());
    AnubisValue::Int(0)
}

fn anb_cmd_pack_route(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if anubis_cmp("<", (argv.clone()).len_val(), AnubisValue::Int(3)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("pack-request-arity: expected pack id, operation id, and arguments; fail closed".to_string()));
    }
    let mut requested_pack = argv.index_get(AnubisValue::Int(1));
    let mut routed = anubis_mk_str("".to_string());
    if anubis_cmp("==", requested_pack.clone(), anb_domain_packs_core_core_pack__pack_id()).as_bool() {
        routed = anb_domain_packs_core_core_pack__route_operation(argv.index_get(AnubisValue::Int(1)), argv.index_get(AnubisValue::Int(2)), anubis_sub((argv.clone()).len_val(), AnubisValue::Int(3)));
    }
    if anubis_cmp("==", requested_pack.clone(), anb_domain_packs_programming_programming_pack__pack_id()).as_bool() {
        routed = anb_domain_packs_programming_programming_pack__route_operation(argv.index_get(AnubisValue::Int(1)), argv.index_get(AnubisValue::Int(2)), anubis_sub((argv.clone()).len_val(), AnubisValue::Int(3)));
    }
    if anubis_cmp("==", requested_pack.clone(), anb_domain_packs_decision_decision_pack__pack_id()).as_bool() {
        routed = anb_domain_packs_decision_decision_pack__route_operation(argv.index_get(AnubisValue::Int(1)), argv.index_get(AnubisValue::Int(2)), anubis_sub((argv.clone()).len_val(), AnubisValue::Int(3)));
    }
    if anubis_cmp("==", routed.clone(), anubis_mk_str("".to_string())).as_bool() {
        let _ = anubis_panic(anubis_mk_str("pack-id-unknown: requested pack is not registered; fail closed".to_string()));
    }
    let mut forwarded = anubis_mk_list(vec![routed.clone()]);
    let mut i = AnubisValue::Int(3);
    while anubis_cmp("<", i.clone(), (argv.clone()).len_val()).as_bool() {
        forwarded.push_val(argv.index_get(i.clone()));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    if anubis_cmp("==", routed.clone(), anubis_mk_str("mod-pow".to_string())).as_bool() {
        let _ = anb_cmd_mod_pow(forwarded.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", routed.clone(), anubis_mk_str("test-exists".to_string())).as_bool() {
        let _ = anb_cmd_test_exists(forwarded.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", routed.clone(), anubis_mk_str("claim-cites-test".to_string())).as_bool() {
        let _ = anb_cmd_claim_cites_test(forwarded.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", routed.clone(), anubis_mk_str("decision-rank".to_string())).as_bool() {
        let _ = anb_cmd_decision_rank(forwarded.clone());
        return AnubisValue::Int(0);
    }
    anubis_panic(anubis_mk_str("pack-route-internal: registered route has no Anubis handler; fail closed".to_string()))
}

fn anb_cmd_mod_inv(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
    let mut a = anb_int_from_text(argv.index_get(AnubisValue::Int(1)));
    let mut modulus = anb_int_from_text(argv.index_get(AnubisValue::Int(2)));
    let mut inv = anb_int_modinv(a.clone(), modulus.clone());
    let mut it = anb_int_to_text(inv.clone());
    println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact inv=".to_string())), it.clone()).display_string());
    let mut claim = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("a".to_string()), anb_jstr(anb_int_to_text(a.clone())))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("inv".to_string()), anb_jstr(it.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("m".to_string()), anb_jstr(anb_int_to_text(modulus.clone())))), anubis_mk_str("}".to_string()));
    println!("{}", anb_cert_envelope(anubis_mk_str("mod-inv".to_string()), claim.clone(), anubis_mk_str("{}".to_string())).display_string());
    AnubisValue::Int(0)
}

fn anb_cmd_crt(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    if AnubisValue::Bool((anubis_cmp("<", (argv.clone()).len_val(), AnubisValue::Int(5))).as_bool() || (anubis_cmp("!=", anubis_mod(anubis_sub((argv.clone()).len_val(), AnubisValue::Int(1)), AnubisValue::Int(2)), AnubisValue::Int(0))).as_bool()).as_bool() {
        let _ = anubis_panic(anubis_mk_str("crt requires residue/modulus pairs: crt r1 m1 r2 m2 [...]; fail closed".to_string()));
    }
    let mut rs = anubis_mk_list(vec![]);
    let mut ms = anubis_mk_list(vec![]);
    let mut i = AnubisValue::Int(1);
    while anubis_cmp("<", i.clone(), (argv.clone()).len_val()).as_bool() {
        rs.push_val(anb_int_from_text(argv.index_get(i.clone())));
        ms.push_val(anb_int_from_text(argv.index_get(anubis_add(i.clone(), AnubisValue::Int(1)))));
        i = anubis_add(i.clone(), AnubisValue::Int(2));
    }
    let mut combined = anb_crt_combine(rs.clone(), ms.clone());
    let mut xt = anb_int_to_text(combined.field_get("x"));
    let mut mt = anb_int_to_text(combined.field_get("modulus"));
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact x=".to_string())), xt.clone()), anubis_mk_str(" M=".to_string())), mt.clone()).display_string());
    let mut residues = anubis_mk_str("[".to_string());
    i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (rs.clone()).len_val()).as_bool() {
        if anubis_cmp(">", i.clone(), AnubisValue::Int(0)).as_bool() {
            residues = anubis_add(residues.clone(), anubis_mk_str(",".to_string()));
        }
        residues = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(residues.clone(), anubis_mk_str("{".to_string())), anb_jkv(anubis_mk_str("m".to_string()), anb_jstr(anb_int_to_text(ms.index_get(i.clone()))))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("r".to_string()), anb_jstr(anb_int_to_text(rs.index_get(i.clone()))))), anubis_mk_str("}".to_string()));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    residues = anubis_add(residues.clone(), anubis_mk_str("]".to_string()));
    let mut claim = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("M".to_string()), anb_jstr(mt.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("residues".to_string()), residues.clone())), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("x".to_string()), anb_jstr(xt.clone()))), anubis_mk_str("}".to_string()));
    println!("{}", anb_cert_envelope(anubis_mk_str("crt".to_string()), claim.clone(), anubis_mk_str("{}".to_string())).display_string());
    AnubisValue::Int(0)
}

fn anb_cmd_divides(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
    let mut a = anb_int_from_text(argv.index_get(AnubisValue::Int(1)));
    let mut b = anb_int_from_text(argv.index_get(AnubisValue::Int(2)));
    let mut result = AnubisValue::Bool(false);
    if anb_big_is_zero(a.field_get("num")).as_bool() {
        result = anb_big_is_zero(b.field_get("num"));
    } else {
        result = anb_big_is_zero((anb_int_mod(b.clone(), a.clone())).field_get("num"));
    }
    let mut word = if (result.clone()).as_bool() { anubis_mk_str("true".to_string()) } else { anubis_mk_str("false".to_string()) };
    println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact divides=".to_string())), word.clone()).display_string());
    AnubisValue::Int(0)
}

fn anb_cmd_prime_cert(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
    let mut text = argv.index_get(AnubisValue::Int(1));
    if anubis_cmp(">", (text.clone()).len_val(), AnubisValue::Int(61)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("prime-cert: input exceeds 61 digits (n <= 10^60 domain); fail closed (prime-cert-budget)".to_string()));
    }
    let mut n = anb_big_from_text(text.clone());
    if anubis_cmp("<", anb_big_cmp(n.clone(), anubis_mk_list(vec![AnubisValue::Int(2)])), AnubisValue::Int(0)).as_bool() {
        let _ = anubis_panic(anubis_mk_str("prime-cert: n must be >= 2; fail closed".to_string()));
    }
    let mut nt = anb_big_to_text(n.clone());
    if AnubisValue::Bool(!(anb_mr_is_probable_prime(n.clone())).as_bool()).as_bool() {
        let mut d = anb_find_divisor(n.clone());
        let mut dt = anb_big_to_text(d.clone());
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact verdict=composite n=".to_string())), nt.clone()), anubis_mk_str(" divisor=".to_string())), dt.clone()).display_string());
        let mut claim = anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("n".to_string()), anb_jstr(nt.clone()))), anubis_mk_str("}".to_string()));
        let mut witness = anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("divisor".to_string()), anb_jstr(dt.clone()))), anubis_mk_str("}".to_string()));
        println!("{}", anb_cert_envelope(anubis_mk_str("composite".to_string()), claim.clone(), witness.clone()).display_string());
        return AnubisValue::Int(0);
    }
    let mut built = anb_pratt_build(n.clone(), AnubisValue::Int(0), AnubisValue::Int(0));
    let mut bj = built.field_get("json");
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact verdict=prime n=".to_string())), nt.clone()), anubis_mk_str(" method=pratt".to_string())).display_string());
    let mut claim = anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("n".to_string()), anb_jstr(nt.clone()))), anubis_mk_str("}".to_string()));
    println!("{}", anb_cert_envelope(anubis_mk_str("prime".to_string()), claim.clone(), bj.clone()).display_string());
    AnubisValue::Int(0)
}

fn anb_cmd_poly_canon(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
    let mut expr = argv.index_get(AnubisValue::Int(1));
    let mut lowered = anb_poly_lower(anb_parse_ast(expr.clone()));
    let mut p = lowered.field_get("coeffs");
    let _ = anb_cert_safe_expr(expr.clone());
    let mut d = anb_poly_deg(p.clone());
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact degree=".to_string())), d.clone()), anubis_mk_str(" coeffs=".to_string())), anb_poly_coeffs_text(p.clone())).display_string());
    let mut claim = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("coeffs".to_string()), anb_json_coeff_array(p.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("degree".to_string()), anb_jstr(anubis_str(d.clone())))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("expr".to_string()), anb_jstr(expr.clone()))), anubis_mk_str("}".to_string()));
    println!("{}", anb_cert_envelope(anubis_mk_str("poly-canon".to_string()), claim.clone(), anubis_mk_str("{}".to_string())).display_string());
    AnubisValue::Int(0)
}

fn anb_cmd_poly_eq(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
    let mut lhs = argv.index_get(AnubisValue::Int(1));
    let mut rhs = argv.index_get(AnubisValue::Int(2));
    let mut pl = anb_poly_lower(anb_parse_ast(lhs.clone()));
    let mut pr = anb_poly_lower(anb_parse_ast(rhs.clone()));
    let mut lc = pl.field_get("coeffs");
    let mut rc = pr.field_get("coeffs");
    let _ = anb_cert_safe_expr(lhs.clone());
    let _ = anb_cert_safe_expr(rhs.clone());
    let mut same = anb_poly_equal(lc.clone(), rc.clone());
    let mut word = if (same.clone()).as_bool() { anubis_mk_str("true".to_string()) } else { anubis_mk_str("false".to_string()) };
    println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact equal=".to_string())), word.clone()).display_string());
    let mut claim = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("equal".to_string()), word.clone())), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("lhs".to_string()), anb_jstr(lhs.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("rhs".to_string()), anb_jstr(rhs.clone()))), anubis_mk_str("}".to_string()));
    let mut witness = anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("lhs_coeffs".to_string()), anb_json_coeff_array(lc.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("rhs_coeffs".to_string()), anb_json_coeff_array(rc.clone()))), anubis_mk_str("}".to_string()));
    println!("{}", anb_cert_envelope(anubis_mk_str("poly-eq".to_string()), claim.clone(), witness.clone()).display_string());
    AnubisValue::Int(0)
}

fn anb_cmd_poly_gcd(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
    let mut lhs = argv.index_get(AnubisValue::Int(1));
    let mut rhs = argv.index_get(AnubisValue::Int(2));
    let mut pl = anb_poly_lower(anb_parse_ast(lhs.clone()));
    let mut pr = anb_poly_lower(anb_parse_ast(rhs.clone()));
    let mut g = anb_poly_gcd(pl.field_get("coeffs"), pr.field_get("coeffs"));
    let _ = anb_cert_safe_expr(lhs.clone());
    let _ = anb_cert_safe_expr(rhs.clone());
    println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact gcd=".to_string())), anb_poly_coeffs_text(g.clone())).display_string());
    let mut claim = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("gcd_coeffs".to_string()), anb_json_coeff_array(g.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("lhs".to_string()), anb_jstr(lhs.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("rhs".to_string()), anb_jstr(rhs.clone()))), anubis_mk_str("}".to_string()));
    println!("{}", anb_cert_envelope(anubis_mk_str("poly-gcd".to_string()), claim.clone(), anubis_mk_str("{}".to_string())).display_string());
    AnubisValue::Int(0)
}

fn anb_cmd_ratfunc_canon(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
    let mut expr = argv.index_get(AnubisValue::Int(1));
    let mut canonical = anb_rf_canon(anb_rf_lower(anb_parse_ast(expr.clone())));
    let mut p = canonical.field_get("num");
    let mut q = canonical.field_get("den");
    let _ = anb_cert_safe_expr(expr.clone());
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact num=".to_string())), anb_poly_coeffs_text(p.clone())), anubis_mk_str(" den=".to_string())), anb_poly_coeffs_text(q.clone())), anubis_mk_str(" side-condition=denominator-nonzero".to_string())).display_string());
    let mut claim = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("den_coeffs".to_string()), anb_json_coeff_array(q.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("expr".to_string()), anb_jstr(expr.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("num_coeffs".to_string()), anb_json_coeff_array(p.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("side_condition".to_string()), anb_jstr(anubis_mk_str("denominator-nonzero".to_string())))), anubis_mk_str("}".to_string()));
    println!("{}", anb_cert_envelope(anubis_mk_str("ratfunc-canon".to_string()), claim.clone(), anubis_mk_str("{}".to_string())).display_string());
    AnubisValue::Int(0)
}

fn anb_cmd_roots_isolate(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
    let mut expr = argv.index_get(AnubisValue::Int(1));
    let mut lowered = anb_poly_lower(anb_parse_ast(expr.clone()));
    let mut p = lowered.field_get("coeffs");
    let mut s = anb_poly_squarefree(p.clone());
    let mut chain = anb_sturm_chain(s.clone());
    let mut rivs = anb_sturm_isolate_all(chain.clone(), s.clone());
    let _ = anb_cert_safe_expr(expr.clone());
    let mut k = (rivs.clone()).len_val();
    let mut iv_text = anubis_mk_str("".to_string());
    let mut iv_json = anubis_mk_str("[".to_string());
    let mut i = AnubisValue::Int(0);
    while anubis_cmp("<", i.clone(), (rivs.clone()).len_val()).as_bool() {
        let mut lo_t = anb_rat_to_text((rivs.index_get(i.clone())).field_get("lo"));
        let mut hi_t = anb_rat_to_text((rivs.index_get(i.clone())).field_get("hi"));
        iv_text = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(iv_text.clone(), anubis_mk_str("[".to_string())), lo_t.clone()), anubis_mk_str(",".to_string())), hi_t.clone()), anubis_mk_str("]".to_string()));
        if anubis_cmp(">", i.clone(), AnubisValue::Int(0)).as_bool() {
            iv_json = anubis_add(iv_json.clone(), anubis_mk_str(",".to_string()));
        }
        iv_json = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(iv_json.clone(), anubis_mk_str("[".to_string())), anb_jstr(lo_t.clone())), anubis_mk_str(",".to_string())), anb_jstr(hi_t.clone())), anubis_mk_str("]".to_string()));
        i = anubis_add(i.clone(), AnubisValue::Int(1));
    }
    iv_json = anubis_add(iv_json.clone(), anubis_mk_str("]".to_string()));
    println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact distinct-real-roots=".to_string())), k.clone()), anubis_mk_str(" intervals=".to_string())), iv_text.clone()).display_string());
    let mut claim = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("{".to_string()), anb_jkv(anubis_mk_str("distinct_real_roots".to_string()), anb_jstr(anubis_str(k.clone())))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("expr".to_string()), anb_jstr(expr.clone()))), anubis_mk_str(",".to_string())), anb_jkv(anubis_mk_str("intervals".to_string()), iv_json.clone())), anubis_mk_str("}".to_string()));
    println!("{}", anb_cert_envelope(anubis_mk_str("roots-isolate".to_string()), claim.clone(), anubis_mk_str("{}".to_string())).display_string());
    AnubisValue::Int(0)
}

fn anb_cmd_alg_sign(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
    let mut lowered = anb_poly_lower(anb_parse_ast(argv.index_get(AnubisValue::Int(1))));
    let mut point = anb_rat_from_frac_text(argv.index_get(AnubisValue::Int(2)));
    let mut s = anb_rat_sign(anb_poly_eval(lowered.field_get("coeffs"), point.clone()));
    println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact sign=".to_string())), s.clone()).display_string());
    AnubisValue::Int(0)
}

fn anb_cmd_alg_cmp(mut argv: AnubisValue) -> AnubisValue {
    __anb_stack_guard();
    let _ = anb_require_arity(argv.clone(), AnubisValue::Int(7));
    let mut order = anb_alg_cmp_order(argv.index_get(AnubisValue::Int(1)), argv.index_get(AnubisValue::Int(2)), argv.index_get(AnubisValue::Int(3)), argv.index_get(AnubisValue::Int(4)), argv.index_get(AnubisValue::Int(5)), argv.index_get(AnubisValue::Int(6)));
    println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact order=".to_string())), order.clone()).display_string());
    AnubisValue::Int(0)
}

fn anb_run_native_self_test() -> AnubisValue {
    __anb_stack_guard();
    let mut a = AnubisValue::Struct { ty: "Vec3".to_string(), fields: vec![("x".to_string(), anubis_field_coerce_float(AnubisValue::Float(1f64), "x")), ("y".to_string(), anubis_field_coerce_float(AnubisValue::Float(2f64), "y")), ("z".to_string(), anubis_field_coerce_float(AnubisValue::Float(3f64), "z"))] };
    let mut b = AnubisValue::Struct { ty: "Vec3".to_string(), fields: vec![("x".to_string(), anubis_field_coerce_float(AnubisValue::Float(4f64), "x")), ("y".to_string(), anubis_field_coerce_float(AnubisValue::Float(5f64), "y")), ("z".to_string(), anubis_field_coerce_float(AnubisValue::Float(6f64), "z"))] };
    let mut cross = anb_cross3(a.clone(), b.clone());
    let _ = anubis_assert(anubis_cmp("==", anb_positive_abs(anubis_neg(AnubisValue::Int(42))), AnubisValue::Int(42)));
    let _ = anubis_assert(anubis_cmp("==", anb_gcd_safe(AnubisValue::Int(462), AnubisValue::Int(1071)), AnubisValue::Int(21)));
    let _ = anubis_assert(anubis_cmp("==", anb_format_hex(AnubisValue::Int(255)), anubis_mk_str("0xFF".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_format_binary(AnubisValue::Int(42)), anubis_mk_str("0b101010".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_choose(AnubisValue::Int(10), AnubisValue::Int(3)), AnubisValue::Int(120)));
    let _ = anubis_assert(anubis_cmp("==", anb_choose(AnubisValue::Int(62), AnubisValue::Int(31)), AnubisValue::Int(465428353255261088)));
    let _ = anubis_assert(anubis_cmp("==", anb_choose(AnubisValue::Int(66), AnubisValue::Int(33)), AnubisValue::Int(7219428434016265740)));
    let _ = anubis_assert(anubis_cmp("==", anb_dot3(a.clone(), b.clone()), AnubisValue::Float(32f64)));
    let _ = anubis_assert(anubis_cmp("==", cross.field_get("x"), anubis_neg(AnubisValue::Float(3f64))));
    let _ = anubis_assert(anubis_cmp("==", cross.field_get("y"), AnubisValue::Float(6f64)));
    let _ = anubis_assert(anubis_cmp("==", cross.field_get("z"), anubis_neg(AnubisValue::Float(3f64))));
    let _ = anubis_assert(anubis_cmp("==", anb_norm_vec3(AnubisValue::Struct { ty: "Vec3".to_string(), fields: vec![("x".to_string(), anubis_field_coerce_float(AnubisValue::Float(2f64), "x")), ("y".to_string(), anubis_field_coerce_float(AnubisValue::Float(3f64), "y")), ("z".to_string(), anubis_field_coerce_float(AnubisValue::Float(6f64), "z"))] }), AnubisValue::Float(7f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_median(anubis_mk_list(vec![AnubisValue::Float(2f64), AnubisValue::Float(4f64), AnubisValue::Float(4f64), AnubisValue::Float(4f64), AnubisValue::Float(5f64), AnubisValue::Float(5f64), AnubisValue::Float(7f64), AnubisValue::Float(9f64)])), AnubisValue::Float(4.5f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_convert_unit(AnubisValue::Float(1f64), anubis_mk_str("km".to_string()), anubis_mk_str("m".to_string())), AnubisValue::Float(1000f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_convert_unit(AnubisValue::Float(212f64), anubis_mk_str("F".to_string()), anubis_mk_str("C".to_string())), AnubisValue::Float(100f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_convert_unit(AnubisValue::Float(1f64), anubis_mk_str("atm".to_string()), anubis_mk_str("Pa".to_string())), AnubisValue::Float(101325f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_rounded(AnubisValue::Float(1.9999999999999927f64), AnubisValue::Float(12f64)), AnubisValue::Float(2f64)));
    let _ = { let __anb_m5 = anb_prime_verdict(AnubisValue::Int(104729)); let mut __anb_r5 = AnubisValue::Int(0); let mut __anb_done5 = false; if !__anb_done5 { if matches!(&__anb_m5, AnubisValue::Enum { ty, tag, .. } if ty == "PrimeVerdict" && tag == "Prime") { let __anb_m5_p0 = (match &__anb_m5 { AnubisValue::Enum { fields, .. } if fields.len() > 0 => fields[0].clone(), _ => AnubisValue::Int(0) }); let mut n = __anb_m5_p0.clone(); __anb_r5 = (anubis_assert(anubis_cmp("==", n.clone(), AnubisValue::Int(104729)))); __anb_done5 = true; } } if !__anb_done5 { if matches!(&__anb_m5, AnubisValue::Enum { ty, tag, .. } if ty == "PrimeVerdict" && tag == "Composite") { __anb_r5 = (anubis_panic(anubis_mk_str("prime self-test failed".to_string()))); __anb_done5 = true; } } if !__anb_done5 { if matches!(&__anb_m5, AnubisValue::Enum { ty, tag, .. } if ty == "PrimeVerdict" && tag == "OutsideDomain") { __anb_r5 = (anubis_panic(anubis_mk_str("prime domain self-test failed".to_string()))); __anb_done5 = true; } } if !__anb_done5 { panic!("ANUBIS_MATCH_UNMATCHED: no match arm matched value `{}` (add a `_` arm)", (__anb_m5).display_string()); } __anb_r5 };
    let _ = { let __anb_m6 = anb_prime_verdict(AnubisValue::Int(221)); let mut __anb_r6 = AnubisValue::Int(0); let mut __anb_done6 = false; if !__anb_done6 { if matches!(&__anb_m6, AnubisValue::Enum { ty, tag, .. } if ty == "PrimeVerdict" && tag == "Composite") { let __anb_m6_nf_value = (match &__anb_m6 { AnubisValue::Enum { fields, field_names, .. } => { let mut __v = AnubisValue::Int(0); for (__i, __n) in field_names.iter().enumerate() { if __n == &"value" { if let Some(__f) = fields.get(__i) { __v = __f.clone(); } break; } } __v }, _ => AnubisValue::Int(0) }); let mut n = __anb_m6_nf_value.clone(); let __anb_m6_nf_divisor = (match &__anb_m6 { AnubisValue::Enum { fields, field_names, .. } => { let mut __v = AnubisValue::Int(0); for (__i, __n) in field_names.iter().enumerate() { if __n == &"divisor" { if let Some(__f) = fields.get(__i) { __v = __f.clone(); } break; } } __v }, _ => AnubisValue::Int(0) }); let mut d = __anb_m6_nf_divisor.clone(); __anb_r6 = ({ let _ = anubis_assert(anubis_cmp("==", n.clone(), AnubisValue::Int(221)));
 anubis_assert(anubis_cmp("==", d.clone(), AnubisValue::Int(13))) }); __anb_done6 = true; } } if !__anb_done6 { if matches!(&__anb_m6, AnubisValue::Enum { ty, tag, .. } if ty == "PrimeVerdict" && tag == "Prime") { __anb_r6 = (anubis_panic(anubis_mk_str("composite self-test failed".to_string()))); __anb_done6 = true; } } if !__anb_done6 { if matches!(&__anb_m6, AnubisValue::Enum { ty, tag, .. } if ty == "PrimeVerdict" && tag == "OutsideDomain") { __anb_r6 = (anubis_panic(anubis_mk_str("composite domain self-test failed".to_string()))); __anb_done6 = true; } } if !__anb_done6 { panic!("ANUBIS_MATCH_UNMATCHED: no match arm matched value `{}` (add a `_` arm)", (__anb_m6).display_string()); } __anb_r6 };
    let _ = anubis_assert(anubis_cmp("<", anubis_abs(anubis_sub(anubis_mul(anubis_mul(AnubisValue::Float(0.5f64), AnubisValue::Float(2f64)), anubis_pow(AnubisValue::Float(3f64), AnubisValue::Float(2f64))), AnubisValue::Float(9f64))), AnubisValue::Float(0.000000000001f64)));
    let mut measured_area = anb_multiply_measurements(anb_measurement(AnubisValue::Float(12f64), AnubisValue::Float(0.1f64), anubis_mk_str("m".to_string())), anb_measurement(AnubisValue::Float(3f64), AnubisValue::Float(0.05f64), anubis_mk_str("m".to_string())), anubis_mk_str("m2".to_string()));
    let _ = anubis_assert(anubis_cmp("==", measured_area.field_get("value"), AnubisValue::Float(36f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_rounded(measured_area.field_get("uncertainty"), AnubisValue::Float(12f64)), AnubisValue::Float(0.9f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_rounded(anubis_mul(anb_relative_uncertainty(measured_area.clone()), AnubisValue::Float(100f64)), AnubisValue::Float(12f64)), AnubisValue::Float(2.5f64)));
    let mut resistance = anb_divide_measurements(anb_measurement(AnubisValue::Float(12f64), AnubisValue::Float(0.1f64), anubis_mk_str("V".to_string())), anb_measurement(AnubisValue::Float(3f64), AnubisValue::Float(0.05f64), anubis_mk_str("A".to_string())), anubis_mk_str("ohm".to_string()));
    let _ = anubis_assert(anubis_cmp("==", resistance.field_get("value"), AnubisValue::Float(4f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_rounded(resistance.field_get("uncertainty"), AnubisValue::Float(12f64)), AnubisValue::Float(0.1f64)));
    let mut matrix = AnubisValue::Struct { ty: "Matrix2".to_string(), fields: vec![("a".to_string(), anubis_field_coerce_float(AnubisValue::Float(1f64), "a")), ("b".to_string(), anubis_field_coerce_float(AnubisValue::Float(2f64), "b")), ("c".to_string(), anubis_field_coerce_float(AnubisValue::Float(3f64), "c")), ("d".to_string(), anubis_field_coerce_float(AnubisValue::Float(4f64), "d"))] };
    let mut inverse = anb_inverse2(matrix.clone());
    let _ = anubis_assert(anubis_cmp("==", anb_determinant2(matrix.clone()), anubis_neg(AnubisValue::Float(2f64))));
    let _ = anubis_assert(AnubisValue::Bool((AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", inverse.field_get("a"), anubis_neg(AnubisValue::Float(2f64)))).as_bool() && (anubis_cmp("==", inverse.field_get("b"), AnubisValue::Float(1f64))).as_bool())).as_bool() && (anubis_cmp("==", inverse.field_get("c"), AnubisValue::Float(1.5f64))).as_bool())).as_bool() && (anubis_cmp("==", inverse.field_get("d"), anubis_neg(AnubisValue::Float(0.5f64)))).as_bool()));
    let _ = anubis_assert(anubis_cmp("==", anb_rounded(anb_integrate_square_simpson(AnubisValue::Float(0f64), AnubisValue::Float(3f64), AnubisValue::Int(100)), AnubisValue::Float(12f64)), AnubisValue::Float(9f64)));
    let _ = anubis_assert(anubis_cmp("<", anubis_abs(anubis_sub(anb_derivative_cube(AnubisValue::Float(2f64), AnubisValue::Float(0.001f64)), AnubisValue::Float(12f64))), AnubisValue::Float(0.000002f64)));
    let _ = { let __anb_m7 = anb_spectrum_band(AnubisValue::Float(501.5f64)); let mut __anb_r7 = AnubisValue::Int(0); let mut __anb_done7 = false; if !__anb_done7 { if matches!(&__anb_m7, AnubisValue::Enum { ty, tag, .. } if ty == "SpectrumBand" && tag == "Visible") { __anb_r7 = (anubis_assert(AnubisValue::Bool(true))); __anb_done7 = true; } } if !__anb_done7 { if matches!(&__anb_m7, AnubisValue::Enum { ty, tag, .. } if ty == "SpectrumBand" && tag == "Ultraviolet") { __anb_r7 = (anubis_panic(anubis_mk_str("spectrum self-test failed".to_string()))); __anb_done7 = true; } } if !__anb_done7 { if matches!(&__anb_m7, AnubisValue::Enum { ty, tag, .. } if ty == "SpectrumBand" && tag == "Infrared") { __anb_r7 = (anubis_panic(anubis_mk_str("spectrum self-test failed".to_string()))); __anb_done7 = true; } } if !__anb_done7 { panic!("ANUBIS_MATCH_UNMATCHED: no match arm matched value `{}` (add a `_` arm)", (__anb_m7).display_string()); } __anb_r7 };
    let _ = anubis_assert(anubis_cmp("==", (anubis_sha256(anubis_mk_str("jackal-claim-v1".to_string()))).len_val(), AnubisValue::Int(64)));
    let _ = anubis_assert(anubis_cmp("==", anb_spectrum_text(AnubisValue::Enum { ty: "SpectrumBand".to_string(), tag: "Infrared".to_string(), fields: vec![], field_names: vec![] }), anubis_mk_str("infrared".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_evaluate_expression(anubis_mk_str("2+3*4".to_string()), anubis_map_lit(vec![])), AnubisValue::Float(14f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_evaluate_expression(anubis_mk_str("(2+3)*4".to_string()), anubis_map_lit(vec![])), AnubisValue::Float(20f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_evaluate_expression(anubis_mk_str("2^10".to_string()), anubis_map_lit(vec![])), AnubisValue::Float(1024f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_evaluate_expression(anubis_mk_str("-3^2".to_string()), anubis_map_lit(vec![])), anubis_neg(AnubisValue::Float(9f64))));
    let _ = anubis_assert(anubis_cmp("==", anb_evaluate_expression(anubis_mk_str("2^-3".to_string()), anubis_map_lit(vec![])), AnubisValue::Float(0.125f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_evaluate_expression(anubis_mk_str("sqrt(16)+cbrt(27)".to_string()), anubis_map_lit(vec![])), AnubisValue::Float(7f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_evaluate_expression(anubis_mk_str("hypot(3,4)".to_string()), anubis_map_lit(vec![])), AnubisValue::Float(5f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_evaluate_expression(anubis_mk_str("sin(pi/2)".to_string()), anubis_map_lit(vec![])), AnubisValue::Float(1f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_evaluate_expression(anubis_mk_str("x^2+1".to_string()), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), AnubisValue::Float(3f64))])), AnubisValue::Float(10f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_evaluate_expression(anubis_mk_str("1.5e2".to_string()), anubis_map_lit(vec![])), AnubisValue::Float(150f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_rounded(anb_simpson_general(anubis_mk_str("x^2".to_string()), AnubisValue::Float(0f64), AnubisValue::Float(3f64), AnubisValue::Int(100)), AnubisValue::Float(12f64)), AnubisValue::Float(9f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_evaluate_expression(anubis_mk_str("a*b".to_string()), anubis_map_lit(vec![((anubis_mk_str("a".to_string())).display_string(), AnubisValue::Float(3f64)), ((anubis_mk_str("b".to_string())).display_string(), AnubisValue::Float(4f64))])), AnubisValue::Float(12f64)));
    let _ = anubis_assert(anubis_cmp("==", anb_big_to_text(anb_big_from_text(anubis_mk_str("00123".to_string()))), anubis_mk_str("123".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_big_to_text(anb_big_add(anb_big_from_text(anubis_mk_str("999999999999999999".to_string())), anb_big_from_text(anubis_mk_str("1".to_string())))), anubis_mk_str("1000000000000000000".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_big_to_text(anb_big_mul(anb_big_from_text(anubis_mk_str("111111111".to_string())), anb_big_from_text(anubis_mk_str("111111111".to_string())))), anubis_mk_str("12345678987654321".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_big_to_text(anb_big_fact(AnubisValue::Int(20))), anubis_mk_str("2432902008176640000".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_big_to_text(anb_big_ncr(AnubisValue::Int(62), AnubisValue::Int(31))), anubis_mk_str("465428353255261088".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_big_to_text(anb_big_pow(anb_big_from_text(anubis_mk_str("2".to_string())), AnubisValue::Int(64))), anubis_mk_str("18446744073709551616".to_string())));
    let mut division_check = anb_big_divmod_small(anb_big_from_text(anubis_mk_str("1000000000000000000".to_string())), AnubisValue::Int(7));
    let _ = anubis_assert(anubis_cmp("==", anb_big_to_text(division_check.field_get("quotient")), anubis_mk_str("142857142857142857".to_string())));
    let _ = anubis_assert(anubis_cmp("==", division_check.field_get("remainder"), AnubisValue::Int(1)));
    let _ = anubis_assert(anubis_cmp("==", anb_ast_to_text(anb_simplify(anb_deriv(anb_simplify(anb_parse_ast(anubis_mk_str("x^2".to_string())))))), anubis_mk_str("2*x".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_ast_to_text(anb_simplify(anb_deriv(anb_simplify(anb_parse_ast(anubis_mk_str("sin(x)".to_string())))))), anubis_mk_str("cos(x)".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_ast_to_text(anb_simplify(anb_deriv(anb_simplify(anb_parse_ast(anubis_mk_str("ln(x)".to_string())))))), anubis_mk_str("1/x".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_ast_to_text(anb_simplify(anb_deriv(anb_simplify(anb_parse_ast(anubis_mk_str("x^x".to_string())))))), anubis_mk_str("x^x*(ln(x)+1)".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_eval_ast(anb_parse_ast(anubis_mk_str("2*x+1".to_string())), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), AnubisValue::Float(3f64))])), anb_evaluate_expression(anubis_mk_str("2*x+1".to_string()), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), AnubisValue::Float(3f64))]))));
    let _ = anubis_assert(anubis_cmp("==", anb_rat_to_text(anb_rat_eval_ast(anb_parse_ast(anubis_mk_str("1/3 + 1/6".to_string())))), anubis_mk_str("1/2".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_rat_to_text(anb_rat_eval_ast(anb_parse_ast(anubis_mk_str("0.1 + 0.2".to_string())))), anubis_mk_str("3/10".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_rat_to_text(anb_rat_eval_ast(anb_parse_ast(anubis_mk_str("(2/3)^-2".to_string())))), anubis_mk_str("9/4".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_rat_to_text(anb_rat_eval_ast(anb_parse_ast(anubis_mk_str("1/3 - 1/3".to_string())))), anubis_mk_str("0".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_big_to_text(anb_big_gcd(anb_big_from_text(anubis_mk_str("462".to_string())), anb_big_from_text(anubis_mk_str("1071".to_string())))), anubis_mk_str("21".to_string())));
    let mut big_division = anb_big_divmod(anb_big_from_text(anubis_mk_str("123456789123456789".to_string())), anb_big_from_text(anubis_mk_str("987654321".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_big_to_text(big_division.field_get("quotient")), anubis_mk_str("124999998".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_big_to_text(big_division.field_get("remainder")), anubis_mk_str("973765431".to_string())));
    let mut sin_range = anb_ieval(anb_parse_ast(anubis_mk_str("sin(x)".to_string())), AnubisValue::Float(0f64), AnubisValue::Float(3.141592653589793f64));
    let _ = anubis_assert(sin_range.field_get("ok"));
    let _ = anubis_assert(AnubisValue::Bool((anubis_cmp("<=", sin_range.field_get("lo"), AnubisValue::Float(0f64))).as_bool() && (anubis_cmp(">=", sin_range.field_get("lo"), anubis_neg(AnubisValue::Float(0.000001f64)))).as_bool()));
    let _ = anubis_assert(anubis_cmp("==", sin_range.field_get("hi"), AnubisValue::Float(1f64)));
    let mut sq_range = anb_ieval(anb_parse_ast(anubis_mk_str("x^2".to_string())), anubis_neg(AnubisValue::Float(1f64)), AnubisValue::Float(2f64));
    let _ = anubis_assert(sq_range.field_get("ok"));
    let _ = anubis_assert(AnubisValue::Bool((anubis_cmp("<=", sq_range.field_get("lo"), AnubisValue::Float(0f64))).as_bool() && (anubis_cmp(">=", sq_range.field_get("lo"), anubis_neg(AnubisValue::Float(0.000001f64)))).as_bool()));
    let _ = anubis_assert(AnubisValue::Bool((anubis_cmp(">=", sq_range.field_get("hi"), AnubisValue::Float(4f64))).as_bool() && (anubis_cmp("<=", sq_range.field_get("hi"), AnubisValue::Float(4.000001f64))).as_bool()));
    let mut div_range = anb_ieval(anb_parse_ast(anubis_mk_str("1/x".to_string())), anubis_neg(AnubisValue::Float(1f64)), AnubisValue::Float(1f64));
    let _ = anubis_assert(AnubisValue::Bool(!(div_range.field_get("ok")).as_bool()));
    let mut ln_range = anb_ieval(anb_parse_ast(anubis_mk_str("ln(x)".to_string())), AnubisValue::Float(0f64), AnubisValue::Float(1f64));
    let _ = anubis_assert(AnubisValue::Bool(!(ln_range.field_get("ok")).as_bool()));
    let mut tan_range = anb_ieval(anb_parse_ast(anubis_mk_str("tan(x)".to_string())), AnubisValue::Float(1f64), AnubisValue::Float(2f64));
    let _ = anubis_assert(AnubisValue::Bool(!(tan_range.field_get("ok")).as_bool()));
    let _ = anubis_assert(anubis_cmp("==", anb_ast_to_text(anb_simplify_bound(anb_parse_ast(anubis_mk_str("x/x".to_string())))), anubis_mk_str("x/x".to_string())));
    let _ = anubis_assert(anb_ast_smooth_ok(anb_parse_ast(anubis_mk_str("sin(x)+x^3".to_string()))));
    let _ = anubis_assert(AnubisValue::Bool(!(anb_ast_smooth_ok(anb_parse_ast(anubis_mk_str("abs(x)".to_string())))).as_bool()));
    let mut bf = anb_simplify_bound(anb_parse_ast(anubis_mk_str("x^2".to_string())));
    let mut bf1 = anb_simplify_bound(anb_deriv(bf.clone()));
    let mut bf2 = anb_simplify_bound(anb_deriv(bf1.clone()));
    let mut bf3 = anb_simplify_bound(anb_deriv(bf2.clone()));
    let mut bf4 = anb_simplify_bound(anb_deriv(bf3.clone()));
    let mut bres = anb_bound_step(bf.clone(), bf1.clone(), bf2.clone(), bf3.clone(), bf4.clone(), AnubisValue::Int(4), AnubisValue::Float(0f64), AnubisValue::Float(1f64), AnubisValue::Float(1f64), AnubisValue::Float(0.000001f64), AnubisValue::Int(0), AnubisValue::Int(0));
    let _ = anubis_assert(AnubisValue::Bool((anubis_cmp("<=", bres.field_get("lo"), AnubisValue::Float(0.3333333333333333f64))).as_bool() && (anubis_cmp(">=", bres.field_get("hi"), AnubisValue::Float(0.3333333333333333f64))).as_bool()));
    let _ = anubis_assert(anubis_cmp("<=", anubis_sub(bres.field_get("hi"), bres.field_get("lo")), AnubisValue::Float(0.000001f64)));
    let mut fold_probe = anb_ieval(anb_simplify_bound(anb_parse_ast(anubis_mk_str("1e16+1-1e16".to_string()))), AnubisValue::Float(0f64), AnubisValue::Float(1f64));
    let _ = anubis_assert(fold_probe.field_get("ok"));
    let _ = anubis_assert(AnubisValue::Bool((anubis_cmp("<=", fold_probe.field_get("lo"), AnubisValue::Float(1f64))).as_bool() && (anubis_cmp(">=", fold_probe.field_get("hi"), AnubisValue::Float(1f64))).as_bool()));
    let mut mid_f = anb_simplify_bound(anb_parse_ast(anubis_mk_str("sin(x)".to_string())));
    let mut mid_f1 = anb_simplify_bound(anb_deriv(mid_f.clone()));
    let mut mid_f2 = anb_simplify_bound(anb_deriv(mid_f1.clone()));
    let mut mid_f3 = anb_simplify_bound(anb_deriv(mid_f2.clone()));
    let mut mid_f4 = anb_simplify_bound(anb_deriv(mid_f3.clone()));
    let mut mid_res = anb_bound_step(mid_f.clone(), mid_f1.clone(), mid_f2.clone(), mid_f3.clone(), mid_f4.clone(), AnubisValue::Int(4), AnubisValue::Float(3.141092653589793f64), AnubisValue::Float(3.1420926535898106f64), anubis_sub(AnubisValue::Float(3.1420926535898106f64), AnubisValue::Float(3.141092653589793f64)), AnubisValue::Float(0.000001f64), AnubisValue::Int(0), AnubisValue::Int(0));
    let _ = anubis_assert(anubis_cmp("<=", mid_res.field_get("lo"), anubis_neg(AnubisValue::Float(0.000000000000000008537274556592414f64))));
    let _ = anubis_assert(anubis_cmp(">=", mid_res.field_get("hi"), anubis_neg(AnubisValue::Float(0.000000000000000008537274556592414f64))));
    let _ = anubis_assert(anubis_cmp("!=", anb_number_text(AnubisValue::Float(9223372036854776000f64)), anubis_mk_str("9223372036854775807".to_string())));
    let mut cea_a = anb_int_from_text(anubis_mk_str("1234567890123456789012345678901234567890".to_string()));
    let mut cea_b = anb_int_from_text(anubis_mk_str("-9876543210987654321098765432109876543210".to_string()));
    let mut cea_x = anb_int_xgcd(cea_a.clone(), cea_b.clone());
    let _ = anubis_assert(anubis_cmp("==", anb_int_to_text(cea_x.field_get("g")), anubis_mk_str("90000000009000000000900000000090".to_string())));
    let mut cea_bez = anb_int_add(anb_int_mul(cea_x.field_get("u"), cea_a.clone()), anb_int_mul(cea_x.field_get("v"), cea_b.clone()));
    let _ = anubis_assert(anubis_cmp("==", anb_int_cmp(cea_bez.clone(), cea_x.field_get("g")), AnubisValue::Int(0)));
    let _ = anubis_assert(AnubisValue::Bool((anb_big_is_zero((anb_int_mod(cea_a.clone(), cea_x.field_get("g"))).field_get("num"))).as_bool() && (anb_big_is_zero((anb_int_mod(cea_b.clone(), cea_x.field_get("g"))).field_get("num"))).as_bool()));
    let mut cea_base = anb_int_from_text(anubis_mk_str("123456789".to_string()));
    let mut cea_mod = anb_int_from_text(anubis_mk_str("998244353".to_string()));
    let mut cea_mp = anb_int_modpow(cea_base.clone(), anb_int_from_text(anubis_mk_str("1000".to_string())), cea_mod.clone());
    let _ = anubis_assert(anubis_cmp("==", anb_int_to_text(cea_mp.clone()), anubis_mk_str("215277794".to_string())));
    let mut cea_acc = anb_int_mod(anb_int_from_text(anubis_mk_str("1".to_string())), cea_mod.clone());
    let mut cea_i = AnubisValue::Int(0);
    while anubis_cmp("<", cea_i.clone(), AnubisValue::Int(1000)).as_bool() {
        cea_acc = anb_int_mod(anb_int_mul(cea_acc.clone(), cea_base.clone()), cea_mod.clone());
        cea_i = anubis_add(cea_i.clone(), AnubisValue::Int(1));
    }
    let _ = anubis_assert(anubis_cmp("==", anb_int_cmp(cea_mp.clone(), cea_acc.clone()), AnubisValue::Int(0)));
    let mut cea_inv = anb_int_modinv(anb_int_from_text(anubis_mk_str("12345".to_string())), anb_int_from_text(anubis_mk_str("1000003".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_int_to_text(cea_inv.clone()), anubis_mk_str("775863".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_int_to_text(anb_int_mod(anb_int_mul(cea_inv.clone(), anb_int_from_text(anubis_mk_str("12345".to_string()))), anb_int_from_text(anubis_mk_str("1000003".to_string())))), anubis_mk_str("1".to_string())));
    let mut cea_crt = anb_crt_combine(anubis_mk_list(vec![anb_int_from_text(anubis_mk_str("2".to_string())), anb_int_from_text(anubis_mk_str("3".to_string())), anb_int_from_text(anubis_mk_str("2".to_string()))]), anubis_mk_list(vec![anb_int_from_text(anubis_mk_str("3".to_string())), anb_int_from_text(anubis_mk_str("5".to_string())), anb_int_from_text(anubis_mk_str("7".to_string()))]));
    let _ = anubis_assert(AnubisValue::Bool((anubis_cmp("==", anb_int_to_text(cea_crt.field_get("x")), anubis_mk_str("23".to_string()))).as_bool() && (anubis_cmp("==", anb_int_to_text(cea_crt.field_get("modulus")), anubis_mk_str("105".to_string()))).as_bool()));
    let mut cea_pratt = anb_pratt_build(anb_big_from_text(anubis_mk_str("1000003".to_string())), AnubisValue::Int(0), AnubisValue::Int(0));
    let _ = anubis_assert(anubis_cmp("==", anubis_sha256(cea_pratt.field_get("json")), anubis_mk_str("d9db6f53abfabb449709f8683ad429da1ba84ca6de52b18e32200fad36db1d19".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_big_to_text(anb_find_divisor(anb_big_from_text(anubis_mk_str("1000001".to_string())))), anubis_mk_str("101".to_string())));
    let mut cea_p1 = anb_poly_lower(anb_parse_ast(anubis_mk_str("(x+1)^2".to_string())));
    let mut cea_p2 = anb_poly_lower(anb_parse_ast(anubis_mk_str("x^2+2*x+1".to_string())));
    let _ = anubis_assert(anb_poly_equal(cea_p1.field_get("coeffs"), cea_p2.field_get("coeffs")));
    let mut cea_p3 = anb_poly_lower(anb_parse_ast(anubis_mk_str("x^2-1".to_string())));
    let mut cea_p4 = anb_poly_lower(anb_parse_ast(anubis_mk_str("(x-1)^2".to_string())));
    let _ = anubis_assert(AnubisValue::Bool(!(anb_poly_equal(cea_p3.field_get("coeffs"), cea_p4.field_get("coeffs"))).as_bool()));
    let mut cea_rf = anb_rf_canon(anb_rf_lower(anb_parse_ast(anubis_mk_str("(x^2-1)/(x-1)".to_string()))));
    let mut cea_rfn = cea_rf.field_get("num");
    let mut cea_rfd = cea_rf.field_get("den");
    let _ = anubis_assert(anubis_cmp("==", anb_poly_coeffs_text(cea_rfn.clone()), anubis_mk_str("1,1".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_poly_coeffs_text(cea_rfd.clone()), anubis_mk_str("1".to_string())));
    let mut cea_sp = anb_poly_lower(anb_parse_ast(anubis_mk_str("(x^2-2)*(x-3)".to_string())));
    let mut cea_ss = anb_poly_squarefree(cea_sp.field_get("coeffs"));
    let mut cea_ch = anb_sturm_chain(cea_ss.clone());
    let mut cea_bound = anb_cauchy_bound(cea_ss.clone());
    let _ = anubis_assert(anubis_cmp("==", anubis_sub(anb_sturm_variations(cea_ch.clone(), anb_rat_neg(cea_bound.clone())), anb_sturm_variations(cea_ch.clone(), cea_bound.clone())), AnubisValue::Int(3)));
    let mut cea_iso = anb_sturm_isolate_all(cea_ch.clone(), cea_ss.clone());
    let _ = anubis_assert(anubis_cmp("==", (cea_iso.clone()).len_val(), AnubisValue::Int(3)));
    let _ = anubis_assert(AnubisValue::Bool((anubis_cmp("<", anb_rat_cmp((cea_iso.index_get(AnubisValue::Int(0))).field_get("hi"), (cea_iso.index_get(AnubisValue::Int(1))).field_get("lo")), AnubisValue::Int(0))).as_bool() && (anubis_cmp("<", anb_rat_cmp((cea_iso.index_get(AnubisValue::Int(1))).field_get("hi"), (cea_iso.index_get(AnubisValue::Int(2))).field_get("lo")), AnubisValue::Int(0))).as_bool()));
    let mut cea_sq2 = anb_poly_lower(anb_parse_ast(anubis_mk_str("x^2-2".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_rat_sign(anb_poly_eval(cea_sq2.field_get("coeffs"), anb_rat_from_frac_text(anubis_mk_str("3/2".to_string())))), AnubisValue::Int(1)));
    let _ = anubis_assert(anubis_cmp("==", anb_rat_sign(anb_poly_eval(cea_sq2.field_get("coeffs"), anb_rat_from_frac_text(anubis_mk_str("7/5".to_string())))), anubis_neg(AnubisValue::Int(1))));
    let _ = anubis_assert(anubis_cmp("==", anb_alg_cmp_order(anubis_mk_str("x^2-2".to_string()), anubis_mk_str("1".to_string()), anubis_mk_str("3/2".to_string()), anubis_mk_str("x-3/2".to_string()), anubis_mk_str("1".to_string()), anubis_mk_str("2".to_string())), anubis_mk_str("less".to_string())));
    let _ = anubis_assert(anubis_cmp("==", anb_alg_cmp_order(anubis_mk_str("x^2-4".to_string()), anubis_mk_str("1".to_string()), anubis_mk_str("3".to_string()), anubis_mk_str("x-2".to_string()), anubis_mk_str("3/2".to_string()), anubis_mk_str("5/2".to_string())), anubis_mk_str("equal".to_string())));
    println!("{}", anubis_mk_str("self-test: 104/104 Anubis-native invariants pass".to_string()).display_string());
    AnubisValue::Int(0)
}

fn anb_main() -> AnubisValue {
    __anb_stack_guard();
    let mut argv = anubis_args();
    if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", (argv.clone()).len_val(), AnubisValue::Int(0))).as_bool() || (anubis_cmp("==", argv.index_get(AnubisValue::Int(0)), anubis_mk_str("help".to_string()))).as_bool())).as_bool() || (anubis_cmp("==", argv.index_get(AnubisValue::Int(0)), anubis_mk_str("--help".to_string()))).as_bool()).as_bool() {
        let _ = anb_usage();
        return AnubisValue::Int(0);
    }
    let mut op = argv.index_get(AnubisValue::Int(0));
    if anubis_cmp("==", op.clone(), anubis_mk_str("self-test".to_string())).as_bool() {
        let _ = anb_run_native_self_test();
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("measure-mul".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(6));
        let mut left = anb_measurement(anb_arg_float(argv.clone(), AnubisValue::Int(1)), anb_arg_float(argv.clone(), AnubisValue::Int(2)), anubis_mk_str("left".to_string()));
        let mut right = anb_measurement(anb_arg_float(argv.clone(), AnubisValue::Int(3)), anb_arg_float(argv.clone(), AnubisValue::Int(4)), anubis_mk_str("right".to_string()));
        println!("{}", anb_measurement_text(anb_multiply_measurements(left.clone(), right.clone(), argv.index_get(AnubisValue::Int(5)))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("uncertain-ohm".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(5));
        let mut voltage = anb_measurement(anb_arg_float(argv.clone(), AnubisValue::Int(1)), anb_arg_float(argv.clone(), AnubisValue::Int(2)), anubis_mk_str("V".to_string()));
        let mut current = anb_measurement(anb_arg_float(argv.clone(), AnubisValue::Int(3)), anb_arg_float(argv.clone(), AnubisValue::Int(4)), anubis_mk_str("A".to_string()));
        let mut resistance = anb_divide_measurements(voltage.clone(), current.clone(), anubis_mk_str("ohm".to_string()));
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("resistance=".to_string())), anb_number_text(resistance.field_get("value"))), anubis_mk_str(" ± ".to_string())), anb_number_text(anb_rounded(resistance.field_get("uncertainty"), AnubisValue::Float(12f64)))), anubis_mk_str(" ohm relative=".to_string())), anb_number_text(anb_rounded(anubis_mul(anb_relative_uncertainty(resistance.clone()), AnubisValue::Float(100f64)), AnubisValue::Float(12f64)))), anubis_mk_str("%".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("matrix2".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(5));
        let mut matrix = anb_matrix2(argv.clone(), AnubisValue::Int(1));
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("det=".to_string())), anb_number_text(anb_determinant2(matrix.clone()))), anubis_mk_str(" inverse=".to_string())), anb_matrix_text(anb_inverse2(matrix.clone()))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("solve2".to_string())).as_bool() {
        let _ = anb_solve_linear2(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("integrate-x2".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(4));
        let mut panels = anb_arg_int(argv.clone(), AnubisValue::Int(3));
        let mut area = anb_integrate_square_simpson(anb_arg_float(argv.clone(), AnubisValue::Int(1)), anb_arg_float(argv.clone(), AnubisValue::Int(2)), panels.clone());
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=estimated integral=".to_string())), anb_number_text(anb_rounded(area.clone(), AnubisValue::Float(12f64)))), anubis_mk_str(" method=simpson panels=".to_string())), panels.clone()).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("derivative-x3".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
        let mut x = anb_arg_float(argv.clone(), AnubisValue::Int(1));
        let mut h = anb_arg_float(argv.clone(), AnubisValue::Int(2));
        let mut estimate = anb_derivative_cube(x.clone(), h.clone());
        let mut exact = anubis_mul(anubis_mul(AnubisValue::Float(3f64), x.clone()), x.clone());
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=estimated derivative=".to_string())), anb_number_text(anb_rounded(estimate.clone(), AnubisValue::Float(12f64)))), anubis_mk_str(" truncation-probe=".to_string())), anb_number_text(anb_rounded(anubis_abs(anubis_sub(estimate.clone(), exact.clone())), AnubisValue::Float(12f64)))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("ph".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        let mut concentration = anb_arg_float(argv.clone(), AnubisValue::Int(1));
        if anubis_cmp("<=", concentration.clone(), AnubisValue::Float(0f64)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("hydrogen concentration must be positive".to_string()));
        }
        let mut value = anubis_neg(anubis_log10(concentration.clone()));
        let mut class = if (anubis_cmp("<", value.clone(), AnubisValue::Float(7f64))).as_bool() { anubis_mk_str("acidic".to_string()) } else { if (anubis_cmp(">", value.clone(), AnubisValue::Float(7f64))).as_bool() { anubis_mk_str("basic".to_string()) } else { anubis_mk_str("neutral".to_string()) } };
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("pH=".to_string())), anb_number_text(value.clone())), anubis_mk_str(" classification=".to_string())), class.clone()).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("dilute".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(4));
        let mut initial_c = anb_arg_float(argv.clone(), AnubisValue::Int(1));
        let mut initial_v = anb_arg_float(argv.clone(), AnubisValue::Int(2));
        let mut final_c = anb_arg_float(argv.clone(), AnubisValue::Int(3));
        if AnubisValue::Bool((anubis_cmp("<=", final_c.clone(), AnubisValue::Float(0f64))).as_bool() || (anubis_cmp("<", initial_c.clone(), final_c.clone())).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("dilution requires 0 < final concentration <= initial concentration".to_string()));
        }
        let mut final_v = anubis_div(anubis_mul(initial_c.clone(), initial_v.clone()), final_c.clone());
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("final-volume=".to_string())), anb_number_text(final_v.clone())), anubis_mk_str(" L solvent-to-add=".to_string())), anb_number_text(anubis_sub(final_v.clone(), initial_v.clone()))), anubis_mk_str(" L".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("relativity".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        let mut beta = anb_arg_float(argv.clone(), AnubisValue::Int(1));
        if anubis_cmp(">=", anubis_abs(beta.clone()), AnubisValue::Float(1f64)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("relativity beta requires |v/c| < 1".to_string()));
        }
        let mut gamma = anubis_div(AnubisValue::Float(1f64), anubis_sqrt(anubis_sub(AnubisValue::Float(1f64), anubis_mul(beta.clone(), beta.clone()))));
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("gamma=".to_string())), anb_number_text(gamma.clone())), anubis_mk_str(" time-dilation=".to_string())), anb_number_text(gamma.clone())), anubis_mk_str(" length-factor=".to_string())), anb_number_text(anubis_div(AnubisValue::Float(1f64), gamma.clone()))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("decibel-power".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        let mut ratio = anb_arg_float(argv.clone(), AnubisValue::Int(1));
        if anubis_cmp("<=", ratio.clone(), AnubisValue::Float(0f64)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("power ratio must be positive".to_string()));
        }
        println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anb_number_text(anubis_mul(AnubisValue::Float(10f64), anubis_log10(ratio.clone())))), anubis_mk_str(" dB".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("blackbody".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        let mut temperature = anb_arg_float(argv.clone(), AnubisValue::Int(1));
        if anubis_cmp("<=", temperature.clone(), AnubisValue::Float(0f64)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("temperature must be positive".to_string()));
        }
        let mut wavelength = anubis_div(AnubisValue::Float(2897771.955f64), temperature.clone());
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("peak-wavelength=".to_string())), anb_number_text(wavelength.clone())), anubis_mk_str(" nm band=".to_string())), anb_spectrum_text(anb_spectrum_band(wavelength.clone()))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("kinetic-sensitivity".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
        let mut mass = anb_arg_float(argv.clone(), AnubisValue::Int(1));
        let mut speed = anb_arg_float(argv.clone(), AnubisValue::Int(2));
        let mut energy = anubis_mul(anubis_mul(anubis_mul(AnubisValue::Float(0.5f64), mass.clone()), speed.clone()), speed.clone());
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("energy=".to_string())), anb_number_text(energy.clone())), anubis_mk_str(" J elasticity[mass]=1 elasticity[speed]=2".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("claim-card".to_string())).as_bool() {
        let _ = anb_projectile_claim_card(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("diff".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        let mut source = argv.index_get(AnubisValue::Int(1));
        let mut raw = anb_parse_ast(source.clone());
        let mut ast = anb_simplify(raw.clone());
        let mut derived = anb_simplify(anb_deriv(ast.clone()));
        let mut check = anb_verify_derivative(ast.clone(), derived.clone());
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("d/dx[".to_string())), source.clone()), anubis_mk_str("] = ".to_string())), anb_ast_to_text(derived.clone())).display_string());
        if anb_has_where_defined_convention(raw.clone()).as_bool() {
            println!("{}", anubis_mk_str("domain-caveat=simplification assumed subexpressions defined (u/u, u-u, u^0, 0*u); result valid only on the original expression's domain".to_string()).display_string());
        }
        let mut probe_note = anubis_mk_str("".to_string());
        if anubis_cmp(">", check.field_get("skipped"), AnubisValue::Int(0)).as_bool() {
            probe_note = anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str(" skipped-unstable-probe=".to_string())), check.field_get("skipped"));
        }
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=checked check=numeric points=".to_string())), check.field_get("points")), anubis_mk_str(" max-rel-dev=".to_string())), anb_number_text(check.field_get("max_dev"))), anubis_mk_str(" tolerance=0.0001".to_string())), probe_note.clone()), anubis_mk_str(" assurance=numeric-sample-check(not-proof-of-identity)".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("rat".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        let mut ast = anb_parse_ast(argv.index_get(AnubisValue::Int(1)));
        let mut exact = anb_rat_eval_ast(ast.clone());
        let mut approx = anb_rat_to_f64(exact.clone());
        let mut approx_text = anubis_mk_str("not-representable-in-float64".to_string());
        if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", approx.clone(), approx.clone())).as_bool() && (anubis_cmp("<=", approx.clone(), AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64))).as_bool())).as_bool() && (anubis_cmp(">=", approx.clone(), anubis_neg(AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64)))).as_bool()).as_bool() {
            approx_text = anb_number_text(approx.clone());
        }
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=exact parsed=".to_string())), anb_ast_to_text(ast.clone())), anubis_mk_str(" exact=".to_string())), anb_rat_to_text(exact.clone())), anubis_mk_str(" approx=".to_string())), approx_text.clone()).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("pack-route".to_string())).as_bool() {
        let _ = anb_cmd_pack_route(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("canon".to_string())).as_bool() {
        let _ = anb_cmd_canon(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("poly-canon".to_string())).as_bool() {
        let _ = anb_cmd_poly_canon(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("poly-eq".to_string())).as_bool() {
        let _ = anb_cmd_poly_eq(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("poly-gcd".to_string())).as_bool() {
        let _ = anb_cmd_poly_gcd(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("ratfunc-canon".to_string())).as_bool() {
        let _ = anb_cmd_ratfunc_canon(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("roots-isolate".to_string())).as_bool() {
        let _ = anb_cmd_roots_isolate(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("alg-sign".to_string())).as_bool() {
        let _ = anb_cmd_alg_sign(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("alg-cmp".to_string())).as_bool() {
        let _ = anb_cmd_alg_cmp(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("xgcd".to_string())).as_bool() {
        let _ = anb_cmd_xgcd(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("mod-pow".to_string())).as_bool() {
        let _ = anb_cmd_mod_pow(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("test-exists".to_string())).as_bool() {
        let _ = anb_cmd_test_exists(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("claim-cites-test".to_string())).as_bool() {
        let _ = anb_cmd_claim_cites_test(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("decision-rank".to_string())).as_bool() {
        let _ = anb_cmd_decision_rank(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("mod-inv".to_string())).as_bool() {
        let _ = anb_cmd_mod_inv(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("crt".to_string())).as_bool() {
        let _ = anb_cmd_crt(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("divides".to_string())).as_bool() {
        let _ = anb_cmd_divides(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("prime-cert".to_string())).as_bool() {
        let _ = anb_cmd_prime_cert(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("eval".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        let _ = anb_print_number(anb_evaluate_expression(argv.index_get(AnubisValue::Int(1)), anubis_map_lit(vec![])));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("worksheet".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        let _ = anb_run_worksheet(argv.index_get(AnubisValue::Int(1)));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("big-add".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
        println!("{}", anb_big_to_text(anb_big_add(anb_big_from_text(argv.index_get(AnubisValue::Int(1))), anb_big_from_text(argv.index_get(AnubisValue::Int(2))))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("big-mul".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
        println!("{}", anb_big_to_text(anb_big_mul(anb_big_from_text(argv.index_get(AnubisValue::Int(1))), anb_big_from_text(argv.index_get(AnubisValue::Int(2))))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("big-pow".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
        if anubis_cmp(">", (argv.index_get(AnubisValue::Int(1))).len_val(), AnubisValue::Int(1000)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("big-pow base is capped at 1000 digits (compute budget); fail closed".to_string()));
        }
        println!("{}", anb_big_to_text(anb_big_pow(anb_big_from_text(argv.index_get(AnubisValue::Int(1))), anb_arg_int(argv.clone(), AnubisValue::Int(2)))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("big-fact".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        println!("{}", anb_big_to_text(anb_big_fact(anb_arg_int(argv.clone(), AnubisValue::Int(1)))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("big-ncr".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
        println!("{}", anb_big_to_text(anb_big_ncr(anb_arg_int(argv.clone(), AnubisValue::Int(1)), anb_arg_int(argv.clone(), AnubisValue::Int(2)))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("integrate".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(5));
        let mut source = argv.index_get(AnubisValue::Int(1));
        let mut a = anb_arg_float(argv.clone(), AnubisValue::Int(2));
        let mut b = anb_arg_float(argv.clone(), AnubisValue::Int(3));
        let mut panels = anb_arg_int(argv.clone(), AnubisValue::Int(4));
        let mut coarse = anb_simpson_general(source.clone(), a.clone(), b.clone(), panels.clone());
        let mut fine = anb_simpson_general(source.clone(), a.clone(), b.clone(), anubis_mul(panels.clone(), AnubisValue::Int(2)));
        let mut estimate = anubis_div(anubis_mul(anubis_abs(anubis_sub(fine.clone(), coarse.clone())), AnubisValue::Float(16f64)), AnubisValue::Float(15f64));
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=estimated integral=".to_string())), anb_number_text(anb_rounded(coarse.clone(), AnubisValue::Float(12f64)))), anubis_mk_str(" method=simpson panels=".to_string())), panels.clone()), anubis_mk_str(" richardson-error-estimate=".to_string())), anb_number_text(estimate.clone())), anubis_mk_str(" assurance=estimate-not-bound(grid-limited) hint=integrate-bound-for-a-certified-enclosure".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("integrate-adaptive".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(5));
        let mut source = argv.index_get(AnubisValue::Int(1));
        let mut a = anb_arg_float(argv.clone(), AnubisValue::Int(2));
        let mut b = anb_arg_float(argv.clone(), AnubisValue::Int(3));
        let mut tol = anb_arg_float(argv.clone(), AnubisValue::Int(4));
        if anubis_cmp("<=", tol.clone(), AnubisValue::Float(0f64)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("integrate-adaptive tolerance must be positive".to_string()));
        }
        if anubis_cmp(">=", a.clone(), b.clone()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("integrate-adaptive requires a < b".to_string()));
        }
        let mut seeds = AnubisValue::Int(32);
        let mut width = anubis_div(anubis_sub(b.clone(), a.clone()), seeds.clone());
        let mut total = AnubisValue::Float(0f64);
        let mut error_sum = AnubisValue::Float(0f64);
        let mut evals = AnubisValue::Int(0);
        let mut i = AnubisValue::Int(0);
        while anubis_cmp("<", i.clone(), seeds.clone()).as_bool() {
            let mut left_edge = anubis_add(a.clone(), anubis_mul(i.clone(), width.clone()));
            let mut right_edge = anubis_add(a.clone(), anubis_mul(anubis_add(i.clone(), AnubisValue::Int(1)), width.clone()));
            let mut mid = anubis_div(anubis_add(left_edge.clone(), right_edge.clone()), AnubisValue::Float(2f64));
            let mut fa = anb_adaptive_eval(source.clone(), left_edge.clone());
            let mut fm = anb_adaptive_eval(source.clone(), mid.clone());
            let mut fb = anb_adaptive_eval(source.clone(), right_edge.clone());
            let mut whole = anubis_div(anubis_mul(anubis_add(anubis_add(fa.clone(), anubis_mul(AnubisValue::Float(4f64), fm.clone())), fb.clone()), anubis_sub(right_edge.clone(), left_edge.clone())), AnubisValue::Float(6f64));
            let mut piece = anb_adaptive_step(source.clone(), left_edge.clone(), right_edge.clone(), fa.clone(), fm.clone(), fb.clone(), whole.clone(), anubis_div(tol.clone(), seeds.clone()), AnubisValue::Int(0), anubis_add(evals.clone(), AnubisValue::Int(3)));
            total = anubis_add(total.clone(), piece.field_get("value"));
            error_sum = anubis_add(error_sum.clone(), piece.field_get("error"));
            evals = piece.field_get("evals");
            i = anubis_add(i.clone(), AnubisValue::Int(1));
        }
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=estimated integral=".to_string())), anb_number_text(total.clone())), anubis_mk_str(" method=adaptive-simpson evals=".to_string())), evals.clone()), anubis_mk_str(" achieved-error-estimate=".to_string())), anb_number_text(error_sum.clone())), anubis_mk_str(" tolerance=".to_string())), anb_number_text(tol.clone())), anubis_mk_str(" assurance=refuses-when-unconverged(local-estimate)".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("integrate-bound".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(5));
        let mut source = argv.index_get(AnubisValue::Int(1));
        let mut a = anb_arg_float(argv.clone(), AnubisValue::Int(2));
        let mut b = anb_arg_float(argv.clone(), AnubisValue::Int(3));
        let mut tol = anb_arg_float(argv.clone(), AnubisValue::Int(4));
        if anubis_cmp("<=", tol.clone(), AnubisValue::Float(0f64)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("integrate-bound tolerance must be positive".to_string()));
        }
        if anubis_cmp(">=", a.clone(), b.clone()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("integrate-bound requires a < b".to_string()));
        }
        let mut f = anb_simplify_bound(anb_parse_ast(source.clone()));
        let mut vars = anb_collect_vars(f.clone(), anubis_map_lit(vec![]));
        for mut name in anubis_iter(vars.clone()) {
            if anubis_cmp("!=", name.clone(), anubis_mk_str("x".to_string())).as_bool() {
                let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("integrate-bound: unknown identifier '".to_string())), name.clone()), anubis_mk_str("'; only x is bound in the integrand".to_string())));
            }
        }
        let mut smooth = anb_ast_smooth_ok(f.clone());
        let mut f1 = anb_mk_num(AnubisValue::Float(0f64));
        let mut f2 = anb_mk_num(AnubisValue::Float(0f64));
        let mut f3 = anb_mk_num(AnubisValue::Float(0f64));
        let mut f4 = anb_mk_num(AnubisValue::Float(0f64));
        let mut taylor_degree = AnubisValue::Int(0);
        if smooth.clone().as_bool() {
            f1 = anb_simplify_bound(anb_deriv(f.clone()));
            f2 = anb_simplify_bound(anb_deriv(f1.clone()));
            if anubis_cmp("<=", anb_ast_size(f2.clone()), AnubisValue::Int(20000)).as_bool() {
                taylor_degree = AnubisValue::Int(2);
                f3 = anb_simplify_bound(anb_deriv(f2.clone()));
                f4 = anb_simplify_bound(anb_deriv(f3.clone()));
                if anubis_cmp("<=", anb_ast_size(f4.clone()), AnubisValue::Int(20000)).as_bool() {
                    taylor_degree = AnubisValue::Int(4);
                }
            }
        }
        let mut result = anb_bound_step(f.clone(), f1.clone(), f2.clone(), f3.clone(), f4.clone(), taylor_degree.clone(), a.clone(), b.clone(), anubis_sub(b.clone(), a.clone()), tol.clone(), AnubisValue::Int(0), AnubisValue::Int(0));
        let mut final_iv = anb_iv_out(result.field_get("lo"), result.field_get("hi"));
        if AnubisValue::Bool(!(final_iv.field_get("ok")).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("integrate-bound: non-finite enclosure; fail closed".to_string()));
        }
        let mut width = anubis_sub(final_iv.field_get("hi"), final_iv.field_get("lo"));
        if anubis_cmp(">", width.clone(), tol.clone()).as_bool() {
            let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("integrate-bound: achieved certified width ".to_string())), anb_number_text(width.clone())), anubis_mk_str(" exceeds the requested tolerance ".to_string())), anb_number_text(tol.clone())), anubis_mk_str(" after accumulation rounding; fail closed (try a larger tolerance)".to_string())));
        }
        let mut mode = anubis_mk_str("range-only(non-smooth-integrand)".to_string());
        if anubis_cmp("==", taylor_degree.clone(), AnubisValue::Int(2)).as_bool() {
            mode = anubis_mk_str("smooth-taylor2".to_string());
        }
        if anubis_cmp("==", taylor_degree.clone(), AnubisValue::Int(4)).as_bool() {
            mode = anubis_mk_str("smooth-taylor4".to_string());
        }
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=bounded integral-enclosure=[".to_string())), anb_number_text(final_iv.field_get("lo"))), anubis_mk_str(",".to_string())), anb_number_text(final_iv.field_get("hi"))), anubis_mk_str("] width=".to_string())), anb_number_text(width.clone())), anubis_mk_str(" method=adaptive-interval mode=".to_string())), mode.clone()), anubis_mk_str(" subintervals=".to_string())), result.field_get("nodes")), anubis_mk_str(" taylor-accepted=".to_string())), result.field_get("taylored")), anubis_mk_str(" range-accepted=".to_string())), result.field_get("ranged")), anubis_mk_str(" tolerance=".to_string())), anb_number_text(tol.clone())), anubis_mk_str(" assurance=certified-bound(outward-rounded-f64;libm<=2ulp-model;implementation-tested-not-mechanized)".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("range-bound".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(4));
        let mut source = argv.index_get(AnubisValue::Int(1));
        let mut xlo = anb_arg_float(argv.clone(), AnubisValue::Int(2));
        let mut xhi = anb_arg_float(argv.clone(), AnubisValue::Int(3));
        if anubis_cmp(">", xlo.clone(), xhi.clone()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("range-bound requires lo <= hi".to_string()));
        }
        let mut f = anb_simplify_bound(anb_parse_ast(source.clone()));
        let mut vars = anb_collect_vars(f.clone(), anubis_map_lit(vec![]));
        for mut name in anubis_iter(vars.clone()) {
            if anubis_cmp("!=", name.clone(), anubis_mk_str("x".to_string())).as_bool() {
                let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("range-bound: unknown identifier '".to_string())), name.clone()), anubis_mk_str("'; only x is bound".to_string())));
            }
        }
        let mut enclosure = anb_ieval(f.clone(), xlo.clone(), xhi.clone());
        if AnubisValue::Bool(!(enclosure.field_get("ok")).as_bool()).as_bool() {
            let mut why = enclosure.field_get("why");
            let _ = anubis_panic(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("range-bound: cannot certify a range: ".to_string())), why.clone()), anubis_mk_str("; fail closed".to_string())));
        }
        let mut final_iv = anb_iv_out(enclosure.field_get("lo"), enclosure.field_get("hi"));
        if AnubisValue::Bool(!(final_iv.field_get("ok")).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("range-bound: non-finite enclosure; fail closed".to_string()));
        }
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=bounded range-enclosure=[".to_string())), anb_number_text(final_iv.field_get("lo"))), anubis_mk_str(",".to_string())), anb_number_text(final_iv.field_get("hi"))), anubis_mk_str("] assurance=certified-superset-of-range(outward-rounded-f64;libm<=2ulp-model;implementation-tested-not-mechanized)".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("derivative".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(4));
        let mut source = argv.index_get(AnubisValue::Int(1));
        let mut at = anb_arg_float(argv.clone(), AnubisValue::Int(2));
        let mut step = anb_arg_float(argv.clone(), AnubisValue::Int(3));
        if anubis_cmp("<=", step.clone(), AnubisValue::Float(0f64)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("derivative step must be positive".to_string()));
        }
        let mut coarse = anubis_div(anubis_sub(anb_evaluate_expression(source.clone(), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), anubis_add(at.clone(), step.clone()))])), anb_evaluate_expression(source.clone(), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), anubis_sub(at.clone(), step.clone()))]))), anubis_mul(AnubisValue::Float(2f64), step.clone()));
        let mut half = anubis_div(step.clone(), AnubisValue::Float(2f64));
        let mut fine = anubis_div(anubis_sub(anb_evaluate_expression(source.clone(), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), anubis_add(at.clone(), half.clone()))])), anb_evaluate_expression(source.clone(), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), anubis_sub(at.clone(), half.clone()))]))), anubis_mul(AnubisValue::Float(2f64), half.clone()));
        let mut probe = anubis_div(anubis_abs(anubis_sub(fine.clone(), coarse.clone())), AnubisValue::Float(3f64));
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=estimated derivative=".to_string())), anb_number_text(fine.clone())), anubis_mk_str(" method=central-difference step=".to_string())), anb_number_text(half.clone())), anubis_mk_str(" richardson-probe=".to_string())), anb_number_text(probe.clone())), anubis_mk_str(" assurance=estimate-not-bound(grid-limited)".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("solve".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(4));
        let mut source = argv.index_get(AnubisValue::Int(1));
        let mut lo = anb_arg_float(argv.clone(), AnubisValue::Int(2));
        let mut hi = anb_arg_float(argv.clone(), AnubisValue::Int(3));
        if anubis_cmp(">=", lo.clone(), hi.clone()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("solve requires lo < hi".to_string()));
        }
        let mut flo = anb_evaluate_expression(source.clone(), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), lo.clone())]));
        let mut fhi = anb_evaluate_expression(source.clone(), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), hi.clone())]));
        if anubis_cmp("==", flo.clone(), AnubisValue::Float(0f64)).as_bool() {
            println!("{}", anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=estimated root=".to_string())), anb_number_text(lo.clone())), anubis_mk_str(" residual=0 method=bisection iterations=0".to_string())).display_string());
            return AnubisValue::Int(0);
        }
        if anubis_cmp("==", fhi.clone(), AnubisValue::Float(0f64)).as_bool() {
            println!("{}", anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=estimated root=".to_string())), anb_number_text(hi.clone())), anubis_mk_str(" residual=0 method=bisection iterations=0".to_string())).display_string());
            return AnubisValue::Int(0);
        }
        if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp(">", flo.clone(), AnubisValue::Float(0f64))).as_bool() && (anubis_cmp(">", fhi.clone(), AnubisValue::Float(0f64))).as_bool())).as_bool() || (AnubisValue::Bool((anubis_cmp("<", flo.clone(), AnubisValue::Float(0f64))).as_bool() && (anubis_cmp("<", fhi.clone(), AnubisValue::Float(0f64))).as_bool())).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("solve requires a sign change on [lo, hi]; fail closed rather than guess".to_string()));
        }
        let mut iterations = AnubisValue::Int(0);
        while anubis_cmp("<", iterations.clone(), AnubisValue::Int(200)).as_bool() {
            let mut mid = anubis_div(anubis_add(lo.clone(), hi.clone()), AnubisValue::Float(2f64));
            if AnubisValue::Bool((anubis_cmp("==", mid.clone(), lo.clone())).as_bool() || (anubis_cmp("==", mid.clone(), hi.clone())).as_bool()).as_bool() {
                break;
            }
            let mut fmid = anb_evaluate_expression(source.clone(), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), mid.clone())]));
            if anubis_cmp("==", fmid.clone(), AnubisValue::Float(0f64)).as_bool() {
                lo = mid.clone();
                hi = mid.clone();
                break;
            }
            if anubis_cmp("==", anubis_cmp(">", fmid.clone(), AnubisValue::Float(0f64)), anubis_cmp(">", flo.clone(), AnubisValue::Float(0f64))).as_bool() {
                lo = mid.clone();
                flo = fmid.clone();
            } else {
                hi = mid.clone();
                fhi = fmid.clone();
            }
            iterations = anubis_add(iterations.clone(), AnubisValue::Int(1));
        }
        let mut root = anubis_div(anubis_add(lo.clone(), hi.clone()), AnubisValue::Float(2f64));
        let mut residual = anubis_abs(anb_evaluate_expression(source.clone(), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), root.clone())])));
        let mut probe_ast = anb_parse_ast(source.clone());
        let mut h = anubis_mul(AnubisValue::Float(0.000000014901161193847656f64), anubis_max(vec![AnubisValue::Float(1f64), anubis_abs(root.clone())]));
        let mut f_up = anb_eval_ast(probe_ast.clone(), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), anubis_add(root.clone(), h.clone()))]));
        let mut f_dn = anb_eval_ast(probe_ast.clone(), anubis_map_lit(vec![((anubis_mk_str("x".to_string())).display_string(), anubis_sub(root.clone(), h.clone()))]));
        let mut fprime = anubis_div(anubis_sub(f_up.clone(), f_dn.clone()), anubis_mul(AnubisValue::Float(2f64), h.clone()));
        let mut diagnostics = anubis_mk_str(" root-error-estimate=unavailable(derivative-probe-failed)".to_string());
        if AnubisValue::Bool((AnubisValue::Bool((anubis_cmp("==", fprime.clone(), fprime.clone())).as_bool() && (anubis_cmp("<=", fprime.clone(), AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64))).as_bool())).as_bool() && (anubis_cmp(">=", fprime.clone(), anubis_neg(AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64)))).as_bool()).as_bool() {
            if anubis_cmp("<", anubis_abs(fprime.clone()), AnubisValue::Float(0.000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000001f64)).as_bool() {
                diagnostics = anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str(" derivative-estimate=".to_string())), anb_number_text(fprime.clone())), anubis_mk_str(" root-error-estimate=indeterminate(derivative-vanishes-at-root;residual-cannot-bound-root-error)".to_string()));
            } else {
                let mut amplification = anubis_div(AnubisValue::Float(1f64), anubis_abs(fprime.clone()));
                let mut first_order = anubis_mul(residual.clone(), amplification.clone());
                let mut estimate = anubis_max(vec![anubis_div(anubis_sub(hi.clone(), lo.clone()), AnubisValue::Float(2f64)), first_order.clone()]);
                if anubis_cmp("<=", estimate.clone(), AnubisValue::Float(179769313486231570000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000f64)).as_bool() {
                    diagnostics = anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str(" derivative-estimate=".to_string())), anb_number_text(fprime.clone())), anubis_mk_str(" condition-amplification=".to_string())), anb_number_text(amplification.clone())), anubis_mk_str(" root-error-estimate=".to_string())), anb_number_text(estimate.clone()));
                }
            }
        }
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("status=estimated root=".to_string())), anb_number_text(root.clone())), anubis_mk_str(" residual=".to_string())), anb_number_text(residual.clone())), anubis_mk_str(" method=bisection iterations=".to_string())), iterations.clone()), diagnostics.clone()), anubis_mk_str(" assurance=estimate-not-bound(first-order)".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("add".to_string())).as_bool() {
        let _ = anb_print_number(anubis_add(anb_binary_float_left(argv.clone()), anb_binary_float_right(argv.clone())));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("sub".to_string())).as_bool() {
        let _ = anb_print_number(anubis_sub(anb_binary_float_left(argv.clone()), anb_binary_float_right(argv.clone())));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("mul".to_string())).as_bool() {
        let _ = anb_print_number(anubis_mul(anb_binary_float_left(argv.clone()), anb_binary_float_right(argv.clone())));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("div".to_string())).as_bool() {
        let mut numerator = anb_binary_float_left(argv.clone());
        let mut denominator = anb_binary_float_right(argv.clone());
        if anubis_cmp("==", denominator.clone(), AnubisValue::Float(0f64)).as_bool() {
            let _ = anubis_panic(anubis_mk_str("division by zero has no finite result; fail closed".to_string()));
        }
        let _ = anb_print_number(anubis_div(numerator.clone(), denominator.clone()));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("pow".to_string())).as_bool() {
        let _ = anb_print_number(anubis_pow(anb_binary_float_left(argv.clone()), anb_binary_float_right(argv.clone())));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("sqrt".to_string())).as_bool() {
        let _ = anb_print_number(anubis_sqrt(anb_unary_float(argv.clone())));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("cbrt".to_string())).as_bool() {
        let _ = anb_print_number(anubis_cbrt(anb_unary_float(argv.clone())));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("sin".to_string())).as_bool() {
        let _ = anb_print_number(anubis_sin(anb_unary_float(argv.clone())));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("cos".to_string())).as_bool() {
        let _ = anb_print_number(anubis_cos(anb_unary_float(argv.clone())));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("tan".to_string())).as_bool() {
        let _ = anb_print_number(anubis_tan(anb_unary_float(argv.clone())));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("sin-deg".to_string())).as_bool() {
        let _ = anb_print_number(anubis_sin(anubis_div(anubis_mul(anb_unary_float(argv.clone()), anubis_pi()), AnubisValue::Float(180f64))));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("hypot".to_string())).as_bool() {
        let _ = anb_print_number(anubis_hypot(anb_binary_float_left(argv.clone()), anb_binary_float_right(argv.clone())));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("ln".to_string())).as_bool() {
        let _ = anb_print_number(anubis_ln(anb_unary_float(argv.clone())));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("log10".to_string())).as_bool() {
        let _ = anb_print_number(anubis_log10(anb_unary_float(argv.clone())));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("exp".to_string())).as_bool() {
        let _ = anb_print_number(anubis_exp(anb_unary_float(argv.clone())));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("hex".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        println!("{}", anb_format_hex(anb_strict_int(argv.index_get(AnubisValue::Int(1)))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("bin".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        println!("{}", anb_format_binary(anb_strict_int(argv.index_get(AnubisValue::Int(1)))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("band".to_string())).as_bool() {
        println!("{}", anubis_band(anb_binary_int_left(argv.clone()), anb_binary_int_right(argv.clone())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("bor".to_string())).as_bool() {
        println!("{}", anubis_bor(anb_binary_int_left(argv.clone()), anb_binary_int_right(argv.clone())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("bxor".to_string())).as_bool() {
        println!("{}", anubis_bxor(anb_binary_int_left(argv.clone()), anb_binary_int_right(argv.clone())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("shl".to_string())).as_bool() {
        let mut value = anb_binary_int_left(argv.clone());
        println!("{}", anubis_shl(value.clone(), anb_shift_count(argv.clone())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("shr".to_string())).as_bool() {
        let mut value = anb_binary_int_left(argv.clone());
        println!("{}", anubis_shr(value.clone(), anb_shift_count(argv.clone())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("gcd".to_string())).as_bool() {
        let mut gcd_a = anb_binary_int_left(argv.clone());
        let mut gcd_b = anb_binary_int_right(argv.clone());
        let _ = anb_require_abs_representable(gcd_a.clone(), anubis_mk_str("a".to_string()));
        let _ = anb_require_abs_representable(gcd_b.clone(), anubis_mk_str("b".to_string()));
        println!("{}", anb_gcd_safe(gcd_a.clone(), gcd_b.clone()).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("fact".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        println!("{}", anubis_factorial(anb_strict_int(argv.index_get(AnubisValue::Int(1)))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("stats".to_string())).as_bool() {
        let _ = anb_stats(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("quadratic".to_string())).as_bool() {
        let _ = anb_quadratic(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("lerp".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(4));
        let _ = anb_print_number(anubis_add(anb_arg_float(argv.clone(), AnubisValue::Int(1)), anubis_mul(anubis_sub(anb_arg_float(argv.clone(), AnubisValue::Int(2)), anb_arg_float(argv.clone(), AnubisValue::Int(1))), anb_arg_float(argv.clone(), AnubisValue::Int(3)))));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("percent-error".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
        println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anb_number_text(anb_rounded(anubis_mul(anubis_div(anubis_abs(anubis_sub(anb_arg_float(argv.clone(), AnubisValue::Int(1)), anb_arg_float(argv.clone(), AnubisValue::Int(2)))), anubis_abs(anb_arg_float(argv.clone(), AnubisValue::Int(2)))), AnubisValue::Float(100f64)), AnubisValue::Float(12f64)))), anubis_mk_str("%".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("ncr".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
        println!("{}", anb_choose(anb_arg_int(argv.clone(), AnubisValue::Int(1)), anb_arg_int(argv.clone(), AnubisValue::Int(2))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("lcm".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
        let mut a = anb_arg_int(argv.clone(), AnubisValue::Int(1));
        let mut b = anb_arg_int(argv.clone(), AnubisValue::Int(2));
        let _ = anb_require_abs_representable(a.clone(), anubis_mk_str("a".to_string()));
        let _ = anb_require_abs_representable(b.clone(), anubis_mk_str("b".to_string()));
        let mut g = anb_gcd_safe(a.clone(), b.clone());
        if anubis_cmp("==", g.clone(), AnubisValue::Int(0)).as_bool() {
            println!("{}", anubis_mk_str("0".to_string()).display_string());
            return AnubisValue::Int(0);
        }
        let mut reduced_text = anubis_add(anubis_mk_str("".to_string()), anb_positive_abs(anubis_div(a.clone(), g.clone())));
        let mut other_text = anubis_add(anubis_mk_str("".to_string()), anb_positive_abs(b.clone()));
        println!("{}", anb_big_to_text(anb_big_mul(anb_big_from_text(reduced_text.clone()), anb_big_from_text(other_text.clone()))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("prime".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        let _ = anb_print_prime(anb_arg_int(argv.clone(), AnubisValue::Int(1)));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("dot".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(7));
        let _ = anb_print_number(anb_dot3(anb_vec3(argv.clone(), AnubisValue::Int(1)), anb_vec3(argv.clone(), AnubisValue::Int(4))));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("cross".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(7));
        println!("{}", anb_vec_text(anb_cross3(anb_vec3(argv.clone(), AnubisValue::Int(1)), anb_vec3(argv.clone(), AnubisValue::Int(4)))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("norm3".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(4));
        let _ = anb_print_number(anb_norm_vec3(anb_vec3(argv.clone(), AnubisValue::Int(1))));
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("describe".to_string())).as_bool() {
        let _ = anb_describe(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("linreg".to_string())).as_bool() {
        let _ = anb_print_regression(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("convert".to_string())).as_bool() {
        let _ = anb_print_conversion(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("ohm".to_string())).as_bool() {
        let _ = anb_print_ohm(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("parallel-r".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
        let mut r1 = anb_arg_float(argv.clone(), AnubisValue::Int(1));
        let mut r2 = anb_arg_float(argv.clone(), AnubisValue::Int(2));
        if AnubisValue::Bool((anubis_cmp("<", r1.clone(), AnubisValue::Float(0f64))).as_bool() || (anubis_cmp("<", r2.clone(), AnubisValue::Float(0f64))).as_bool()).as_bool() {
            let _ = anubis_panic(anubis_mk_str("parallel-r models ideal passive resistors: resistance must be >= 0 ohm (a negative value implies an active element, outside this model); fail closed".to_string()));
        }
        if AnubisValue::Bool((anubis_cmp("==", r1.clone(), AnubisValue::Float(0f64))).as_bool() || (anubis_cmp("==", r2.clone(), AnubisValue::Float(0f64))).as_bool()).as_bool() {
            println!("{}", anubis_mk_str("0 ohm".to_string()).display_string());
            return AnubisValue::Int(0);
        }
        println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anb_number_text(anubis_div(AnubisValue::Float(1f64), anubis_add(anubis_div(AnubisValue::Float(1f64), r1.clone()), anubis_div(AnubisValue::Float(1f64), r2.clone()))))), anubis_mk_str(" ohm".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("kinetic".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
        println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anb_number_text(anubis_mul(anubis_mul(AnubisValue::Float(0.5f64), anb_arg_float(argv.clone(), AnubisValue::Int(1))), anubis_pow(anb_arg_float(argv.clone(), AnubisValue::Int(2)), AnubisValue::Float(2f64))))), anubis_mk_str(" J".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("photon".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        let mut wavelength = anubis_mul(anb_arg_float(argv.clone(), AnubisValue::Int(1)), AnubisValue::Float(0.000000001f64));
        let mut frequency = anubis_div(AnubisValue::Float(299792458f64), wavelength.clone());
        let mut energy = anubis_mul(AnubisValue::Float(0.000000000000000000000000000000000662607015f64), frequency.clone());
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("energy=".to_string())), energy.clone()), anubis_mk_str(" J frequency=".to_string())), anb_number_text(anb_rounded(frequency.clone(), AnubisValue::Float(0f64)))), anubis_mk_str(" Hz".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("ideal-gas".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(4));
        println!("{}", anubis_add(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("pressure=".to_string())), anb_number_text(anb_rounded(anubis_div(anubis_mul(anubis_mul(anb_arg_float(argv.clone(), AnubisValue::Int(1)), AnubisValue::Float(8.31446261815324f64)), anb_arg_float(argv.clone(), AnubisValue::Int(2))), anb_arg_float(argv.clone(), AnubisValue::Int(3))), AnubisValue::Float(9f64)))), anubis_mk_str(" Pa".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("molarity".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(3));
        println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anb_number_text(anubis_div(anb_arg_float(argv.clone(), AnubisValue::Int(1)), anb_arg_float(argv.clone(), AnubisValue::Int(2))))), anubis_mk_str(" mol/L".to_string())).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("orbit".to_string())).as_bool() {
        let _ = anb_orbit(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("projectile".to_string())).as_bool() {
        let _ = anb_projectile(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("constants".to_string())).as_bool() {
        println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("pi=".to_string())), anubis_pi()).display_string());
        println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("e=".to_string())), anubis_e()).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("parse-dump".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("ast=".to_string())), anb_ast_sexp(anb_parse_ast(argv.index_get(AnubisValue::Int(1))))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("range-bound-cert".to_string())).as_bool() {
        let _ = anb_run_range_bound_cert(argv.clone());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("lower-dump".to_string())).as_bool() {
        let _ = anb_require_arity(argv.clone(), AnubisValue::Int(2));
        println!("{}", anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("lowered=".to_string())), anb_ast_sexp(anb_simplify_bound(anb_parse_ast(argv.index_get(AnubisValue::Int(1)))))).display_string());
        return AnubisValue::Int(0);
    }
    if anubis_cmp("==", op.clone(), anubis_mk_str("maturity".to_string())).as_bool() {
        println!("{}", anubis_mk_str("JACKAL COMMAND MATURITY — epistemic classes, oracles, residuals".to_string()).display_string());
        println!("{}", anubis_mk_str("class=exact       commands=rat,big-add,big-mul,big-pow,big-fact,big-ncr,gcd,lcm,ncr,fact,prime,hex,bin,band,bor,bxor,shl,shr,xgcd,mod-pow,mod-inv,crt,divides,prime-cert,canon,poly-canon,poly-eq,poly-gcd,ratfunc-canon,roots-isolate,alg-sign,alg-cmp  oracle=python-int+fraction  evidence=300-rational-trees+99-bigint-cases(2026-08-13)  residual=none-observed-within-grammar-and-budgets".to_string()).display_string());
        println!("{}", anubis_mk_str("class=bounded     commands=integrate-bound,range-bound  guarantee=certified-enclosure-under-stated-f64-model  residual=implementation-tested-not-mechanized;libm<=2ulp-assumed".to_string()).display_string());
        println!("{}", anubis_mk_str("class=proof-carrying commands=range-bound-cert  guarantee=emits-a-checker-verifiable-certificate; jackal_cert_check (Lean-proved cert_check_sound) accepting it mechanically implies a Runs derivation, hence a true enclosure under ModelTCB  fragment=exact-Q ops+sin/cos+named-consts (transcendentals fail closed)  residual=emitter-faithfulness-tested;codec+Lean-runtime in TCB".to_string()).display_string());
        println!("{}", anubis_mk_str("class=checked     commands=diff  oracle=sympy+richardson-self-check  evidence=79-released-derivatives-max-rel-dev-1.221e-15(2026-08-13)  residual=sampled-agreement-not-proof-of-identity".to_string()).display_string());
        println!("{}", anubis_mk_str("class=estimated   commands=integrate,integrate-adaptive,derivative,solve,integrate-x2,derivative-x3  evidence=integrate:120-oscillatory-median-calibration-ratio-0.99981;solve:150-constructed-roots-max-err-1.2e-16;derivative+legacy:suite-level-only(2026-08-13)  residual=estimate-not-bound;fixed-grids-can-share-blind-spots".to_string()).display_string());
        println!("{}", anubis_mk_str("class=approximate commands=eval,worksheet,add,sub,mul,div,pow,sqrt,cbrt,sin,cos,tan,sin-deg,hypot,ln,log10,exp,quadratic,lerp,percent-error,dot,cross,norm3,stats,describe,linreg,matrix2,solve2  model=ieee-f64  evidence=eval-grammar:500-differential-cases;other-commands:suite-level-only(2026-08-13)  residual=per-command-depth-uneven".to_string()).display_string());
        println!("{}", anubis_mk_str("class=model-based commands=claim-card,projectile,orbit,relativity,ph,dilute,blackbody,photon,ideal-gas,molarity,kinetic,kinetic-sensitivity,ohm,parallel-r,uncertain-ohm,measure-mul,convert,decibel-power  evidence=claim-card:50-deterministic-cards+50-external-sha256;other-model-commands:suite-level-only(2026-08-13)  residual=hash-binds-bytes-not-physical-assumptions".to_string()).display_string());
        println!("{}", anubis_mk_str("class=refused     behavior=fail-closed-nonzero-exit-with-named-reason  residual=surfaced-via-runtime-panic-channel-not-a-crash".to_string()).display_string());
        println!("{}", anubis_mk_str("non-claim=universal-correctness; finite campaigns cannot establish it".to_string()).display_string());
        return AnubisValue::Int(0);
    }
    anubis_panic(anubis_add(anubis_add(anubis_mk_str("".to_string()), anubis_mk_str("unknown operation: ".to_string())), op.clone()))
}


fn main() {
    let child = std::thread::Builder::new()
        .stack_size(1024 * 1024 * 1024)
        .spawn(|| { let _ = anb_main(); })
        .expect("anubis: failed to spawn main thread");
    if child.join().is_err() { std::process::exit(101); }
}
