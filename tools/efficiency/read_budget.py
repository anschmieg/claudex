#!/usr/bin/env python3
"""Offline sizing probe; cannot change a running Claude Code context."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Read:
    tool_name: str
    estimated_tokens: int
    currently_used: int


def target(read, normal=256000, expanded=768000, headroom=32000):
    """Select a *sufficient* launch budget or fail; never promise truncation.

    Returns normal for unrelated tools. This is a planning prototype only:
    it does not override any live session, provider model, or Claude Code cap.
    """
    values = (read.estimated_tokens, read.currently_used,
              normal, expanded, headroom)
    if any(type(n) is not int or n < 0 for n in values):
        raise ValueError('token estimates and budgets must be nonnegative integers')
    if normal < 100000 or expanded < normal or expanded > 1000000:
        raise ValueError('invalid compaction budgets')
    if read.tool_name not in ('Read', 'read_file', 'files__read', 'NotebookRead'):
        return normal
    needed = read.currently_used + read.estimated_tokens + headroom
    if needed <= normal:
        return normal
    if needed <= expanded:
        return expanded
    raise ValueError(
        f'read needs {needed} tokens, exceeding expanded {expanded}; '
        'caller must handle insufficient budget before tool execution'
    )
