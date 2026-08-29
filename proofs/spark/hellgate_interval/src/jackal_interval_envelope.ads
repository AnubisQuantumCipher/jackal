package Jackal_Interval_Envelope
  with SPARK_Mode
is
   Max_Magnitude : constant Long_Long_Integer :=
     8_000_000_000_000_000_000;

   subtype Magnitude is Long_Long_Integer
     range 0 .. Max_Magnitude;

   type Closed_Interval is record
      Lower : Magnitude;
      Upper : Magnitude;
   end record;

   function Is_Ordered (Item : Closed_Interval) return Boolean is
     (Item.Lower <= Item.Upper);

   --  JCK-INT-001: exact width over every ordered fixed-scale interval.
   function Width (Item : Closed_Interval) return Magnitude
     with
       Pre  => Is_Ordered (Item),
       Post => Width'Result = Item.Upper - Item.Lower;

   --  JCK-INT-002: the midpoint/radius pair covers both interval endpoints.
   function Midpoint (Item : Closed_Interval) return Magnitude
     with
       Pre  => Is_Ordered (Item),
       Post =>
         Midpoint'Result =
           Item.Lower + (Item.Upper - Item.Lower) / 2
         and then Midpoint'Result in Item.Lower .. Item.Upper;

   function Radius_Ceiling (Item : Closed_Interval) return Magnitude
     with
       Pre  => Is_Ordered (Item),
       Post =>
         Radius_Ceiling'Result =
           (Item.Upper - Item.Lower)
           - (Item.Upper - Item.Lower) / 2;

   function Contains
     (Item  : Closed_Interval;
      Value : Magnitude) return Boolean is
     (Item.Lower <= Value and then Value <= Item.Upper);

   function Covers
     (Item   : Closed_Interval;
      Center : Magnitude;
      Radius : Magnitude) return Boolean is
     (Is_Ordered (Item)
      and then Contains (Item, Center)
      and then Center - Item.Lower <= Radius
      and then Item.Upper - Center <= Radius);

   --  JCK-INT-003: strict admission is equivalent to the allocated width
   --  predicate for every input satisfying the public precondition.
   function Strictly_Meets_Target
     (Item         : Closed_Interval;
      Target_Width : Magnitude) return Boolean
     with
       Pre  => Is_Ordered (Item) and then Target_Width > 0,
       Post =>
         Strictly_Meets_Target'Result =
           (Item.Upper - Item.Lower < Target_Width);

   function Admits_Untrusted_Envelope
     (Item         : Closed_Interval;
      Target_Width : Magnitude) return Boolean is
     (Is_Ordered (Item)
      and then Target_Width > 0
      and then Item.Upper - Item.Lower < Target_Width);

   type Decision_Verdict is
     (Reject_Unordered,
      Reject_Nonpositive_Target,
      Reject_Not_Strictly_Narrower,
      Admit);

   type Envelope_Decision is record
      Verdict : Decision_Verdict;
      Width   : Magnitude;
      Center  : Magnitude;
      Radius  : Magnitude;
   end record;

   function Required_Verdict
     (Item         : Closed_Interval;
      Target_Width : Magnitude) return Decision_Verdict is
     (if not Is_Ordered (Item) then Reject_Unordered
      elsif Target_Width = 0 then Reject_Nonpositive_Target
      elsif Item.Upper - Item.Lower >= Target_Width then
        Reject_Not_Strictly_Narrower
      else Admit);

   --  JCK-INT-004: total, deterministic evaluation over the complete public
   --  input type.  Rejections zero every derived output; acceptance returns
   --  the exact width and a covering midpoint/radius pair.
   function Evaluate_Untrusted_Envelope
     (Item         : Closed_Interval;
      Target_Width : Magnitude) return Envelope_Decision
     with
       Post =>
         Evaluate_Untrusted_Envelope'Result.Verdict =
           Required_Verdict (Item, Target_Width)
         and then
           ((Evaluate_Untrusted_Envelope'Result.Verdict = Admit) =
              Admits_Untrusted_Envelope (Item, Target_Width))
         and then
           (if Evaluate_Untrusted_Envelope'Result.Verdict = Admit then
                Evaluate_Untrusted_Envelope'Result.Width =
                  Item.Upper - Item.Lower
                and then Evaluate_Untrusted_Envelope'Result.Center =
                  Item.Lower + (Item.Upper - Item.Lower) / 2
                and then Evaluate_Untrusted_Envelope'Result.Radius =
                  (Item.Upper - Item.Lower)
                  - (Item.Upper - Item.Lower) / 2
                and then Covers
                  (Item,
                   Evaluate_Untrusted_Envelope'Result.Center,
                   Evaluate_Untrusted_Envelope'Result.Radius)
            else Evaluate_Untrusted_Envelope'Result.Width = 0
                 and then Evaluate_Untrusted_Envelope'Result.Center = 0
                 and then Evaluate_Untrusted_Envelope'Result.Radius = 0);

end Jackal_Interval_Envelope;
