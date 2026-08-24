# Finite-duration periapsis burn certification report

## Decisive result

**PROVED SAFE** — `/opt/homebrew/bin/python3 -B spacecraft_burn_cert/verify_receipt.py spacecraft_burn_cert/evidence/baseline_receipt.json --source spacecraft_burn_cert/certify.py` returned `status: ACCEPT`, no refusal reasons, and replayed trace SHA-256
`f5b9684d0762eb6cb83dbfb20316b6cb166ea74b16b8ab151ccb7c70a23ce5fe`.

For every allowed initial state, thrust, mass, and cutoff time, the safety
margin satisfies

\[
M \ge L =
\frac{51450379597827184853505075}
     {1208925819614629174706176}\ {\rm km} > 0.
\]

The exact terminating decimal representation of this dyadic endpoint is

```text
42.55875651181648843759718976895353094338884936131961467253859154880046844482421875 km
```

Consequently,

\[
\inf(r_a-R_E) \ge
\frac{1260376199212456359559681075}
     {1208925819614629174706176}\ {\rm km}
=1042.5587565118164884375971897689535\ldots\ {\rm km}
>1000\ {\rm km}.
\]

`L` is an exactly represented, rigorously certified lower bound.  It is not a
claim that `L` equals the exact mathematical infimum.

The literal energy/angular-momentum/eccentricity formula without the
independent eccentricity-vector intersection also closes the requirement:

```text
M >= 4684830994590880152455811 / 1208925819614629174706176 km
  = 3.87520137181309412623115452782699663874903250881942540218005888164043426513671875 km
```

The larger decisive bound uses the intersection of two exactly equivalent
eccentricity enclosures, described below.

## Reachable cutoff enclosure

The program partitions `(x0,y0,vx0,vy0,m0,T)` into
`(4,1,1,2,2,2)`, giving 32 boxes.  It advances every box with exact
dyadic interval arithmetic at `h=1/32 s`.  All possible cutoff times are
covered by the 96 validated tubes spanning `[118.5,121.5] s` in each branch.

The resulting hull of all cutoff states is:

| quantity | rigorous interval enclosure |
|---|---:|
| `x` km | `[6611.4907036697814266927517417813, 6616.9029477499189910525610256093]` |
| `y` km | `[924.4144502640997258952576144704, 948.1763697997565598928579455480]` |
| `vx` km/s | `[-1.0970146600720285705440631958, -1.0686367406732386058403824468]` |
| `vy` km/s | `[7.8532410298989287962813529363, 7.8569422550132530778072801238]` |
| `m` kg | `[1143.2150715897432411226603833843, 1148.0116300191989902543477910764]` |

Mass loss is integrated as `dm/dt=-T/(Isp*g0)`.  The separate exact analytic
mass range
`[448476801/392266, 64327657/56038] kg` is contained in this tube hull.

For each step the producer constructs a box `B` and checks, with exact integer
endpoint arithmetic,

```text
X_n union (X_n + [0,h] f(B))  subset  interior(B).
```

The exact solution tube is therefore enclosed in `B`, and
`X_n + h f(B)` encloses its endpoint.  The vector field is continuously
differentiable throughout every accepted tube because the independently
replayed global lower bounds are strictly positive:

| denominator domain | exact global lower bound | decimal rendering |
|---|---:|---:|
| `r^2` | `53912371654328477687089108767263 / 1208925819614629174706176` | `44595268.6092139161650312328056` |
| `v^2` | `72158111333449500373422077 / 1208925819614629174706176` | `59.6877907334723263238313231945` |
| `m` | `1382062217417427315736792485 / 1208925819614629174706176` | `1143.2150715897432411226603833843` |

The baseline run checked 124,416 tubes and 3,072 cutoff post-processing cells;
the maximum Picard-inclusion iteration count was one.  These counts reconcile
exactly as `32*3888` and `32*96`.

## Independent orbital post-processing

The independent verifier imports no code from the producer and recomputes each
requested step from the cutoff tubes:

