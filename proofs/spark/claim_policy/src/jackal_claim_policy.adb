package body Jackal_Claim_Policy
  with SPARK_Mode
is
   function Meet_Mathematical
     (Left, Right : Mathematical_Class) return Mathematical_Class is
   begin
      --  JCK-CLAIM-001
      return Required_Mathematical_Meet (Left, Right);
   end Meet_Mathematical;

   function Meet_Provenance
     (Left, Right : Provenance_Class) return Provenance_Class is
     (if Left <= Right then Left else Right);

   function Meet_Model (Left, Right : Model_Class) return Model_Class is
     (Required_Model_Meet (Left, Right));

   function Meet_Implementation
     (Left, Right : Implementation_Class) return Implementation_Class is
     (if Left <= Right then Left else Right);

   function Meet_Artifact
     (Left, Right : Artifact_Flags) return Artifact_Flags is
     --  JCK-CLAIM-003
     (Content_Addressed    =>
        Left.Content_Addressed and Right.Content_Addressed,
      Reproducible_Built   =>
        Left.Reproducible_Built and Right.Reproducible_Built,
      Authenticated        => Left.Authenticated and Right.Authenticated,
      Transparency_Logged  =>
        Left.Transparency_Logged and Right.Transparency_Logged);

   function Apply_Rule_Caps
     (Behavior : Rule_Behavior;
      Input    : Rule_Axes) return Rule_Axes is
     --  JCK-CLAIM-002
     (Mathematical  =>
        Required_Capped_Mathematical (Behavior, Input.Mathematical),
      Implementation =>
        Required_Capped_Implementation (Behavior, Input.Implementation));

   procedure Prove_Mathematical_Meet_Laws
     (Left, Middle, Right : Mathematical_Class)
   is
   begin
      null;
   end Prove_Mathematical_Meet_Laws;

end Jackal_Claim_Policy;
