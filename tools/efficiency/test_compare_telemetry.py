import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from compare_telemetry import analyze

SCRIPT = Path(__file__).with_name('compare_telemetry.py')


class TraceTests(unittest.TestCase):
    def make_trace(self, events):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name)/'trace.jsonl'
        path.write_text(''.join(json.dumps(event) + '\n' for event in events))
        return path

    def test_usage_deduplicated_and_cache_coverage_visible(self):
        usage = {'input_tokens': 10, 'output_tokens': 3,
                 'cache_read_input_tokens': 90,
                 'cache_creation_input_tokens': 5}
        trace = self.make_trace([
            {'type': 'assistant', 'message': {
                'id': 'msg_1', 'content': [{'text': 'PRIVATE PAYLOAD'}],
                'usage': usage}},
            {'type': 'assistant', 'message': {
                'id': 'msg_1', 'usage': {**usage, 'output_tokens': 4}}},
            {'type': 'system', 'subtype': 'compact_boundary'},
            {'type': 'assistant', 'message': {
                'id': 'msg_2', 'usage': {'input_tokens': 20, 'output_tokens': 7}}},
            {'type': 'result', 'usage': usage},
        ])
        report = analyze(trace)
        self.assertEqual(report['assistant_messages_with_usage'], 2)
        self.assertEqual(report['compact_boundaries'], 1)
        self.assertEqual(report['reported_usage']['input_tokens']['tokens'], 30)
        self.assertEqual(report['reported_usage']['output_tokens']['tokens'], 11)
        self.assertEqual(report['reported_usage']['cache_read_input_tokens']['tokens'], 90)
        self.assertFalse(report['cache_metrics_complete'])
        result = subprocess.run([sys.executable, str(SCRIPT), f'medium={trace}'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('PRIVATE PAYLOAD', result.stdout)
        self.assertIn('medium', json.loads(result.stdout)['results'])

    def test_reject_invalid_usage(self):
        trace = self.make_trace([
            {'type': 'assistant', 'message': {
                'id': 'x', 'usage': {'input_tokens': -3}}},
        ])
        with self.assertRaises(ValueError):
            analyze(trace)

    def test_empty_trace_does_not_claim_cache_coverage(self):
        trace = self.make_trace([{'type': 'result', 'usage': {'input_tokens': 100}}])
        self.assertEqual(analyze(trace)['assistant_messages_with_usage'], 0)
        self.assertFalse(analyze(trace)['cache_metrics_complete'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