| step | rigorous global interval |
|---|---:|
| `r=sqrt(x^2+y^2)` km | `[6678.9917996786786720684596217109, 6681.3111134383560783084277281268]` |
| `v^2=vx^2+vy^2` km^2/s^2 | `[62.8161662104251262482656170944, 62.9341552414273784786901807189]` |
| `epsilon=v^2/2-mu/r` km^2/s^2 | `[-28.2715283775294197832427572087, -28.1920654455674677320247962530]` |
| `a=-mu/(2 epsilon)` km | `[7049.5028863882159302306459600650, 7069.3728093389916236783423816825]` |
| `h=x vy-y vx` km^2/s | `[52935.2205315267811329389508251635, 53003.0663261809056433376363383851]` |
| `e^2=1+2 epsilon h^2/mu^2` | `[0.0022247889483622943248171804, 0.0035866804316925588013990555]` |
| `e` from the requested formula | `[0.0471676684643442422169524154, 0.0598889007387225199969286812]` |
| `e` after equivalent-vector intersection | `[0.0526550844940187482602489540, 0.0550434388798342039629808440]` |
| `r_a=a(1+e)` km | `[7420.6950565118164884375971899437, 7458.4953994886042283211137990468]` |
| `r_a-R_E` km | `[1042.5587565118164884375971897690, 1080.3590994886042283211137996993]` |
| `M=(r_a-R_E)-1000` km | `[42.5587565118164884375971897690, 80.3590994886042283211137996993]` |

The second route uses

```text
e_x = ((v^2-mu/r)x-(r.v)vx)/mu
e_y = ((v^2-mu/r)y-(r.v)vy)/mu
e = sqrt(e_x^2+e_y^2).
```

The verifier's exact multivariate polynomial normalizer checked all four
recorded identities:

- `(vx^2+vy^2)(x^2+y^2)-(x vx+y vy)^2=(x vy-y vx)^2`;
- reduction of the eccentricity-vector numerator to
  `mu^2+2 epsilon h^2`;
- the `v^2/2-mu/r` energy substitution;
- expansion of `a(1+e)`, with the plus sign.

The two eccentricity intervals are mathematically equal enclosures of the same
quantity, so their intersection is also an enclosure.  The direct requested
formula remains separately reported and independently positive.

## JACKAL evidence and the assurance boundary

The installed JACKAL v1.7.3 runtime has no admitted nonlinear ODE certificate
lane.  It was used only where its formal fragment applies.  For the
independently replayed eccentricity-vector radicand

```text
[3351816859579158189993/1208925819614629174706176,
 3662779467674981330153/1208925819614629174706176]
```

`jackal_sqrt_rat_bound` returned `status=formal-bounded`; the pinned checker
returned `ACCEPT`.  A separate `jackal_verify_receipt` replay returned
`status=verified`, `verdict=ACCEPT`, receipt digest
`fd2f237349fc31592a8204c5c601e066f36d011b92217fa5559c6109f106b33f`,
and the formal enclosure

```text
[0.05265508449401874826024916416,
 0.0550434388798342039629804474500000000001].
```

That formal receipt certifies only `sqrt(x)` over that supplied rational
interval, under the assumptions and non-claims preserved in
`evidence/jackal_sqrt_receipt.json`.  It does not certify the truth of the
radicand enclosure, the ODE propagation, the multivariate orbital composition,
or the overall mission result.

The overall verdict is therefore **rigorously interval-bounded, not
formal-bounded**.  Calling it “formally proved” would cross the assurance
boundary.

## Instrument validation and diagnostics

`/opt/homebrew/bin/python3 -B spacecraft_burn_cert/validate.py --output spacecraft_burn_cert/evidence/instrument_validation.json`
returned `INSTRUMENT_VALIDATION_PASS`.

| check | result | evidence class |
|---|---|---|
| exact dyadic arithmetic corpus | 144/144 containments passed | exact implementation check |
| analytic mass solution | contained in certified tube hull | exact cross-check |
| step `1/16 s` | `M >= 42.1568120515684803341452720024 km` | rigorous interval-bounded |
| step `1/32 s` | `M >= 42.5587565118164884375971897690 km` | rigorous interval-bounded, decisive |
| step `1/64 s` | `M >= 42.7598567664322865457310281679 km` | rigorous interval-bounded cross-check |
| nominal RK4 | `M ~= 61.36001821038917 km` | numerically estimated only |
| all 128 input corners | minimum sampled `43.68554532892449 km` | deterministic samples only |

