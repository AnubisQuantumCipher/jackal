package Jackal_Claim_Policy
  with SPARK_Mode
is
   type Mathematical_Class is
     (Refused,
      Indeterminate,
      Estimated,
      Model_Based,
      Checked,
      Bounded,
      Formal_Bounded,
      Exact);

   type Mathematical_Strength is
     (Refusal_Strength,
      Indeterminate_Strength,
      Estimate_Strength,
      Check_Strength,
      Bound_Strength,
      Formal_Bound_Strength,
      Exact_Strength);

   function Strength_Of
     (Item : Mathematical_Class) return Mathematical_Strength is
     (case Item is
         when Refused        => Refusal_Strength,
         when Indeterminate  => Indeterminate_Strength,
         when Estimated
            | Model_Based    => Estimate_Strength,
         when Checked        => Check_Strength,
         when Bounded        => Bound_Strength,
         when Formal_Bounded => Formal_Bound_Strength,
         when Exact          => Exact_Strength);

   function Required_Mathematical_Meet
     (Left, Right : Mathematical_Class) return Mathematical_Class is
     (if Strength_Of (Left) < Strength_Of (Right) then Left
      elsif Strength_Of (Right) < Strength_Of (Left) then Right
      elsif Mathematical_Class'Pos (Left) <= Mathematical_Class'Pos (Right)
      then Left
      else Right);

   --  JCK-CLAIM-001: canonical weakest-class meet, including the shared-rank
   --  Estimated/Model_Based tie break fixed by registry order.
   function Meet_Mathematical
     (Left, Right : Mathematical_Class) return Mathematical_Class
     with
       Post =>
         Meet_Mathematical'Result =
           Required_Mathematical_Meet (Left, Right)
         and then Strength_Of (Meet_Mathematical'Result) <= Strength_Of (Left)
         and then Strength_Of (Meet_Mathematical'Result) <= Strength_Of (Right);

   type Provenance_Class is
     (Unknown,
      Supplied,
      Integrity_Bound,
      Observed,
      Authenticated_Source,
      Measured);

   function Meet_Provenance
     (Left, Right : Provenance_Class) return Provenance_Class
     with
       Post =>
         Meet_Provenance'Result =
           (if Left <= Right then Left else Right);

   type Model_Class is
     (Model_Unknown,
      Assumed,
      Calibrated,
      Empirically_Validated,
      Not_Applicable);

   function Required_Model_Meet
     (Left, Right : Model_Class) return Model_Class is
     (if Left = Not_Applicable then Right
      elsif Right = Not_Applicable then Left
      elsif Left <= Right then Left
      else Right);

   function Meet_Model (Left, Right : Model_Class) return Model_Class
     with
       Post =>
         Meet_Model'Result = Required_Model_Meet (Left, Right);

   type Implementation_Class is
     (Impl_Unknown,
      Directly_Trusted,
      Campaign_Tested,
      Independently_Recomputed,
      Checker_Derived,
      Source_Native_Refined);

   function Meet_Implementation
     (Left, Right : Implementation_Class) return Implementation_Class
     with
       Post =>
         Meet_Implementation'Result =
           (if Left <= Right then Left else Right);

   type Artifact_Flags is record
      Content_Addressed   : Boolean;
      Reproducible_Built  : Boolean;
      Authenticated       : Boolean;
      Transparency_Logged : Boolean;
   end record;

   --  JCK-CLAIM-003: compositional artifact evidence survives only when both
   --  parents carry the same flag.
   function Meet_Artifact
     (Left, Right : Artifact_Flags) return Artifact_Flags
     with
       Post =>
         Meet_Artifact'Result.Content_Addressed =
           (Left.Content_Addressed and Right.Content_Addressed)
         and then Meet_Artifact'Result.Reproducible_Built =
           (Left.Reproducible_Built and Right.Reproducible_Built)
         and then Meet_Artifact'Result.Authenticated =
           (Left.Authenticated and Right.Authenticated)
         and then Meet_Artifact'Result.Transparency_Logged =
           (Left.Transparency_Logged and Right.Transparency_Logged);

   type Rule_Behavior is
     (Preserve_Axes, Interval_Arithmetic, Derived_Default);

   type Rule_Axes is record
      Mathematical  : Mathematical_Class;
      Implementation : Implementation_Class;
   end record;

   function Required_Capped_Mathematical
     (Behavior : Rule_Behavior;
      Value    : Mathematical_Class) return Mathematical_Class is
     (if Behavior = Interval_Arithmetic
        and then Strength_Of (Bounded) < Strength_Of (Value)
      then Bounded
      else Value);

   function Required_Capped_Implementation
     (Behavior : Rule_Behavior;
      Value    : Implementation_Class) return Implementation_Class is
     (if Behavior /= Preserve_Axes
        and then Independently_Recomputed < Value
      then Independently_Recomputed
      else Value);

   --  JCK-CLAIM-002: rule application preserves or lowers both axes exactly
   --  according to the closed rule category; it can never strengthen them.
   function Apply_Rule_Caps
     (Behavior : Rule_Behavior;
      Input    : Rule_Axes) return Rule_Axes
     with
       Post =>
         Apply_Rule_Caps'Result.Mathematical =
           Required_Capped_Mathematical (Behavior, Input.Mathematical)
         and then Apply_Rule_Caps'Result.Implementation =
           Required_Capped_Implementation (Behavior, Input.Implementation)
         and then Strength_Of (Apply_Rule_Caps'Result.Mathematical) <=
           Strength_Of (Input.Mathematical)
         and then Apply_Rule_Caps'Result.Implementation <=
           Input.Implementation;

   procedure Prove_Mathematical_Meet_Laws
     (Left, Middle, Right : Mathematical_Class)
     with
       Ghost,
       Post =>
         Meet_Mathematical (Left => Left, Right => Right) =
           Meet_Mathematical (Left => Right, Right => Left)
         and then Meet_Mathematical (Left => Left, Right => Left) = Left
         and then Meet_Mathematical
           (Left  => Meet_Mathematical (Left => Left, Right => Middle),
            Right => Right) =
             Meet_Mathematical
               (Left  => Left,
                Right => Meet_Mathematical
                  (Left => Middle, Right => Right));

end Jackal_Claim_Policy;
