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
        for env in ({}, {'CLAUDEX_EFFICIENCY': 'advisory'},
                    {'CLAUDEX_EFFICIENCY': 'off',
                     'CLAUDEX_EFFICIENCY_LARGE_READ': '1'}):
            self.assertEqual(window(env), DEFAULT)

    def test_medium_default_is_smaller_than_previous_behavior(self):
        self.assertEqual(window(self.adaptive()), 256000)
        self.assertLess(window(self.adaptive()), DEFAULT)
        self.assertLess(window(self.adaptive()), 384000)

    def test_tiers_are_compaction_thresholds(self):
        self.assertEqual(TIERS, {'small': 192000, 'medium': 256000, 'large': 768000})
        for tier, limit in TIERS.items():
            self.assertEqual(window(self.adaptive(CLAUDEX_EFFICIENCY_CONTEXT_TIER=tier)), limit)

    def test_custom_target_and_large_read_expansion(self):
        self.assertEqual(window(self.adaptive(CLAUDEX_EFFICIENCY_TARGET_TOKENS='400000')), 400000)
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

    def test_private_settings_turn_off_unverified_idle_ttl(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp)/'source.json', Path(tmp)/'output.json'
            source.write_text(json.dumps({
                'env': {'USER_KEEP': 'yes'}, 'hooks': {'Stop': []},
                'idleCompaction': True,
            }))
            patch_settings(source, output, window(self.adaptive()))
            patched = json.loads(output.read_text())
            self.assertEqual(patched['env']['CLAUDE_CODE_AUTO_COMPACT_WINDOW'], '256000')
            self.assertEqual(patched['env']['USER_KEEP'], 'yes')
            self.assertEqual(patched['hooks'], {'Stop': []})
            self.assertIs(patched['idleCompaction'], False)
            # Never rewrite the persistent source on disk.
            self.assertIs(json.loads(source.read_text())['idleCompaction'], True)

    def test_legacy_hook_executes_at_path_with_spaces_metachars(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp)/'a.json', Path(tmp)/'b.json'
            hook = Path(tmp)/'my guard;echo malicious.py'
            source.write_text(json.dumps({
                'env': {}, 'hooks': {'PreToolUse': [{'matcher': 'Bash'}]},
            }))
            hook.write_text('print("SAFE_HOOK_OK")\n')
            patch_settings(source, output, 192000, hook)
            steps = json.loads(output.read_text())['hooks']['PreToolUse']
            self.assertEqual(len(steps), 2)
            self.assertEqual(steps[0]['matcher'], 'Bash')
            self.assertEqual(steps[1]['matcher'], 'Read')
            result = subprocess.run(['sh', '-c', steps[1]['hooks'][0]['command']],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'SAFE_HOOK_OK')
            self.assertFalse((Path.cwd() / 'malicious.py').exists())

    def test_malformed_settings_refuse_to_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp)/'a.json', Path(tmp)/'b.json'
            source.write_text('{"env":{}, "hooks":{"PreToolUse":"bad"}}')
            hook = Path(tmp)/'guard.py'
            hook.write_text('pass')
            with self.assertRaises(ValueError):
                patch_settings(source, output, 192000, hook)
            self.assertFalse(output.exists())

    def test_helper_cli(self):
        script = Path(__file__).with_name('native.py')
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp)/'a.json', Path(tmp)/'b.json'
            source.write_text('{"env": {}}')
            p = subprocess.run([sys.executable, str(script), '--patch-settings',
                                str(source), str(output), '256000'],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual(json.loads(output.read_text())['env']
                             ['CLAUDE_CODE_AUTO_COMPACT_WINDOW'], '256000')


if __name__ == '__main__':
    unittest.main(verbosity=2)
