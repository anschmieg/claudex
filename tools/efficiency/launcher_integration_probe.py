"""Exercise the real launch() shell function with stubbed external processes.

No inference, user settings, credentials or production runtime mutations.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = (ROOT / 'claudex').read_text()
SDK = LAUNCHER.split('merge_claude_sdk_settings() {', 1)[1].split('\nlaunch() {', 1)[0]
BODY = LAUNCHER.split('launch() {', 1)[1].split('\nuninstall_all() {', 1)[0]
STUB = r"""
set -euo pipefail
umask 077
have(){ command -v "$1" >/dev/null 2>&1; }
die(){ echo "DIE:$*" >&2; exit 41; }
note(){ printf '%s\n' "$*" >&2; }
with_runtime_lock(){ :; }
launch_cleanup(){ :; }
client_token(){ printf 'FAKE'; }
claude(){
  python3 - "$@" <<'CAPTURE'
import json,os,sys
args=sys.argv[1:]
settings=json.load(open(args[args.index('--settings')+1]))
print(json.dumps({
  'args':args,
  'compact_env':os.environ.get('CLAUDE_CODE_AUTO_COMPACT_WINDOW'),
  'compact_setting_env':settings.get('env',{}).get('CLAUDE_CODE_AUTO_COMPACT_WINDOW'),
  'compact_setting_native':settings.get('autoCompactWindow'),
  'idle':settings.get('idleCompaction','absent'),
  'model_args':[args[i+1] for i,x in enumerate(args[:-1]) if x=='--model'],
  'compact_args':[args[i+1] for i,x in enumerate(args[:-1]) if x=='--autocompact'],
  'agent_args':[args[i+1] for i,x in enumerate(args[:-1]) if x=='--agents'],
  'read_guard':bool(settings.get('hooks',{}).get('PreToolUse',[])),
}))
CAPTURE
}
"""
STUB += '\nmerge_claude_sdk_settings() {' + SDK + '\nlaunch() {' + BODY
CASES = [
    ('adaptive', 'adaptive', [], {}),
    ('off', 'off', [], {}),
    ('caller_agents', 'adaptive', ['--agents', '{"user_agent":{"description":"custom","prompt":"preserve"}}'], {}),
    ('caller_compact', 'adaptive', ['--autocompact', '384000'], {}),
    ('direct_agent', 'adaptive', ['--agent', 'gpt-fast'], {}),
    ('direct_model', 'adaptive', ['--agent', 'gpt-fast', '--model', 'gpt-6-luna[1m]'], {}),
    ('extra_dir', 'adaptive', ['--add-dir', 'custom-plugins'], {}),
    ('sdk', 'adaptive', ['--settings', '{"ultracode":true}'], {}),
    ('sdk_compact', 'adaptive', ['--settings', '{"autoCompactWindow":512000}'], {}),
    ('read_guard', 'adaptive', [], {'CLAUDEX_EFFICIENCY_READ_GUARD': 'deny'}),
    ('large', 'adaptive', [], {'CLAUDEX_EFFICIENCY_LARGE_READ': '1'}),
    ('legacy_workers', 'adaptive', [], {'CLAUDEX_EFFICIENCY_WORKER_TARGET_TOKENS': '192000'}),
]
with tempfile.TemporaryDirectory(prefix='claudex-launcher-integration-') as t:
    for label, mode, extra, changes in CASES:
        base = Path(t) / label
        for directory in ('state', 'sessions', 'cfg', 'data/efficiency', 'project'):
            (base/directory).mkdir(parents=True)
        for f in ('native.py', 'read_hook.py'):
            shutil.copy2(ROOT / 'tools/efficiency' / f, base / 'data/efficiency' / f)
        conf = base / 'cfg/settings.json'
        conf.write_text(json.dumps({
            'env': {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:12345',
                    'ANTHROPIC_AUTH_TOKEN': 'FAKE',
                    'CLAUDE_CODE_AUTO_COMPACT_WINDOW': '272000'},
        }))
        env = dict(os.environ)
        env.update(HOME=str(base), STATE_ROOT=str(base / 'state'),
                   SESSION_DIR=str(base / 'sessions'),
                   DATA_ROOT=str(base / 'data'),
                   CLAUDE_SETTINGS_SOL=str(conf),
                   CLAUDE_SETTINGS_ASTRA=str(conf),
                   CLAUDE_SETTINGS_LUNA=str(conf),
                   BASE_URL='http://127.0.0.1:12345',
                   CLAUDEX_EFFICIENCY=mode,
                   CLAUDEX_USE_CODEX_DEFAULT_EFFORT='0',
                   CLAUDEX_GPT_OVERLAY='0')
        env.update(changes)
        run = subprocess.run(['bash', '-c', STUB + '\nlaunch sol "$@"\n', '--', *extra],
                             cwd=base / 'project', env=env, capture_output=True,
                             text=True, timeout=20)
        assert run.returncode == 0, (label, run.stderr)
        report = json.loads(run.stdout.strip().splitlines()[-1])
        args = report['args']
        if mode == 'adaptive':
            assert report['compact_env'] is None, label
            assert report['compact_setting_env'] is None, label
            expected = 512000 if label == 'sdk_compact' else 768000 if label == 'large' else 256000
            assert report['compact_setting_native'] == expected, label
            assert report['idle'] is False, label
            assert '--agents' not in args if label != 'caller_agents' else args.count('--agents') == 1, label
        else:
            assert report['compact_env'] == '272000' and report['compact_setting_native'] is None, label
        if label == 'caller_agents':
            assert report['agent_args'] == [extra[1]], report
        if label == 'caller_compact':
            assert report['compact_args'] == ['384000'], report
        elif label == 'sdk_compact':
            assert report['compact_args'] == [], report
        elif mode == 'adaptive':
            assert report['compact_args'] == [str(report['compact_setting_native'])], report
        if label == 'legacy_workers':
            assert 'Obsolete worker budget' in run.stderr, run.stderr
        if label == 'direct_agent':
            assert report['model_args'] == [], report
        if label == 'direct_model':
            assert report['model_args'] == ['gpt-6-luna[1m]'], report
        if label == 'read_guard':
            assert report['read_guard'], report
        print(f'PASS {label}')
