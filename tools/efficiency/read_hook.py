#!/usr/bin/env python3
"""Opt-in Read preflight: bound oversized single-tool returns without approvals.

PreToolUse may deny a too-large read and request a bounded range. It cannot
alter the running Claude Code compaction window. No payload/file text logged.
"""
import json, os, sys
from pathlib import Path

MAX_INPUT_BYTES=100000

def evaluate(event,limit_bytes=160000):
    if event.get('hook_event_name')!='PreToolUse' or event.get('tool_name')!='Read':
        return None
    payload=event.get('tool_input')
    if not isinstance(payload,dict):return None
    raw=payload.get('file_path')
    if not isinstance(raw,str) or not raw or '\x00' in raw:return None
    path=Path(raw)
    try:
        stat=path.stat()
        if not path.is_file():return None
    except OSError:return None
    if stat.st_size<=limit_bytes:return None
    if isinstance(payload.get('limit'),int) and 0<payload['limit']<=150:
        return None  # Existing range is explicit; no automatic interference.
    return {'hookSpecificOutput':{
        'hookEventName':'PreToolUse',
        'permissionDecision':'deny',
        'permissionDecisionReason':(
            'Adaptive Claudex: this file is large. Read at most 150 lines '
            'using Read(offset=..., limit=150), focusing on relevant ranges. '
            'The current Claude Code context window cannot be expanded mid-turn.')}}

def main():
    if os.getenv('CLAUDEX_EFFICIENCY')!='adaptive':return 0
    try:
        data=sys.stdin.read(MAX_INPUT_BYTES+1)
        if len(data)>MAX_INPUT_BYTES:return 0
        event=json.loads(data)
        result=evaluate(event)
        if result:print(json.dumps(result))
    except (ValueError,TypeError,OSError):pass
    return 0

if __name__=='__main__':sys.exit(main())
