#!/usr/bin/env python3
"""Aggregate real Claude Code stream-json usage without retaining text.

No synthetic cost savings, billing guesses, prompts or tool outputs.
Pass captures of the same tasks under different budgets for comparison.
"""
import argparse
import json
from pathlib import Path

FIELDS = ('input_tokens', 'output_tokens', 'cache_creation_input_tokens',
          'cache_read_input_tokens')


def analyze(path):
    messages = {}
    compact_events = 0
    with Path(path).open(encoding='utf-8') as stream:
        for index, line in enumerate(stream):
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get('type') == 'system' and event.get('subtype') == 'compact_boundary':
                compact_events += 1
            if event.get('type') != 'assistant':
                continue
            message = event.get('message')
            if not isinstance(message, dict):
                continue
            usage = message.get('usage')
            if not isinstance(usage, dict) or not any(field in usage for field in FIELDS):
                continue
            key = message.get('id')
            if not isinstance(key, str) or not key:
                key = f'line_{index}'  # No id: cannot reliably deduplicate.
            values = {}
            for field in FIELDS:
                value = usage.get(field)
                if value is not None and (type(value) is not int or value < 0):
                    raise ValueError(f'invalid {field} on line {index + 1}')
                values[field] = value
            messages[key] = values

    totals = {field: sum(v[field] or 0 for v in messages.values())
              for field in FIELDS}
    known = {field: sum(v[field] is not None for v in messages.values())
             for field in FIELDS}
    return {
        'assistant_messages_with_usage': len(messages),
        'compact_boundaries': compact_events,
        'reported_usage': {field: {
            'tokens': totals[field],
            'messages_reporting': known[field],
        } for field in FIELDS},
        'cache_metrics_complete': (
            len(messages) > 0
            and known['cache_read_input_tokens'] == len(messages)
            and known['cache_creation_input_tokens'] == len(messages)
        ),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('traces', nargs='+', help='label=path/to/stream-json.jsonl')
    opts = p.parse_args()
    results = {}
    for pair in opts.traces:
        label, sep, path = pair.partition('=')
        if not sep or not label or not path or label in results:
            p.error('each trace must be a distinct label=path')
        results[label] = analyze(path)
    print(json.dumps({
        'results': results,
        'note': 'Observed token counters only, not provider invoices, '
                'cache TTL evidence, coding-quality scores, or savings claims.',
    }, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
