import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from native import DEFAULT, TIERS, patch_settings, window


class NativeTests(unittest.TestCase):
    def adaptive(self, **kwargs):
        return {'CLAUDEX_EFFICIENCY': 'adaptive', **kwargs}

    def test_disabled_original(self):
        self.assertEqual(window({}), DEFAULT)
        self.assertEqual(window({'CLAUDEX_EFFICIENCY': 'advisory'}), DEFAULT)
        self.assertEqual(window({'CLAUDEX_EFFICIENCY': 'off',
                                 'CLAUDEX_EFFICIENCY_LARGE_READ': '1'}), DEFAULT)

    def test_medium_default(self):
        self.assertEqual(window(self.adaptive()), 384000)

    def test_budgets_have_headroom(self):
        self.assertEqual(TIERS, {'small': 192000, 'medium': 384000, 'large': 768000})
        for tier, limit in TIERS.items():
            self.assertEqual(window(self.adaptive(CLAUDEX_EFFICIENCY_CONTEXT_TIER=tier)), limit)

    def test_custom_target(self):
        self.assertEqual(window(self.adaptive(CLAUDEX_EFFICIENCY_TARGET_TOKENS='400000')), 400000)

    def test_large_read_expands_only_at_launch(self):
        self.assertEqual(window(self.adaptive(CLAUDEX_EFFICIENCY_LARGE_READ='1')), 768000)
        self.assertEqual(window(self.adaptive(CLAUDEX_EFFICIENCY_CONTEXT_TIER='large',
                                             CLAUDEX_EFFICIENCY_LARGE_READ='1',
                                             CLAUDEX_EFFICIENCY_LARGE_READ_TOKENS='500000')), 768000)

    def test_invalid(self):
        for extra in [
            {'CLAUDEX_EFFICIENCY_CONTEXT_TIER': 'extreme'},
            {'CLAUDEX_EFFICIENCY_TARGET_TOKENS': '99999'},
            {'CLAUDEX_EFFICIENCY_TARGET_TOKENS': '1000001'},
            {'CLAUDEX_EFFICIENCY_TARGET_TOKENS': '20K'},
            {'CLAUDEX_EFFICIENCY_LARGE_READ': 'maybe'},
            {'CLAUDEX_EFFICIENCY_LARGE_READ': '1',
             'CLAUDEX_EFFICIENCY_LARGE_READ_TOKENS': '80000'},
        ]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                window(self.adaptive(**extra))

    def test_private_settings_default_has_no_read_denial(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp)/'source.json', Path(tmp)/'output.json'
            source.write_text(json.dumps({'env': {'USER_KEEP': 'yes'}, 'hooks': {'Stop': []}}))
            patch_settings(source, output, window(self.adaptive()))
            patched = json.loads(output.read_text())
            self.assertEqual(patched['env']['CLAUDE_CODE_AUTO_COMPACT_WINDOW'], '384000')
            self.assertEqual(patched['env']['USER_KEEP'], 'yes')
            self.assertEqual(patched['hooks'], {'Stop': []})
            self.assertEqual(json.loads(source.read_text())['env'], {'USER_KEEP': 'yes'})

    def test_explicit_legacy_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output, hook = (Path(tmp)/name for name in ('a.json', 'b.json', 'read.py'))
            source.write_text(json.dumps({'env': {}, 'hooks': {'PreToolUse': [{'matcher': 'Bash'}]}}))
            hook.write_text('# guard')
            patch_settings(source, output, 192000, hook)
            steps = json.loads(output.read_text())['hooks']['PreToolUse']
            self.assertEqual(len(steps), 2)
            self.assertEqual(steps[0]['matcher'], 'Bash')
            self.assertEqual(steps[1]['matcher'], 'Read')

    def test_helper_cli(self):
        script = Path(__file__).with_name('native.py')
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp)/'a.json', Path(tmp)/'b.json'
            source.write_text('{"env": {}}')
            p = subprocess.run([sys.executable, str(script), '--patch-settings',
                                str(source), str(output), '384000'],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(output.read_text())['env']
                             ['CLAUDE_CODE_AUTO_COMPACT_WINDOW'], '384000')


if __name__ == '__main__':
    unittest.main(verbosity=2)
