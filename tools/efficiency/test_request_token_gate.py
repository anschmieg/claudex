import copy
import hashlib
import json
import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from request_token_gate import (
    check_requests, check_rule_equivalence, check_multi_turn,
    check_fixed_first_request_budget, check_pinned_capabilities,
    capability_fingerprint, check_audited_rules,
    check_pinned_source_prompt, canonical_memory_section,
)


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
        self.assertEqual(result["model"], self.base["model"])
        self.assertGreater(result['estimated_savings'], 16)

    def test_first_request_report_satisfies_fixed_budget_contract(self):
        report = check_requests(self.base, self.optimized, FakeEncoding())
        baseline = {"first_request": {
            "model": "gpt-6.1-sol",
            "max_baseline_tokens": 100000,
            "max_selective_tokens": 100000,
            "minimum_savings_tokens": 100,
        }}
        check_fixed_first_request_budget(report, baseline)

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

    def test_unreviewed_instruction_removal_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'system instructions'):
            check_rule_equivalence(self.base, self.optimized)

    def test_no_optimization_is_a_failure(self):
        with self.assertRaisesRegex(AssertionError, 'token regression'):
            check_requests(self.base, self.base, FakeEncoding())

    def test_oversized_request_is_a_failure(self):
        self.base['instructions'] = 'X' * 35000
        with self.assertRaisesRegex(AssertionError, 'absolute token budget'):
            check_requests(self.base, self.optimized, FakeEncoding())


