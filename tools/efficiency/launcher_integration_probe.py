"""Run the committed launch() Bash function with fake runtime/Claude dependencies.

No production writes, provider calls, or credentials. Use in release gates as
a CLI integration smoke test alongside the ordinary unittest suite.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

repo=Path(__file__).resolve().parents[2]
_qa_temp=tempfile.TemporaryDirectory(prefix='claudex-launcher-integration-')
base=Path(_qa_temp.name)
launch=(repo/'claudex').read_text()
sdk=launch.split('merge_claude_sdk_settings() {',1)[1].split('\nlaunch() {',1)[0]
body=launch.split('launch() {',1)[1].split('\nuninstall_all() {',1)[0]
stub = r"""
set -euo pipefail
umask 077
have(){ command -v "$1" >/dev/null 2>&1; }
die(){ echo "DIE:$*" >&2; exit 41; }
with_runtime_lock(){ :; }
launch_cleanup(){ :; }
client_token(){ printf 'FAKE_LOCAL_TOKEN'; }
claude(){
  if [[ "${1:-}" == --version ]]; then printf '%s\n' "$MOCK_VERSION"; return 0; fi
  python3 - "$@" <<'CAPTURE'
import json,os,sys
args=sys.argv[1:]
path=args[args.index('--settings')+1] if '--settings' in args else None
settings=json.load(open(path)) if path else {}
print(json.dumps({
  'args':args,
  'compact_env':os.environ.get('CLAUDE_CODE_AUTO_COMPACT_WINDOW'),
  'compact_settings':settings.get('env',{}).get('CLAUDE_CODE_AUTO_COMPACT_WINDOW'),
  'idleCompaction':settings.get('idleCompaction','absent'),
  'has_read_hooks': bool(settings.get('hooks',{}).get('PreToolUse',[])),
  'sdk_flag':settings.get('ultracode','absent')
}))
CAPTURE
}
"""
# Use the true launcher function, no simulation of any conditional decisions.
stub += '\nmerge_claude_sdk_settings() {'+sdk+'\nlaunch() {'+body
cases = [
  ('adaptive_new', '2.1.300 (Claude Code)', 'adaptive', [], None, {}),
  ('adaptive_old', '2.1.294 (Claude Code)', 'adaptive', [], None, {}),
  ('off_new', '2.1.300 (Claude Code)', 'off', [], None, {}),
  ('caller_agents', '2.1.300 (Claude Code)', 'adaptive',
   ['--agents','{"custom":{"description":"User-owned","prompt":"Custom"}}'], None, {}),
  ('sdk_settings', '2.1.300 (Claude Code)', 'adaptive',
   ['--settings', '{"ultracode":true}'], None, {}),
  ('worker_over_cap', '2.1.300 (Claude Code)', 'adaptive', [], None,
   {'CLAUDEX_EFFICIENCY_WORKER_TARGET_TOKENS':'300000'}),
  ('project_owned', '2.1.300 (Claude Code)', 'adaptive', [], 'project', {}),
  ('guard_optin', '2.1.300 (Claude Code)', 'adaptive', [], None,
   {'CLAUDEX_EFFICIENCY_READ_GUARD':'deny'}),
]
for label,version,mode,extra,project,other_env in cases:
    root=base/label
    for suffix in ('state','sessions','cfg','data/efficiency','data/agents-owned','user_agents','project'):
        (root/suffix).mkdir(parents=True, exist_ok=True)
    for agent in ('gpt-fast','gpt-core'):
        text=f'''---
name: {agent}
description: Claudex test worker
model: gpt-6-luna[1m]
---
Synthetic agent instructions.
'''
        for sub in ('user_agents','data/agents-owned'):
            (root/sub/f'{agent}.md').write_text(text)
    if project:
        local=root/'project'/'.claude'/'agents'
        local.mkdir(parents=True,exist_ok=True)
        (local/'gpt-fast.md').write_text('user-customized project agent')
    for py in ('native.py','read_hook.py','agents.py'):
        shutil.copy2(repo/'tools'/'efficiency'/py,root/'data'/'efficiency'/py)
    conf=root/'cfg'/'settings.json'
    conf.write_text(json.dumps({'model':'gpt-6.1-sol[1m]', 'env':{'ANTHROPIC_BASE_URL':'http://127.0.0.1:12345','ANTHROPIC_AUTH_TOKEN':'FAKE'}}))
    env=dict(os.environ)
    env.update(HOME=str(root),
      STATE_ROOT=str(root/'state'), SESSION_DIR=str(root/'sessions'),
      DATA_ROOT=str(root/'data'), AGENTS_DIR=str(root/'user_agents'),
      CLAUDE_SETTINGS_SOL=str(conf), CLAUDE_SETTINGS_ASTRA=str(conf),
      CLAUDE_SETTINGS_LUNA=str(conf), BASE_URL='http://127.0.0.1:12345',
      MOCK_VERSION=version, CLAUDEX_EFFICIENCY=mode,
      CLAUDEX_USE_CODEX_DEFAULT_EFFORT='0', CLAUDEX_GPT_OVERLAY='0')
    env.update(other_env)
    result=subprocess.run(['bash','-c',stub+'\nlaunch sol "$@"\n','--', *extra],
         env=env,cwd=root/'project',capture_output=True,text=True,timeout=20)
    try:
        details=json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError,IndexError):
        details={}
    args=details.get('args',[])
    agentpos=[i for i,x in enumerate(args) if x=='--agents']
    payloads=[]
    for i in agentpos:
        try:payloads.append(json.loads(args[i+1]))
        except (IndexError,ValueError):payloads.append({})
    observed={'label':label,'returncode':result.returncode,'compact_env':details.get('compact_env'),
              'compact_settings':details.get('compact_settings'),'idleCompaction':details.get('idleCompaction'),
              'agent_keys':[list(p.keys()) for p in payloads],
              'worker_compact':[p.get('gpt-fast',{}).get('autoCompactWindow') for p in payloads],
              'sdk_flag':details.get('sdk_flag'),'read_guard':details.get('has_read_hooks'),
              'error':result.stderr[-180:].replace(str(root),'<FIXTURE>')}
    assert (result.returncode==41 if label=='worker_over_cap' else result.returncode==0),observed
    if label=='adaptive_new':
        assert observed['compact_env']==observed['compact_settings']=='256000',observed
        assert observed['worker_compact']==[192000] and observed['idleCompaction'] is False,observed
    if label=='adaptive_old':
        assert observed['compact_env']=='256000' and not payloads,observed
    if label=='off_new':
        assert observed['compact_env']=='272000' and not payloads and observed['idleCompaction']=='absent',observed
    if label=='caller_agents':
        assert len(payloads)==1 and list(payloads[0])==['custom'],observed
    if label=='sdk_settings':
        assert observed['sdk_flag'] is True and observed['worker_compact']==[192000],observed
    if label=='project_owned':
        assert len(payloads)==1 and 'gpt-fast' not in payloads[0] and 'gpt-core' in payloads[0],observed
    if label=='guard_optin':
        assert observed['read_guard'] is True,observed
    print(json.dumps({**observed,'status':'PASS'}))
