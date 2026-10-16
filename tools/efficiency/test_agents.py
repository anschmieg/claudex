import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from agents import NAMES, client_supported, definitions


AGENT = '''---
name: gpt-fast
description: Bounded worker
model: gpt-6-luna[1m]
effort: high
---
Keep tasks bounded and test them.
'''


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agents = Path(self.tmp.name)/'agents'
        self.owned = Path(self.tmp.name)/'owned'
        self.agents.mkdir()
        self.owned.mkdir()
        (self.agents/'gpt-fast.md').write_text(AGENT)
        (self.owned/'gpt-fast.md').write_text(AGENT)

    def test_version_gate(self):
        self.assertFalse(client_supported('2.1.294 (Claude Code)'))
        self.assertFalse(client_supported('corrupt'))
        self.assertTrue(client_supported('2.1.296 (Claude Code)'))
        self.assertTrue(client_supported('2.1.299 (Claude Code)'))
        self.assertEqual(definitions(self.agents, self.owned, 192000,
                                     256000, '2.1.294 (Claude Code)'), {})

    def test_session_only_faithful_agent_override(self):
        spec = definitions(self.agents, self.owned, 192000,
                           256000, '2.1.299 (Claude Code)')
        self.assertEqual(set(spec), {'gpt-fast'})
        agent = spec['gpt-fast']
        self.assertEqual(agent['autoCompactWindow'], 192000)
        self.assertEqual(agent['model'], 'gpt-6-luna[1m]')
        self.assertEqual(agent['effort'], 'high')
        self.assertEqual(agent['description'], 'Bounded worker')
        self.assertEqual(agent['prompt'], 'Keep tasks bounded and test them.')
        self.assertEqual((self.agents/'gpt-fast.md').read_text(), AGENT)

    def test_preserve_modified_unowned_and_symlinked_agent(self):
        (self.agents/'gpt-fast.md').write_text(AGENT + '\ncustom')
        self.assertEqual(definitions(self.agents, self.owned, 192000,
                                     256000, '2.1.299'), {})
        (self.agents/'gpt-fast.md').unlink()
        (self.agents/'gpt-fast.md').symlink_to(self.owned/'gpt-fast.md')
        self.assertEqual(definitions(self.agents, self.owned, 192000,
                                     256000, '2.1.299'), {})
        # Other people's agents must never be included.
        (self.agents/'unrelated.md').write_text(AGENT)
        self.assertNotIn('unrelated', NAMES)

    def test_project_agent_definition_wins(self):
        project = Path(self.tmp.name)/'project'
        local = project/'.claude'/'agents'
        local.mkdir(parents=True)
        (local/'gpt-fast.md').write_text('custom project agent')
        self.assertEqual(definitions(self.agents, self.owned, 192000,
                                     256000, '2.1.299', project_dir=project), {})

    def test_reject_worker_budget_above_coordinator(self):
        with self.assertRaisesRegex(ValueError, 'exceed'):
            definitions(self.agents, self.owned, 384000, 256000, '2.1.299')

    def test_cli_old_version_emits_no_json(self):
        cmd = [sys.executable, str(Path(__file__).with_name('agents.py')),
               str(self.agents), str(self.owned), '256000', '2.1.294']
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('2.1.296', result.stderr)

    def test_cli_new_version_json(self):
        cmd = [sys.executable, str(Path(__file__).with_name('agents.py')),
               str(self.agents), str(self.owned), '256000', '2.1.299']
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['gpt-fast']['autoCompactWindow'], 192000)
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
