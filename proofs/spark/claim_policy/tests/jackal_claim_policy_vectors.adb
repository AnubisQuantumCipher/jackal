with Ada.Text_IO;
with Jackal_Claim_Policy;

procedure Jackal_Claim_Policy_Vectors is
   package Policy renames Jackal_Claim_Policy;

   function Flag (Mask, Position : Natural) return Boolean is
     ((Mask / (2 ** Position)) mod 2 = 1);

   function Artifact (Mask : Natural) return Policy.Artifact_Flags is
     (Content_Addressed    => Flag (Mask, 0),
      Reproducible_Built   => Flag (Mask, 1),
      Authenticated        => Flag (Mask, 2),
      Transparency_Logged  => Flag (Mask, 3));

   function Artifact_Mask (Item : Policy.Artifact_Flags) return Natural is
     ((if Item.Content_Addressed then 1 else 0)
      + (if Item.Reproducible_Built then 2 else 0)
      + (if Item.Authenticated then 4 else 0)
      + (if Item.Transparency_Logged then 8 else 0));

begin
   --  Exhaustive bridge vectors for JCK-CLAIM-001, JCK-CLAIM-002, and
   --  JCK-CLAIM-003.
   for Left in Policy.Mathematical_Class loop
      for Right in Policy.Mathematical_Class loop
         Ada.Text_IO.Put_Line
           ("MATH|" & Policy.Mathematical_Class'Image (Left)
            & "|" & Policy.Mathematical_Class'Image (Right)
            & "|" & Policy.Mathematical_Class'Image
              (Policy.Meet_Mathematical (Left, Right)));
      end loop;
   end loop;

   for Left in Policy.Provenance_Class loop
      for Right in Policy.Provenance_Class loop
         Ada.Text_IO.Put_Line
           ("PROVENANCE|" & Policy.Provenance_Class'Image (Left)
            & "|" & Policy.Provenance_Class'Image (Right)
            & "|" & Policy.Provenance_Class'Image
              (Policy.Meet_Provenance (Left, Right)));
      end loop;
   end loop;

   for Left in Policy.Model_Class loop
      for Right in Policy.Model_Class loop
         Ada.Text_IO.Put_Line
           ("MODEL|" & Policy.Model_Class'Image (Left)
            & "|" & Policy.Model_Class'Image (Right)
            & "|" & Policy.Model_Class'Image
              (Policy.Meet_Model (Left, Right)));
      end loop;
   end loop;

   for Left in Policy.Implementation_Class loop
      for Right in Policy.Implementation_Class loop
         Ada.Text_IO.Put_Line
           ("IMPLEMENTATION|" & Policy.Implementation_Class'Image (Left)
            & "|" & Policy.Implementation_Class'Image (Right)
            & "|" & Policy.Implementation_Class'Image
              (Policy.Meet_Implementation (Left, Right)));
      end loop;
   end loop;

   for Behavior in Policy.Rule_Behavior loop
      for Math in Policy.Mathematical_Class loop
         for Implementation in Policy.Implementation_Class loop
            declare
               Result : constant Policy.Rule_Axes :=
                 Policy.Apply_Rule_Caps
                   (Behavior,
                    (Mathematical => Math, Implementation => Implementation));
            begin
               Ada.Text_IO.Put_Line
                 ("RULE|" & Policy.Rule_Behavior'Image (Behavior)
                  & "|" & Policy.Mathematical_Class'Image (Math)
                  & "|" & Policy.Implementation_Class'Image (Implementation)
                  & "|" & Policy.Mathematical_Class'Image
                    (Result.Mathematical)
                  & "|" & Policy.Implementation_Class'Image
                    (Result.Implementation));
            end;
         end loop;
      end loop;
   end loop;

   for Left_Mask in 0 .. 15 loop
      for Right_Mask in 0 .. 15 loop
         Ada.Text_IO.Put_Line
           ("ARTIFACT|" & Natural'Image (Left_Mask)
            & "|" & Natural'Image (Right_Mask)
            & "|" & Natural'Image
              (Artifact_Mask
                 (Policy.Meet_Artifact
                    (Artifact (Left_Mask), Artifact (Right_Mask)))));
      end loop;
   end loop;
end Jackal_Claim_Policy_Vectors;
