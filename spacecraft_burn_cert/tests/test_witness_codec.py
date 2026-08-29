from __future__ import annotations

from dataclasses import replace
import unittest

from spacecraft_burn_cert import witness_codec as codec


def interval(lo: int, hi: int) -> codec.Interval:
    return codec.Interval(lo, hi)


def box(offset: int) -> codec.Box:
    return codec.Box(
        tuple(interval(offset + 2 * index, offset + 2 * index + 1) for index in range(5))
    )


def minimal_witness() -> codec.BurnWitness:
    step = codec.StepWitness(branch=0, step=0, tube=box(20))
    branch = codec.BranchWitness(
        branch=0,
        initial=box(0),
        thrust=interval(10, 11),
        steps=(step,),
    )
    return codec.BurnWitness(
        scale_bits=80,
        step_num=1,
        step_den=32,
        partition_counts=(1, 1, 1, 1, 1, 1),
        steps_per_branch=1,
        first_cutoff_step=0,
        branches=(branch,),
    )


class WitnessCodecTests(unittest.TestCase):
    def test_canonical_round_trip_is_byte_exact(self):
        encoded = codec.encode_witness(minimal_witness())
        self.assertEqual(codec.encode_witness(codec.decode_witness(encoded)), encoded)
        self.assertTrue(encoded.startswith(b"jackal-spacecraft-burn-cert v2\n"))
        self.assertTrue(encoded.endswith(b"end 1 1 1\n"))

    def test_duplicate_terminal_record_refuses(self):
        encoded = codec.encode_witness(minimal_witness())
        terminal = encoded.splitlines(keepends=True)[-1]
        with self.assertRaisesRegex(codec.WitnessRefusal, "trailing-record"):
            codec.decode_witness(encoded + terminal)

    def test_noncanonical_integer_refuses(self):
        encoded = codec.encode_witness(minimal_witness())
        mutant = encoded.replace(b"config 80 ", b"config +80 ", 1)
        with self.assertRaisesRegex(codec.WitnessRefusal, "noncanonical-integer"):
            codec.decode_witness(mutant)

    def test_integer_tokens_and_record_envelope_are_explicitly_bounded(self):
        encoded = codec.encode_witness(minimal_witness())
        oversized_integer = b"9" * (codec.MAX_INTEGER_DIGITS + 1)
        mutant = encoded.replace(b"config 80 ", b"config " + oversized_integer + b" ", 1)
        with self.assertRaisesRegex(codec.WitnessRefusal, "integer-digit-limit"):
            codec.decode_witness(mutant)

        long_record = (
            codec.MAGIC
            + b"x" * (codec.MAX_WITNESS_RECORD_CHARS + 1)
            + b"\nend 0 0 0\n"
        )
        with self.assertRaisesRegex(codec.WitnessRefusal, "record-length-limit"):
            codec.decode_witness(long_record)

        too_many_records = codec.MAGIC + b"\n" * codec.MAX_WITNESS_RECORDS
        with self.assertRaisesRegex(codec.WitnessRefusal, "record-count-limit"):
            codec.decode_witness(too_many_records)

    def test_noncanonical_line_endings_and_step_fraction_refuse(self):
        encoded = codec.encode_witness(minimal_witness())
        with self.assertRaisesRegex(codec.WitnessRefusal, "noncanonical-line-ending"):
            codec.decode_witness(encoded.replace(b"\n", b"\r\n"))
        with self.assertRaisesRegex(codec.WitnessRefusal, "noncanonical-control-character"):
            codec.decode_witness(encoded.replace(b"tube", b"tu\x0cbe", 1))
        mutant = encoded.replace(b"config 80 1 32 ", b"config 80 2 64 ", 1)
        with self.assertRaisesRegex(codec.WitnessRefusal, "step-rational-not-reduced"):
            codec.decode_witness(mutant)

    def test_truncated_unknown_and_oversized_inputs_refuse(self):
        encoded = codec.encode_witness(minimal_witness())
        with self.assertRaisesRegex(codec.WitnessRefusal, "missing-terminal"):
            codec.decode_witness(b"\n".join(encoded.splitlines()[:-1]) + b"\n")
        with self.assertRaisesRegex(codec.WitnessRefusal, "unexpected-record"):
            codec.decode_witness(encoded.replace(b"tube ", b"orbit ", 1))
        with self.assertRaisesRegex(codec.WitnessRefusal, "witness-too-large"):
            codec.decode_witness(b"x" * (codec.MAX_WITNESS_BYTES + 1))

    def test_branch_and_step_order_are_exact(self):
        encoded = codec.encode_witness(minimal_witness())
        with self.assertRaisesRegex(codec.WitnessRefusal, "step-order"):
            codec.decode_witness(encoded.replace(b"tube 0 0 ", b"tube 0 1 ", 1))
        with self.assertRaisesRegex(codec.WitnessRefusal, "branch-order"):
            codec.decode_witness(encoded.replace(b"branch 0 ", b"branch 1 ", 1))

    def test_box_dimension_and_interval_order_refuse(self):
        with self.assertRaisesRegex(codec.WitnessRefusal, "box-dimension"):
            codec.Box((interval(0, 1),))
        with self.assertRaisesRegex(codec.WitnessRefusal, "interval-order"):
            interval(2, 1)

    def test_encode_refuses_malformed_direct_dataclass_graphs(self):
        class WeirdInteger(int):
            def __str__(self):
                return "evil"

        valid = minimal_witness()
        branch = valid.branches[0]
        step = branch.steps[0]
        malformed = (
            None,
            replace(valid, branches=None),
            replace(valid, branches=list(valid.branches)),
            replace(valid, branches=(replace(branch, branch=False),)),
            replace(valid, scale_bits=WeirdInteger(80)),
            replace(valid, branches=(replace(branch, initial=None),)),
            replace(valid, branches=(replace(branch, thrust=None),)),
            replace(valid, branches=(replace(branch, steps=None),)),
            replace(valid, branches=(replace(branch, steps=list(branch.steps)),)),
            replace(
                valid,
                branches=(replace(branch, steps=(replace(step, branch=False),)),),
            ),
            replace(
                valid,
                branches=(replace(branch, steps=(replace(step, step=False),)),),
            ),
            replace(
                valid,
                branches=(replace(branch, steps=(replace(step, tube=None),)),),
            ),
        )
        for index, candidate in enumerate(malformed):
            with self.subTest(index=index), self.assertRaises(codec.WitnessRefusal):
                codec.encode_witness(candidate)


if __name__ == "__main__":
    unittest.main()