Neither the nominal integration nor the 128 corner samples contribute to the
universal verdict.

## Required A -> B -> A mutations

For every mutation, source state `A` had SHA-256
`9f342c68e0dbed7de9c27d56a585711f48fe40e3f7727f0ce0248f3ac8823fa8`.
The mutation changed it to the listed `B` hash; behavior tests failed, the
independent verifier refused with the named reason, and exact restoration
returned to the same `A` hash before the next mutation.

| mutation | B SHA-256 | observed mutant behavior | verifier reason |
|---|---|---|---|
| meters used as kilometers | `796b5e382b88da3f95bf1a07b38a81a1231ae09c326d86a0c7612350a2223d79` | producer failed closed | `unit-scale-mismatch` |
| frozen mass | `b3b6c50da9b6824e159b374a463ee82b94c362f608bd5089bd158e89c3706cc3` | false lower margin `24.8015418822929005... km` | `mass-integration-mismatch` |
| `a(1-e)` | `c6ead5915363319d95f2599c7bf7018538e3e17984fe1bf5748e942afcdafd1c` | false `PROVED UNSAFE`, margin `-703.4868767408176... km` | `apoapsis-plus-mismatch` |
| `v^2` energy | `884ccab3eadd571aff7f9a42d3eb40e88a496bcd0dfe77fadad00fede0dd353e` | producer failed closed on non-elliptic energy | `energy-half-mismatch` |
| interval centers only | `dd31f33b8c2dab171cbde6ae3a070b0219d271dec89020ffa9104598ee72080c` | false narrow lower margin `50.5953897126259580... km` | `full-box-coverage-mismatch` |
| upward-rounded margin | `6694801105fc8521ff72fa79932d9ccc2535eb3f5e68cc43296c841451573898` | reported `42.558757 km`, above the exact lower endpoint | `decision-rounding-mismatch` and `reported-lower-bound-mismatch` |

`/opt/homebrew/bin/python3 -B spacecraft_burn_cert/mutation_aba.py --output spacecraft_burn_cert/evidence/mutation_aba.json`
returned `MUTATION_ABA_PASS`.  The baseline independent verifier returned
`ACCEPT` both before and after the campaign, and the final certifier SHA-256 was
the original `A` hash.

## Evidence classification

| material | classification |
|---|---|
| supplied decimal constants interpreted as rationals; dyadic endpoints; hashes; symbolic polynomial reductions | exact |
| JACKAL `sqrt(x)` enclosure only | formal-bounded, then verified by receipt replay |
| nonlinear ODE reachable set and full orbital result | rigorously interval-bounded; independently replayed; not formal |
| step-size study | rigorous interval-bounded cross-check, not a convergence theorem |
| nominal RK4 trajectory | numerically estimated |
| 128 corner trajectories | sampled diagnostic |
| Monte Carlo | not used |

## Artifact identities

| artifact | SHA-256 |
|---|---|
| `certify.py` | `9f342c68e0dbed7de9c27d56a585711f48fe40e3f7727f0ce0248f3ac8823fa8` |
| `verify_receipt.py` | `1ff7a25523de7bb060efbb87db4cb1d0e5332e31a4c06bc491306a1d7195dd58` |
| `validate.py` | `855cb2ffe6a4429eb2796b1693cc43ae7a454a8aa76fcedc31c9fa5f5d5208c6` |
| `mutation_aba.py` | `7d58fc4f078d50bcc888dae9e7ffd602cfb74cd78a3996518eb6ed9fbcdea956` |
| baseline receipt | `3ed9881842e19f97989325235ee1c6f196a3349b3bcfb1fa4ac3bf0be5ca583d` |
| independent verification | `4fa78fa3877f9c36465e27caf06b69260ae411fb099fcab0cf97ba867f810ca9` |
| instrument validation | `919fe12ff5ac62db9c0d2db2e2453c2bc5e3020379f27c876ae219631207abcf` |
| mutation A-B-A evidence | `4fd8440cd256bb54cfa93f6b43e5fb6efdae659a30bf84d97cbbadcd07bb165b` |
| JACKAL square-root evidence | `cd759b1c6969c052f92da2db251e9e89eec3f43c54eda96653263d5bfd26ceb9` |
