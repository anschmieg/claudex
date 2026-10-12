#!/usr/bin/env python3
"""Synthetic regression checks for T3 Code's Claude Agent SDK --settings merge."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
text = (root / 'claudex').read_text()
start = text.index('merge_claude_sdk_settings() {')
end = text.index('\nlaunch() {', start)
with tempfile.TemporaryDirectory(prefix='claudex-sdk-', dir=os.environ.get('CLAUDEX_TEST_TMPDIR')) as directory:
    temp = Path(directory)
    function = temp / 'merge.sh'
    function.write_text(text[start:end])
    base = temp / 'base.json'
    base.write_text(json.dumps({
        'model': 'gpt-6.1-sol[1m]',
        'env': {'ANTHROPIC_AUTH_TOKEN': 'synthetic-test-value', 'ANTHROPIC_BASE_URL': 'http://127.0.0.1:3147'},
        'modelPicker': {'replaceBuiltInOptions': True},
    }))

    def merge(payload, name):
        out = temp / (name + '.json')
        cmd = ['bash', '-c', 'source "$1"; merge_claude_sdk_settings "$2" "$3" "$4"', '--',
               str(function), str(base), json.dumps(payload), str(out)]
        return subprocess.run(cmd, capture_output=True, text=True), out

    for case, payload in [
        ('probe', {'disableAllHooks': True}),
        ('session', {'showThinkingSummaries': True, 'alwaysThinkingEnabled': False,
                     'fastMode': False, 'ultracode': False, 'autoCompactWindow': 272000}),
    ]:
        result, out = merge(payload, case)
        assert result.returncode == 0, (case, result.stderr)
        combined = json.loads(out.read_text())
        assert combined['env']['ANTHROPIC_AUTH_TOKEN'] == 'synthetic-test-value'
        assert combined['model'] == 'gpt-6.1-sol[1m]'
        assert combined['modelPicker'] == {'replaceBuiltInOptions': True}
        for key, value in payload.items():
            assert combined[key] == value

    for case, payload in [
        ('reject-token', {'env': {'ANTHROPIC_AUTH_TOKEN': 'override'}}),
        ('reject-model', {'model': 'evil'}),
        ('reject-modelpicker', {'modelPicker': {}}),
        ('reject-hooks', {'hooks': {'PreToolUse': []}}),
        ('reject-mcp', {'mcpServers': {}}),
        ('reject-disable-hooks-false', {'disableAllHooks': False}),
        ('reject-window', {'autoCompactWindow': -1}),
    ]:
        result, out = merge(payload, case)
        assert result.returncode != 0, case
        assert not out.exists(), case
print('T3_SDK_SETTINGS_MERGE=PASS')
