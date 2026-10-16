#!/usr/bin/env python3
"""Deterministic adaptive session policy. No agent and no implicit dispatch.

An embedding owner supplies authoritative activity, cache lifetime and a
verified compact callback. Without those three properties, fail closed.
"""
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class Session:
    session_id: str
    now: float
    last_model_request: float
    cache_ttl_seconds: Optional[float]
    context_tokens: int
    active_turn: bool
    active_tool_calls: int
    awaiting_user: bool
    last_user_message: float
    pending_approval: bool = False
    compaction_running: bool = False
    last_compaction: Optional[float] = None
    owner_verified: bool = False

@dataclass(frozen=True)
class Policy:
    min_context_tokens: int = 64000
    safety_seconds: float = 60
    min_quiet_seconds: float = 30
    min_compaction_gap_seconds: float = 1200


def eligible(session: Session, policy=Policy()):
    if not session.owner_verified or not session.session_id:
        return 'unverified_session_owner'
    if session.cache_ttl_seconds is None or session.cache_ttl_seconds <= policy.safety_seconds:
        return 'cache_lifetime_unknown'
    if session.active_turn or session.active_tool_calls or session.compaction_running:
        return 'active_work'
    if session.awaiting_user or session.pending_approval:
        return 'human_boundary'
    if session.context_tokens < policy.min_context_tokens:
        return 'small_context'
    if session.now - session.last_user_message < policy.min_quiet_seconds:
        return 'recent_user_message'
    if session.now - session.last_model_request < policy.min_quiet_seconds:
        return 'recent_model_request'
    if session.last_compaction is not None and session.now - session.last_compaction < policy.min_compaction_gap_seconds:
        return 'recent_compaction'
    until_expiration = session.last_model_request + session.cache_ttl_seconds - session.now
    if until_expiration < 0:
        return 'cache_already_expired'
    if until_expiration > policy.safety_seconds:
        return 'too_early'
    return 'ready'


def dispatch_if_safe(session, callback, policy=Policy()):
    """Must run under an OWNER-PROVIDED per-session lock and recheck freshness.

    Do not wire to a timer before the owner can prove atomic check/dispatch,
    distinguish user-origin messages, and verify a supported compact command.
    """
    reason=eligible(session,policy)
    if reason!='ready':return reason
    if callback is None: return 'no_verified_dispatch'
    return 'dispatched' if callback(session.session_id) else 'dispatch_rejected'
