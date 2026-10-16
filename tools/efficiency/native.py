#!/usr/bin/env python3
"""Opt-in native Claude Code compaction budget: no token-history manipulation."""
import os
import sys

DEFAULT = 272000
MINIMUM = 16000
MAXIMUM = 272000

def window(env=None):
    env=os.environ if env is None else env
    mode=env.get('CLAUDEX_EFFICIENCY','off')
    if mode != 'adaptive':
        return DEFAULT
    raw=env.get('CLAUDEX_EFFICIENCY_TARGET_TOKENS','64000')
    if not raw.isdecimal():
        raise ValueError('target must be an integer')
    target=int(raw)
    if not MINIMUM<=target<=MAXIMUM:
        raise ValueError('target must be between 16000 and 272000')
    # Explicit scoped expansion is useful for huge file/tool reads. Never
    # inspect the file content or the user's prompt to grant an exception.
    expand=env.get('CLAUDEX_EFFICIENCY_LARGE_READ','0')
    if expand not in ('0','1'):
        raise ValueError('large-read override must be 0 or 1')
    if expand=='1':
        raw=env.get('CLAUDEX_EFFICIENCY_LARGE_READ_TOKENS','192000')
        if not raw.isdecimal():raise ValueError('invalid large-read budget')
        target=max(target,min(int(raw),MAXIMUM))
    return target

def patch_settings(source,destination,budget,read_hook=None):
    import json
    from pathlib import Path
    src=Path(source)
    obj=json.loads(src.read_text())
    if not isinstance(obj,dict) or not isinstance(obj.get('env'),dict):
        raise ValueError('Claude settings missing env object')
    obj['env']['CLAUDE_CODE_AUTO_COMPACT_WINDOW']=str(budget)
    if read_hook:
        if not Path(read_hook).is_file():raise ValueError('adaptive read hook missing')
        # Hook denies only unexpected large whole-file reads; it never approves
        # tools, changes permissions, or modifies existing hook definitions.
        obj.setdefault('hooks',{}).setdefault('PreToolUse',[]).append({
            'matcher':'Read',
            'hooks':[{'type':'command','command':'python3 '+str(Path(read_hook)),'timeout':5}]
        })
    Path(destination).write_text(json.dumps(obj))

if __name__=='__main__':
    if len(sys.argv) in (5,6) and sys.argv[1]=='--patch-settings':
        try:
            patch_settings(sys.argv[2],sys.argv[3],int(sys.argv[4]),sys.argv[5] if len(sys.argv)==6 else None);sys.exit(0)
        except (ValueError,OSError) as exc:
            print('claudex native efficiency: '+str(exc),file=sys.stderr);sys.exit(2)
    try:print(window())
    except ValueError as exc:
        print('claudex native efficiency: '+str(exc),file=sys.stderr)
        sys.exit(2)
