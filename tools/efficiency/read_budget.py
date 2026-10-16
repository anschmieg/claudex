#!/usr/bin/env python3
"""Deterministic read-budget selector for an owning session controller.

Only returns a requested compaction-window target; it cannot retroactively
change running Claude Code's model context or mutate another process's env.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Read:
    tool_name: str
    estimated_tokens: int
    currently_used: int


def target(read,normal=64000,expanded=192000,headroom=12000):
    if not all(isinstance(n,int) and n>=0 for n in
               (read.estimated_tokens,read.currently_used,normal,expanded,headroom)):
        raise ValueError('invalid token estimate')
    if read.tool_name not in ('Read','read_file','files__read','NotebookRead'):
        return normal
    needed=read.currently_used + read.estimated_tokens + headroom
    return expanded if needed>normal else normal