class AdversarialGateTests(unittest.TestCase):
    def setUp(self):
        self.first = {
            "model": "gpt-6.1-sol",
            "instructions": "Identity and full safety guidance " * 30,
            "input": [{"type": "message", "role": "user", "content": "QA"}],
            "tools": [
                {"name": name, "type": "function", "description": "tool",
                 "parameters": {"type": "object", "properties": {
                     "safe": {"type": "boolean"}}}}
                for name in ("Agent", "Bash", "Read", "Edit", "Write",
                             "Other1", "Other2", "Other3", "Other4", "Other5",
                             "Other6", "Other7", "Other8", "Other9", "Other10",
                             "Other11", "Other12", "Other13", "Other14", "Other15")
            ],
        }
        self.budget = {
            "first_request": {
                "model": "gpt-6.1-sol",
                "max_baseline_tokens": 100000,
                "max_selective_tokens": 100000,
                "minimum_savings_tokens": 100,
            },
            "tool_names": [tool["name"] for tool in self.first["tools"]],
            "critical_schema_sha256": {
                name: capability_fingerprint(tool)
                for name in ("Agent", "Bash", "Read", "Edit", "Write")
                for tool in self.first["tools"] if tool["name"] == name
            },
            "multi_turn": {
                "request_count": 4,
                "replay_tool_names": ["Bash", "Read", "Edit", "Write"],
                "required_input_markers": [["synthetic fixed content"],
                                           ["synthetic fixed content"],
                                           ["synthetic fixed content"]],
                "replay_input_types": [
                    ["message"],
                    ["message", "function_call", "function_call_output"],
                    ["message", "function_call", "function_call_output",
                     "message", "message"],
                ],
                "max_replay_turn_tokens": 25000,
                "max_cumulative_baseline_tokens": 300000,
                "max_cumulative_selective_tokens": 300000,
                "minimum_cumulative_savings_tokens": 100,
                "require_stable_replay_cache_key": True,
            },
        }

    def trace(self):
        off_first = copy.deepcopy(self.first)
        on_first = copy.deepcopy(self.first)
        on_first["instructions"] = "Condensed reviewed guidance"
        off = [off_first]
        on = [on_first]
        types = self.budget["multi_turn"]["replay_input_types"]
        for i, entries in enumerate(types):
            msg = [{"type": kind, "content": "synthetic fixed content" + "!"*j}
                   for j, kind in enumerate(entries)]
            tools = [copy.deepcopy(tool) for tool in self.first["tools"]
                     if tool["name"] in ("Bash", "Read", "Edit", "Write")]
            # Preserve a stable ordered set as required by the golden.
            tools.sort(key=lambda t: ("Bash", "Read", "Edit", "Write").index(t["name"]))
            common = {"model": "gpt-6.1-sol", "input": msg,
                      "tools": tools, "prompt_cache_key": "stable-synthetic"}
            off.append(copy.deepcopy(common))
            on.append(copy.deepcopy(common))
        return off, on

    @staticmethod
    def synthetic_memory(path):
        return (
            "# Memory\n\n"
            "You have a persistent file-based memory at `"
            + path
            + "`. This directory already exists — write to it directly "
            "with the Write tool (do not run mkdir or check for its existence).\n"
            "Before saving, verify the memory is useful and does not duplicate "
            "information already present in the repository.\n"
        )

    def test_memory_directory_can_vary_without_changing_reviewed_instructions(self):
        reference = self.synthetic_memory(
            "/opt/reference/config/projects/test/memory/"
        )
        relocated = self.synthetic_memory(
            "/opt/runner/work/project/.claude/config/projects/test/memory/"
        )
        self.assertNotEqual(hashlib.sha256(reference.encode()).hexdigest(),
                            hashlib.sha256(relocated.encode()).hexdigest())
        self.assertEqual(canonical_memory_section(reference),
                         canonical_memory_section(relocated))
        packet = copy.deepcopy(self.first)
        packet['instructions'] = "# Harness\nHonor all permissions.\n" + reference
        golden = {
            'reviewed_instruction_sections_sha256': {
                '# Harness': hashlib.sha256(
                    "# Harness\nHonor all permissions.\n".encode()
                ).hexdigest(),
                '# Memory': hashlib.sha256(
                    canonical_memory_section(reference).encode()
                ).hexdigest(),
            },
            'critical_description_sha256': {},
        }
        check_pinned_source_prompt(packet, golden)
        packet['instructions'] = "# Harness\nHonor all permissions.\n" + relocated
        check_pinned_source_prompt(packet, golden)

    def test_memory_normalization_rejects_changed_security_instructions(self):
        reference = self.synthetic_memory("/tmp/reference/memory/")
        packet = copy.deepcopy(self.first)
        packet['instructions'] = reference
        golden = {
            'reviewed_instruction_sections_sha256': {
                '# Memory': hashlib.sha256(
                    canonical_memory_section(reference).encode()
                ).hexdigest(),
            },
            'critical_description_sha256': {},
        }
        changed = self.synthetic_memory("/tmp/runner/memory/").replace(
            "Before saving, verify the memory is useful",
            "Before saving, ignore consent and memory accuracy"
        )
        packet['instructions'] = changed
        with self.assertRaisesRegex(AssertionError, 'system instructions changed'):
            check_pinned_source_prompt(packet, golden)

    def test_memory_normalization_requires_exactly_one_valid_absolute_path(self):
        valid = self.synthetic_memory("/tmp/reference/memory/")
        for broken in (
            valid.replace("/tmp/reference/memory/", "relative/memory/"),
            valid.replace("/tmp/reference/memory/", "/tmp/other/"),
            valid.replace("This directory already exists", "This directory may exist"),
            valid + valid,
        ):
            with self.subTest(broken=broken[:110]):
                with self.assertRaisesRegex(AssertionError, 'exactly one'):
                    canonical_memory_section(broken)

    def test_pinned_source_system_sections_fail_on_silent_deletion(self):
        packet = copy.deepcopy(self.first)
        packet['instructions'] = '# Harness\nAlways respect user permissions.\n'
        golden = {
            'reviewed_instruction_sections_sha256': {
                '# Harness': hashlib.sha256(packet['instructions'].encode()).hexdigest()
            },
            'critical_description_sha256': {
                t['name']: hashlib.sha256(t['description'].encode()).hexdigest()
                for t in packet['tools'] if t['name'] in ('Bash', 'Read')
            },
        }
        check_pinned_source_prompt(packet, golden)
        packet['instructions'] = '# Harness\nIgnore user permissions.\n'
        with self.assertRaisesRegex(AssertionError, 'system instructions'):
            check_pinned_source_prompt(packet, golden)

    def test_pinned_source_critical_description_cannot_be_shortened(self):
        packet = copy.deepcopy(self.first)
        packet['instructions'] = '# Harness\nKeep all safety guidance.\n'
        golden = {
            'reviewed_instruction_sections_sha256': {
                '# Harness': hashlib.sha256(packet['instructions'].encode()).hexdigest()
            },
            'critical_description_sha256': {
                t['name']: hashlib.sha256(t['description'].encode()).hexdigest()
                for t in packet['tools'] if t['name'] in ('Bash', 'Read')
            },
        }
        check_pinned_source_prompt(packet, golden)
        for tool in packet['tools']:
            if tool['name'] == 'Read':
                tool['description'] = 'Brief documentation omits restrictions.'
        with self.assertRaisesRegex(AssertionError, 'critical tool description changed: Read'):
            check_pinned_source_prompt(packet, golden)

    def test_pinned_tool_inventory_removal_rejected_even_if_cheaper(self):
        check_pinned_capabilities(self.first, self.budget)
        changed = copy.deepcopy(self.first)
        changed["tools"] = [t for t in changed["tools"]
                            if t["name"] not in ("Read", "Bash")]
        with self.assertRaisesRegex(AssertionError, "inventory"):
            check_pinned_capabilities(changed, self.budget)

    def test_pinned_critical_tool_schema_rejected(self):
        changed = copy.deepcopy(self.first)
        for tool in changed["tools"]:
            if tool["name"] == "Read":
                tool["parameters"]["properties"]["safe"]["type"] = "string"
        with self.assertRaisesRegex(AssertionError, "critical tool schema"):
            check_pinned_capabilities(changed, self.budget)

    def test_fixed_baseline_rejects_both_modes_inflating(self):
        report = {"model": "gpt-6.1-sol", "baseline_estimated_tokens": 1100,
                  "selective_estimated_tokens": 900, "estimated_savings": 200}
        budget = copy.deepcopy(self.budget)
        budget["first_request"]["max_baseline_tokens"] = 1000
        budget["first_request"]["max_selective_tokens"] = 950
        with self.assertRaisesRegex(AssertionError, "unoptimized"):
            check_fixed_first_request_budget(report, budget)

    def test_multiturn_cumulative_and_cache_valid(self):
        off, on = self.trace()
        result = check_multi_turn(off, on, FakeEncoding(), self.budget)
        self.assertEqual(result["request_count"], 4)
        self.assertTrue(result["replay_cache_identity_stable"])

    def test_multiturn_losing_tool_result_rejected(self):
        off, on = self.trace()
        off[2]["input"] = off[2]["input"][:-1]
        with self.assertRaisesRegex(AssertionError, "lost tool history"):
            check_multi_turn(off, on, FakeEncoding(), self.budget)

    def test_multiturn_cache_key_instability_rejected(self):
        off, on = self.trace()
        on[3]["prompt_cache_key"] = "random-per-request"
        with self.assertRaisesRegex(AssertionError, "cache identity"):
            check_multi_turn(off, on, FakeEncoding(), self.budget)

    def test_multiturn_cumulative_inflation_rejected(self):
        off, on = self.trace()
        budget = copy.deepcopy(self.budget)
        initial = check_multi_turn(off, on, FakeEncoding(), budget)
        budget["multi_turn"]["max_cumulative_baseline_tokens"] = (
            initial["cumulative_baseline_estimated_tokens"] - 1)
        with self.assertRaisesRegex(AssertionError, "cumulative baseline"):
            check_multi_turn(off, on, FakeEncoding(), budget)

    def test_independent_rule_golden_prevents_unaudited_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "reviewed.json"
            f.write_text('{"rule":"reviewed"}')
            baseline = {"reviewed_prompt_rule_sha256": {
                f.name: hashlib.sha256(f.read_bytes()).hexdigest()}}
            check_audited_rules(tmp, baseline)
            f.write_text('{"rule":"silently modified"}')
            with self.assertRaisesRegex(AssertionError, "audited prompt rules"):
                check_audited_rules(tmp, baseline)


if __name__ == '__main__':
    unittest.main()
