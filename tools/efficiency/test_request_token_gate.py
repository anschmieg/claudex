import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from request_token_gate import check_requests


class FakeEncoding:
    def encode(self, text):
        return text.encode('utf-8')


class TokenGateTests(unittest.TestCase):
    def setUp(self):
        self.base = {
            'model': 'gpt-6.1-sol',
            'instructions': 'Long synthetic policy. ' * 160,
            'input': [{'role': 'user', 'content': 'Keep my request unchanged'}],
            'tools': [{
                'type': 'function',
                'name': 'Read',
                'description': 'Long tool documentation. ' * 200,
                'parameters': {'type': 'object',
                               'properties': {'path': {'type': 'string'}}},
            }],
        }
        # Ensure token gates cover the full coding tool schema, not bare mode.
        for i in range(19):
            self.base['tools'].append({
                'type': 'function', 'name': f'SyntheticTool{i}',
                'description': 'Small synthetic description',
                'parameters': {'type': 'object'},
            })
        self.optimized = copy.deepcopy(self.base)
        self.optimized['instructions'] = 'Short synthetic policy.'
        self.optimized['tools'][0]['description'] = 'Short tool docs.'

    def test_reduced_tokens_preserve_user_and_schema(self):
        result = check_requests(self.base, self.optimized, FakeEncoding())
        self.assertGreater(result['estimated_savings'], 16)

    def test_request_semantics_are_a_hard_gate(self):
        self.optimized['input'][0]['content'] = 'Changed!'
        with self.assertRaisesRegex(AssertionError, 'user message'):
            check_requests(self.base, self.optimized, FakeEncoding())

    def test_tool_schemas_are_a_hard_gate(self):
        self.optimized['tools'][0]['parameters']['properties']['path']['type'] = 'integer'
        with self.assertRaisesRegex(AssertionError, 'tool schema'):
            check_requests(self.base, self.optimized, FakeEncoding())

    def test_volatile_cache_key_is_not_user_content(self):
        self.base['prompt_cache_key'] = 'session-off'
        self.optimized['prompt_cache_key'] = 'session-on'
        self.assertGreater(check_requests(self.base, self.optimized,
                                          FakeEncoding())['estimated_savings'], 100)

    def test_missing_tools_are_not_a_success(self):
        self.base['tools'] = self.base['tools'][:1]
        with self.assertRaisesRegex(AssertionError, 'coding tools'):
            check_requests(self.base, self.optimized, FakeEncoding())

    def test_no_optimization_is_a_failure(self):
        with self.assertRaisesRegex(AssertionError, 'token regression'):
            check_requests(self.base, self.base, FakeEncoding())

    def test_oversized_request_is_a_failure(self):
        self.base['instructions'] = 'X' * 35000
        with self.assertRaisesRegex(AssertionError, 'absolute token budget'):
            check_requests(self.base, self.optimized, FakeEncoding())


if __name__ == '__main__':
    unittest.main()
