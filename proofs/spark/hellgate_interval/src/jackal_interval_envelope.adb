package body Jackal_Interval_Envelope
  with SPARK_Mode
is

   function Width (Item : Closed_Interval) return Magnitude is
     (Item.Upper - Item.Lower);

   function Midpoint (Item : Closed_Interval) return Magnitude is
     (Item.Lower + Width (Item) / 2);

   function Radius_Ceiling (Item : Closed_Interval) return Magnitude is
     (Width (Item) - Width (Item) / 2);

   function Strictly_Meets_Target
     (Item         : Closed_Interval;
      Target_Width : Magnitude) return Boolean is
     (Width (Item) < Target_Width);

   function Evaluate_Untrusted_Envelope
     (Item         : Closed_Interval;
      Target_Width : Magnitude) return Envelope_Decision
   is
      Empty : constant Envelope_Decision :=
        (Verdict => Reject_Unordered,
         Width   => 0,
         Center  => 0,
         Radius  => 0);
   begin
      --  JCK-INT-004.  The branch order is part of Required_Verdict and makes
      --  subtraction unreachable until ordering has been established.
      if not Is_Ordered (Item) then
         return Empty;
      elsif Target_Width = 0 then
         return
           (Verdict => Reject_Nonpositive_Target,
            Width   => 0,
            Center  => 0,
            Radius  => 0);
      elsif Width (Item) >= Target_Width then
         return
           (Verdict => Reject_Not_Strictly_Narrower,
            Width   => 0,
            Center  => 0,
            Radius  => 0);
      else
         return
           (Verdict => Admit,
            Width   => Width (Item),
            Center  => Midpoint (Item),
            Radius  => Radius_Ceiling (Item));
      end if;
   end Evaluate_Untrusted_Envelope;

end Jackal_Interval_Envelope;
