#!/usr/bin/env python3
"""Exercise the exact Bash argument-selection block, including overrides, in macOS Bash 3.2."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SOURCE = (REPO / "claudex").read_text()
START = SOURCE.index("  # Codex (not Claude Code) owns the implicit reasoning default.")
END = SOURCE.index("  # Do not exec:", START)
BLOCK = SOURCE[START:END]


class Tests(unittest.TestCase):
    def run_selection(self, *args, enabled="1"):
        with tempfile.TemporaryDirectory() as td:
            helper = Path(td) / "codex-helper"
            helper.write_text('''#!/usr/bin/env python3
import sys
model = sys.argv[-1].split('[')[0]
levels = {'gpt-synthetic-sol': 'low', 'gpt-synthetic-astra': 'medium'}
if model in levels:
    print(levels[model])
''')
            helper.chmod(0o755)
            script = '''set -euo pipefail
have() { command -v "$1" >/dev/null 2>&1; }
run_selection() {
  local selected_model="$1"; shift
  local REASONING_HELPER="$DYNAMIC_HELPER"
  local -a forwarded_args=("$@")
''' + BLOCK + '''
  printf 'RESULT:%s:%s\\n' "$effective_model" "${default_effort_args[*]-}"
}
run_selection "$@"
'''
            env = dict(os.environ, DYNAMIC_HELPER=str(helper), CLAUDEX_USE_CODEX_DEFAULT_EFFORT=enabled)
            proc = subprocess.run(['/bin/bash', '-c', script, '--', *args], env=env,
                                  capture_output=True, text=True, timeout=9)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return proc.stdout.strip().split('RESULT:', 1)[-1]

    def test_default_per_model(self):
        self.assertEqual(self.run_selection('gpt-synthetic-sol[1m]'), 'gpt-synthetic-sol[1m]:--effort low')
        self.assertEqual(self.run_selection('gpt-synthetic-astra[1m]'), 'gpt-synthetic-astra[1m]:--effort medium')

    def test_explicit_user_effort_takes_precedence(self):
        self.assertEqual(self.run_selection('gpt-synthetic-sol', '--effort', 'high'), 'gpt-synthetic-sol:')
        self.assertEqual(self.run_selection('gpt-synthetic-sol', '--effort=high'), 'gpt-synthetic-sol:')

    def test_sdk_model_override_uses_effective_model(self):
        self.assertEqual(self.run_selection('gpt-synthetic-sol', '--model', 'gpt-synthetic-astra[1m]'),
                         'gpt-synthetic-astra[1m]:--effort medium')
        self.assertEqual(self.run_selection('gpt-synthetic-sol', '--model=gpt-synthetic-astra[1m]'),
                         'gpt-synthetic-astra[1m]:--effort medium')

    def test_no_discovery_does_not_fake_default(self):
        self.assertEqual(self.run_selection('gpt-unknown'), 'gpt-unknown:')
        self.assertEqual(self.run_selection('gpt-synthetic-sol', enabled='0'), 'gpt-synthetic-sol:')


if __name__ == '__main__':
    unittest.main(verbosity=2)
