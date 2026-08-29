with Ada.Text_IO;
with Jackal_Interval_Envelope;

procedure Hellgate_Interval_Demo
  with SPARK_Mode
is
   package Envelope renames Jackal_Interval_Envelope;
   use type Envelope.Decision_Verdict;

   --  The checked energy interval is negative.  This independent fixed-scale
   --  boundary represents its absolute magnitudes, ordered from smaller to
   --  larger, at a scale of 10^18.
   Hellgate_Magnitude : constant Envelope.Closed_Interval :=
     (Lower => 4_615_978_698_574_496_507,
      Upper => 4_615_978_698_574_496_508);

   --  2*10^(-12) at scale 10^18.  JACKAL exact replay:
   --  parsed=2/10^12*10^18; exact=2000000; status=exact (not formal).
   Required_Strict_Width : constant Envelope.Magnitude := 2_000_000;

   Reversed_Magnitude : constant Envelope.Closed_Interval :=
     (Lower => Hellgate_Magnitude.Upper,
      Upper => Hellgate_Magnitude.Lower);
   Boundary_Width : constant Envelope.Closed_Interval :=
     (Lower => 0,
      Upper => Required_Strict_Width);

   Center : constant Envelope.Magnitude :=
     Envelope.Midpoint (Hellgate_Magnitude);
   Radius : constant Envelope.Magnitude :=
     Envelope.Radius_Ceiling (Hellgate_Magnitude);
   Decision : constant Envelope.Envelope_Decision :=
     Envelope.Evaluate_Untrusted_Envelope
       (Hellgate_Magnitude, Required_Strict_Width);
begin
   --  JCK-INT-001, JCK-INT-002, JCK-INT-003, JCK-INT-004.
   pragma Assert (Envelope.Is_Ordered (Hellgate_Magnitude));
   pragma Assert (Envelope.Contains (Hellgate_Magnitude, Center));
   pragma Assert (Center - Hellgate_Magnitude.Lower <= Radius);
   pragma Assert (Hellgate_Magnitude.Upper - Center <= Radius);
   pragma Assert
     (Envelope.Strictly_Meets_Target
        (Hellgate_Magnitude, Required_Strict_Width));
   pragma Assert
     (Envelope.Admits_Untrusted_Envelope
        (Hellgate_Magnitude, Required_Strict_Width));
   pragma Assert
     (not Envelope.Admits_Untrusted_Envelope
        (Reversed_Magnitude, Required_Strict_Width));
   pragma Assert
     (not Envelope.Admits_Untrusted_Envelope
        (Hellgate_Magnitude, 0));
   pragma Assert
     (not Envelope.Admits_Untrusted_Envelope
        (Boundary_Width, Required_Strict_Width));
   pragma Assert (Decision.Verdict = Envelope.Admit);
   pragma Assert (Decision.Center = Center);
   pragma Assert (Decision.Radius = Radius);
   pragma Assert
     (Envelope.Evaluate_Untrusted_Envelope
        (Reversed_Magnitude, Required_Strict_Width).Verdict =
        Envelope.Reject_Unordered);
   pragma Assert
     (Envelope.Evaluate_Untrusted_Envelope
        (Hellgate_Magnitude, 0).Verdict =
        Envelope.Reject_Nonpositive_Target);
   pragma Assert
     (Envelope.Evaluate_Untrusted_Envelope
        (Boundary_Width, Required_Strict_Width).Verdict =
        Envelope.Reject_Not_Strictly_Narrower);

   Ada.Text_IO.Put_Line ("HELLGATE fixed-scale interval envelope: ACCEPT");
end Hellgate_Interval_Demo;
