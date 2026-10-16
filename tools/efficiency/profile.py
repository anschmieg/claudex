#!/usr/bin/env python3
"""Opt-in Claudex efficiency preflight. No prompt, session or credential mutations.

Only explicit environment variables enable analysis. JSON summaries never include
prompt contents, tool outputs, file contents or provider tokens.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

DEFAULTS = {
    'session_warn_tokens': 100000,
    'idle_warn_minutes': 60,
    'max_subagents': 4,
    'max_delegate_depth': 1,
    'max_external_calls': 0,
}

def positive(name, default):
    value=os.environ.get('CLAUDEX_EFFICIENCY_'+name.upper(),str(default))
    if not value.isdecimal(): raise ValueError(name+' must be a nonnegative integer')
    number=int(value)
    if number>10000000:raise ValueError(name+' is out of bounds')
    return number

def profile():
    mode=os.environ.get('CLAUDEX_EFFICIENCY','off').lower()
    if mode not in ('off','advisory','strict','adaptive'):
        raise ValueError('CLAUDEX_EFFICIENCY must be off, advisory, strict or adaptive')
    return dict(mode=mode,**{k:positive(k,v) for k,v in DEFAULTS.items()})

def evaluate(config,context_tokens=None,idle_minutes=None,model_switch=False,
             agent_count=None,depth=None,external_calls=None):
    """Strict mode emits policy violations, not unverified proxy enforcement."""
    signals=[]
    def add(name,condition,detail):
        if condition: signals.append({'code':name,'detail':detail})
    if context_tokens is not None:
        add('long_context',context_tokens>=config['session_warn_tokens'],
            'Consider a short durable handoff before resuming; preserve task and approval state.')
    if idle_minutes is not None:
        add('cold_resume',idle_minutes>=config['idle_warn_minutes'] and
            (context_tokens is None or context_tokens>=config['session_warn_tokens']),
            'A cold large session may be costly; compare handoff with keeping its reasoning trail.')
    add('model_switch',model_switch,
        'A model/effort switch may invalidate provider-specific cached context.')
    if agent_count is not None:
        add('subagent_budget',agent_count>config['max_subagents'],
            'Subagent count exceeds the configured plan; reduce fanout or document an exception.')
    if depth is not None:
        add('delegation_depth',depth>config['max_delegate_depth'],
            'Nested delegation may multiply costs.')
    if external_calls is not None:
        add('external_call_budget',external_calls>config['max_external_calls'],
            'External paid calls require separately configured provider-side caps and approval.')
    return signals

def main():
    parser=argparse.ArgumentParser(description='Claudex opt-in token-efficiency diagnostics')
    parser.add_argument('--context-tokens',type=int)
    parser.add_argument('--idle-minutes',type=int)
    parser.add_argument('--model-switch',action='store_true')
    parser.add_argument('--agent-count',type=int)
    parser.add_argument('--delegation-depth',type=int)
    parser.add_argument('--external-calls',type=int)
    parser.add_argument('--json',action='store_true')
    opts=parser.parse_args()
    try:
        conf=profile()
        if conf['mode']=='off':return 0
        metrics=[opts.context_tokens,opts.idle_minutes,opts.agent_count,opts.delegation_depth,opts.external_calls]
        if any(x is not None and x<0 for x in metrics):raise ValueError('metrics cannot be negative')
        signals=evaluate(conf,opts.context_tokens,opts.idle_minutes,opts.model_switch,
                         opts.agent_count,opts.delegation_depth,opts.external_calls)
    except ValueError as exc:
        print('claudex efficiency: '+str(exc),file=sys.stderr)
        return 2
    result={'mode':conf['mode'],'policy':{k:v for k,v in conf.items() if k!='mode'},
            'signals':signals,'note':'Advisory only; no provider spend or subagent enforcement.'}
    if opts.json:print(json.dumps(result,sort_keys=True))
    elif signals:
        for issue in signals:print('claudex efficiency: '+issue['code']+': '+issue['detail'],file=sys.stderr)
    return 0

if __name__=='__main__':sys.exit(main())
