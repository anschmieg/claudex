#!/usr/bin/env python3
"""Test the actual Bash overlay assembly block independently of any model API."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SOURCE = (REPO / 'claudex').read_text()
START = SOURCE.index('  # Load our small, separately versioned GPT overlay at *session startup*.')
END = SOURCE.index('  # Do not exec:', START)
BLOCK = SOURCE[START:END]


class PromptOverlay(unittest.TestCase):
    def execute(self, args=(), overlay='GPT overlay', enabled='1', existing_file=None):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            overlay_path = root / 'overlay.md'
            overlay_path.write_text(overlay)
            source_file = root / 'incoming.md'
            source_file.write_text(existing_file or '')
            rewritten = [str(source_file) if part == ':incoming:' else part for part in args]
            script = '''set -euo pipefail
launch_test() {
  local GPT_OVERLAY_FILE="$TEST_OVERLAY_FILE"
  local -a forwarded_args=("$@")
  local index
  die() { echo "ERROR:$*" >&2; exit 4; }
''' + BLOCK + '''
  printf '%s\\n' "${#append_prompt_args[@]}" ${append_prompt_args[@]+"${append_prompt_args[@]}"} '---FORWARD---' ${merged_cli_args[@]+"${merged_cli_args[@]}"}
}
launch_test "$@"
'''
            env = dict(os.environ, TEST_OVERLAY_FILE=str(overlay_path), CLAUDEX_GPT_OVERLAY=enabled)
            p = subprocess.run(['/bin/bash', '-c', script, '--', *rewritten],
                               capture_output=True, text=True, env=env, timeout=7)
            return p

    def test_separate_overlay_file_appended(self):
        p=self.execute(['--model', 'gpt-synthetic'], overlay='GPT supplementary instructions')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('2\n--append-system-prompt\nGPT supplementary instructions', p.stdout)
        self.assertIn('---FORWARD---\n--model\ngpt-synthetic',p.stdout)

    def test_sdk_and_user_append_preserved_in_order(self):
        p=self.execute(['--append-system-prompt', 'SDK context', '--model', 'gpt-synthetic',
                        '--append-system-prompt=User additions'], overlay='GPT overlay')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('SDK context\n\nUser additions\n\nGPT overlay', p.stdout)
        self.assertEqual(p.stdout.count('--append-system-prompt\n'), 1)

    def test_file_append_and_explicit_system_prompt(self):
        p=self.execute(['--append-system-prompt-file', ':incoming:', '--system-prompt', 'Custom system'],
                       overlay='GPT overlay', existing_file='Other appended file')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('Other appended file\n\nGPT overlay', p.stdout)
        self.assertIn('---FORWARD---\n--system-prompt\nCustom system',p.stdout)

    def test_opt_out_never_swallows_user_append(self):
        p=self.execute(['--append-system-prompt','User-only'],enabled='0')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('2\n--append-system-prompt\nUser-only',p.stdout)
        self.assertNotIn('GPT overlay',p.stdout)

    def test_empty_argv_safe_on_bash32(self):
        p=self.execute((),overlay='',enabled='0')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('0\n---FORWARD---',p.stdout)

    def test_missing_flag_value_rejected(self):
        p=self.execute(['--append-system-prompt'], overlay='GPT overlay')
        self.assertEqual(p.returncode,4)
        self.assertIn('Missing --append-system-prompt value',p.stderr)

    def test_symlinked_overlay_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'overlay.md';p.write_text('text');l=Path(td)/'linked.md';l.symlink_to(p)
            script=BLOCK
            code='''set -euo pipefail
launch_test() {
local GPT_OVERLAY_FILE="$1"; shift
local -a forwarded_args=("$@")
local index
die() { echo "$*" >&2; exit 4; }
'''+script+'''
}
launch_test "$@"
'''
            proc=subprocess.run(['/bin/bash','-c',code,'--',str(l)],capture_output=True,text=True,env=dict(os.environ,CLAUDEX_GPT_OVERLAY="1"))
            self.assertEqual(proc.returncode,4)
            self.assertIn('Refusing symlinked GPT overlay',proc.stderr)

if __name__ == '__main__': unittest.main(verbosity=2)
