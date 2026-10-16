#!/usr/bin/env python3
"""Opt-in native Claude Code compaction budgets; never edit conversation history.

A tier is a compaction *budget*, not a claim that Claude Code advertises a
256K/512K model window. Current Claude Code only recognizes the [1m] context
suffix. Its auto-compact env setting supports 100K–1M tokens.
"""
import json
import os
import sys
from pathlib import Path

DEFAULT = 272000  # Preserve non-adaptive behavior exactly.
MINIMUM = 100000
MAXIMUM = 1000000
# Leave 25% of the *nominal tier* for tools/reasoning; experimentally tune later.
TIERS = {'small': 192000, 'medium': 384000, 'large': 768000}


def _tokens(value, name):
    if not isinstance(value, str) or not value.isdecimal():
        raise ValueError(name + ' must be a decimal integer')
    number = int(value)
    if not MINIMUM <= number <= MAXIMUM:
        raise ValueError(name + ' must be between 100000 and 1000000')
    return number


def window(env=None):
    env = os.environ if env is None else env
    if env.get('CLAUDEX_EFFICIENCY', 'off') != 'adaptive':
        return DEFAULT
    tier = env.get('CLAUDEX_EFFICIENCY_CONTEXT_TIER', 'medium').lower()
    if tier not in TIERS:
        raise ValueError('context tier must be small, medium or large')
    target = TIERS[tier]
    if 'CLAUDEX_EFFICIENCY_TARGET_TOKENS' in env:
        target = _tokens(env['CLAUDEX_EFFICIENCY_TARGET_TOKENS'], 'target')
    expand = env.get('CLAUDEX_EFFICIENCY_LARGE_READ', '0')
    if expand not in ('0', '1'):
        raise ValueError('large-read override must be 0 or 1')
    if expand == '1':
        requested = _tokens(
            env.get('CLAUDEX_EFFICIENCY_LARGE_READ_TOKENS', str(TIERS['large'])),
            'large-read budget',
        )
        target = max(target, requested)
    return target


def patch_settings(source, destination, budget, read_hook=None):
    src = Path(source)
    obj = json.loads(src.read_text())
    if not isinstance(obj, dict) or not isinstance(obj.get('env'), dict):
        raise ValueError('Claude settings missing env object')
    _tokens(str(budget), 'budget')
    obj['env']['CLAUDE_CODE_AUTO_COMPACT_WINDOW'] = str(budget)
    if read_hook:
        hook = Path(read_hook)
        if not hook.is_file():
            raise ValueError('adaptive read hook missing')
        hooks = obj.setdefault('hooks', {})
        if not isinstance(hooks, dict):
            raise ValueError('Claude settings hooks must be an object')
        pre = hooks.setdefault('PreToolUse', [])
        if not isinstance(pre, list):
            raise ValueError('PreToolUse hooks must be an array')
        pre.append({
            'matcher': 'Read',
            'hooks': [{'type': 'command', 'command': 'python3 ' + str(hook), 'timeout': 5}],
        })
    Path(destination).write_text(json.dumps(obj))


if __name__ == '__main__':
    if len(sys.argv) in (5, 6) and sys.argv[1] == '--patch-settings':
        try:
            patch_settings(
                sys.argv[2], sys.argv[3], int(sys.argv[4]),
                sys.argv[5] if len(sys.argv) == 6 else None,
            )
            sys.exit(0)
        except (ValueError, OSError) as exc:
            print('claudex native efficiency: ' + str(exc), file=sys.stderr)
            sys.exit(2)
    try:
        print(window())
    except ValueError as exc:
        print('claudex native efficiency: ' + str(exc), file=sys.stderr)
        sys.exit(2)
