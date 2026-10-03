#!/usr/bin/env python3
"""Public fixture comparisons for the development sealed-runtime guest.

Original exit/stdout/stderr must match exactly. A refusal cannot count as a
positive control, and Python optimization cannot remove evidence checks.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from sealed_runtime_runner import replay


def request(method, params):
    return (json.dumps({'jsonrpc': '2.0', 'id': 'public-compatibility',
                        'method': method, 'params': params}) + '\n').encode()


def direct(runtime, payload):
    return subprocess.run([sys.executable, '-I', '-S', '-B',
        str(runtime / 'isolated_entry.py'), 'plugin', 'stdio'], input=payload,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3600)


def result(process):
    if process.returncode != 0 or process.stderr:
        raise RuntimeError('original runtime failed: ' + repr(process))
    return json.loads(process.stdout)['result']


def compare(guest, runtime, name, params, expected, method="jackal_verify_receipt"):
    payload = request(method, params)
    original = direct(runtime, payload)
    observed = result(original)
    if observed.get('status') != expected:
        raise RuntimeError('original control did not produce expected status: ' + repr(observed))
    start = time.monotonic()
    private = replay(guest, payload)
    if (original.returncode, original.stdout, original.stderr) != (
            private.returncode, private.stdout, private.stderr):
        raise RuntimeError(json.dumps({'case': name, 'comparison': 'mismatch',
            'original': {'exit': original.returncode, 'stdout': repr(original.stdout), 'stderr': repr(original.stderr)},
            'guest': {'exit': private.returncode, 'stdout': repr(private.stdout), 'stderr': repr(private.stderr)}}))
    print(json.dumps({'case': name, 'status': observed['status'], 'comparison': 'byte-identical',
        'elapsed_seconds': time.monotonic() - start, 'returncode': private.returncode,
        'stdout_sha256': hashlib.sha256(private.stdout).hexdigest(),
        'stderr_sha256': hashlib.sha256(private.stderr).hexdigest()}), flush=True)


def archival_receipt(runtime):
    producer = runtime / 'ln_rat_producer.py'
    certificate = subprocess.check_output([sys.executable, '-I', '-S', '-B',
        str(producer), 'emit', '--expression=ln(x)', '--lower=2', '--upper=3'], timeout=300)
    with tempfile.TemporaryDirectory(prefix='jackal-public-archival-') as directory:
        certificate_path = Path(directory) / 'certificate'
        receipt_path = Path(directory) / 'receipt.json'
        certificate_path.write_bytes(certificate)
        checker = runtime / 'jackal_cert_check_v170'
        accepted = subprocess.run([str(checker), str(certificate_path),
            'range-bound-cert', 'ln(x)', '2', '3'], capture_output=True, timeout=300)
        if accepted.returncode != 0 or not accepted.stdout.startswith(b'ACCEPT'):
            raise RuntimeError('archival certificate positive control failed')
        emitted = subprocess.run([sys.executable, '-I', '-S', '-B', str(runtime / 'isolated_entry.py'),
            'emit-variant-receipt', '--variant', 'ln_rat', '--expression', 'ln(x)',
            '--lower', '2', '--upper', '3', '--cert', str(certificate_path),
            '--producer', str(producer), '--checker', str(checker),
            '--proof-identity', str(runtime / 'evidence/range_proof_identity_v1.json'),
            '--inventory', str(runtime / 'evidence/formal_coverage_inventory_v170.json'),
            '--release-epoch', 'v1.5.0', '--output', str(receipt_path)],
            capture_output=True, timeout=300)
        if emitted.returncode != 0:
            raise RuntimeError("archival receipt construction failed: " + repr(emitted.stderr))
        return json.loads(receipt_path.read_bytes())


def check(guest, runtime, selected):
    if selected in ('all', 'smoke'):
        compare(guest, runtime, 'schema-refusal', {}, 'refused')
    if selected in ('all', 'archival-range'):
        params = {'receipt': archival_receipt(runtime), 'expected_release_epoch': 'v1.5.0',
                  'expected_command': 'range-bound-cert', 'expected_expression': 'ln(x)',
                  'expected_input_lo': '2', 'expected_input_hi': '3'}
        compare(guest, runtime, 'archival-range-accept', params, 'verified')
        negative = copy.deepcopy(params)
        negative['expected_release_epoch'] = 'v1.7.2'
        compare(guest, runtime, 'archival-range-epoch-mismatch', negative, 'refused')
    for case, tool, expression, tolerance, epoch, command in (
        ('integral', 'jackal_integrate_bound_cert', '0', '2', 'v1.7.2', 'integrate-bound-cert'),
        ('gaussian', 'jackal_gaussian_integral', 'exp(-10000000000*(x-0.5000123456789)^2)',
         '1/1000000000000', 'v1.5.0', 'integrate')):
        if selected not in ('all', case):
            continue
        produced = result(direct(runtime, request(tool, {'expression': expression,
            'input_lo': '0', 'input_hi': '1', 'tolerance': tolerance})))
        if produced.get('status') != 'formal-bounded' or not isinstance(produced.get('receipt'), dict):
            raise RuntimeError('positive receipt generation failed: ' + repr(produced))
        params = {'receipt': produced['receipt'], 'expected_release_epoch': epoch,
            'expected_command': command, 'expected_expression': expression,
            'expected_input_lo': '0', 'expected_input_hi': '1', 'expected_tolerance': tolerance}
        compare(guest, runtime, case + '-accept', params, 'verified')
        negative = copy.deepcopy(params)
        negative['expected_expression'] = 'x'
        compare(guest, runtime, case + '-request-mismatch', negative, 'refused')
    if selected in ('all', 'bundle'):
        root = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(root / 'tools'))
        spec = importlib.util.spec_from_file_location('public_bundle_helpers',
            root / 'tests/claim_hostile_test.py')
        helpers = importlib.util.module_from_spec(spec)
        fixture_environment = {
            'JACKAL_BIN': str(runtime / 'jackal-native'),
            'JACKAL_V170_ARCHIVAL_RANGE_CHECKER': str(runtime / 'jackal_cert_check_v170'),
            'JACKAL_V170_ARCHIVAL_RANGE_INVENTORY': str(runtime / 'evidence/formal_coverage_inventory_v170.json')}
        previous = {key: os.environ.get(key) for key in fixture_environment}
        try:
            os.environ.update(fixture_environment)
            spec.loader.exec_module(helpers)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        node = helpers.input_node('x', '1', '2')
        bundle = helpers.bundle_of([node], node['id'])
        params = {'bundle': bundle, 'expected_release_epoch': bundle['release_epoch'],
            'expected_policy_sha256': helpers.sha_hex(helpers.canon(bundle['policy'])),
            'expected_root_proposition': node['proposition'],
            'verification_time_unix': str(helpers.VTIME)}
        compare(guest, runtime, 'bundle-input-accept', params, 'verified', 'jackal_verify_bundle')
        negative = copy.deepcopy(params)
        negative['expected_policy_sha256'] = '0' * 64
        compare(guest, runtime, 'bundle-policy-mismatch', negative, 'refused', 'jackal_verify_bundle')
    if selected in ('all', 'current-range'):
        produced = result(direct(runtime, request('jackal_range_bound', {
            'expression': 'x^2+1', 'input_lo': '1', 'input_hi': '2'})))
        if produced.get('status') != 'formal-bounded' or not isinstance(produced.get('receipt'), dict):
            raise RuntimeError('positive receipt generation failed: ' + repr(produced))
        params = {'receipt': produced['receipt'], 'expected_release_epoch': 'v1.7.2',
                  'expected_command': 'range-bound-cert', 'expected_expression': 'x^2+1',
                  'expected_input_lo': '1', 'expected_input_hi': '2'}
        compare(guest, runtime, 'current-range-accept', params, 'verified')
        negative = copy.deepcopy(params)
        negative['expected_expression'] = 'x'
        compare(guest, runtime, 'current-range-request-mismatch', negative, 'refused')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guest', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--case', choices=('all', 'smoke', 'current-range', 'archival-range', 'integral', 'gaussian', 'bundle'), default='all')
    args = parser.parse_args()
    check(args.guest.resolve(), args.runtime.resolve(), args.case)
