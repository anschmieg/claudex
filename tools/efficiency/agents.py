#!/usr/bin/env python3
"""Session-only native --agents overrides for *unchanged Claudex-owned* agents.

Never rewrite ~/.claude/agents or override customized/user-owned definitions.
The feature requires Claude Code >=2.1.296, which added autoCompactWindow
to --agents definitions. Caller must avoid a conflicting user --agents flag.
"""
import argparse
import json
from pathlib import Path
import re
import sys

MIN_VERSION = (2, 1, 296)
NAMES = (
    'gpt-fast', 'gpt-fast-deep', 'gpt-core', 'gpt-core-deep', 'gpt-expert',
)
FIELDS = {'name', 'description', 'model', 'effort'}


def client_supported(version):
    match = re.match(r'^\s*(\d+)\.(\d+)\.(\d+)\b', version)
    return bool(match and tuple(map(int, match.groups())) >= MIN_VERSION)


def parse_owned(source, reference, name):
    """Only parse the small, known Claudex-generated frontmatter subset."""
    if source.is_symlink() or reference.is_symlink():
        return None
    if not source.is_file() or not reference.is_file():
        return None
    data = source.read_bytes()
    if len(data) > 32768 or data != reference.read_bytes():
        return None
    text = data.decode('utf-8')
    if not text.startswith('---\n') or '\n---\n' not in text[4:]:
        return None
    header, prompt = text[4:].split('\n---\n', 1)
    fields = {}
    for line in header.splitlines():
        key, sep, value = line.partition(': ')
        if not sep or key not in FIELDS or key in fields or not value:
            return None
        fields[key] = value
    if fields.get('name') != name or not fields.get('description') or not prompt.strip():
        return None
    return {k: v for k, v in fields.items() if k != 'name'} | {'prompt': prompt.strip()}


def project_agent_exists(name, directory):
    # A project's agent definition must keep precedence over a CLI override.
    directory = Path(directory).resolve()
    for base in (directory, *directory.parents):
        # The home agents directory is already checked against Claudex
        # ownership references; do not traverse into that private directory.
        if base == Path.home():
            break
        try:
            if (base / '.claude' / 'agents' / f'{name}.md').exists():
                return True
        except OSError:
            return True  # Cannot prove absence: preserve project agent.

    return False


def definitions(agent_dir, owned_dir, worker_budget, coordinator_budget, version,
                project_dir=None):
    if not client_supported(version):
        return {}
    if type(worker_budget) is not int or not 100000 <= worker_budget <= 1000000:
        raise ValueError('worker budget must be 100000–1000000 tokens')
    if type(coordinator_budget) is not int or not 100000 <= coordinator_budget <= 1000000:
        raise ValueError('coordinator budget must be 100000–1000000 tokens')
    # Subagent threshold may be lower than coordinator, never higher.
    if worker_budget > coordinator_budget:
        raise ValueError('worker budget cannot exceed coordinator budget')
    result = {}
    for name in NAMES:
        if project_agent_exists(name, project_dir or Path.cwd()):
            continue
        spec = parse_owned(Path(agent_dir) / f'{name}.md',
                           Path(owned_dir) / f'{name}.md', name)
        if spec is not None:
            spec['autoCompactWindow'] = worker_budget
            result[name] = spec
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('agent_dir')
    parser.add_argument('owned_dir')
    parser.add_argument('coordinator_tokens', type=int)
    parser.add_argument('client_version')
    parser.add_argument('--worker-tokens', type=int, default=None)
    opts = parser.parse_args()
    if not client_supported(opts.client_version):
        print('Claudex: per-worker native compaction requires Claude Code >=2.1.296; '
              'preserving existing worker behavior', file=sys.stderr)
        return 0
    try:
        worker = opts.worker_tokens
        if worker is None:
            worker = min(192000, opts.coordinator_tokens)
        agents = definitions(opts.agent_dir, opts.owned_dir, worker,
                             opts.coordinator_tokens, opts.client_version)
        if agents:
            print(json.dumps(agents, separators=(',', ':')))
    except (OSError, UnicodeError, ValueError) as exc:
        print('Claudex worker budget: ' + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
