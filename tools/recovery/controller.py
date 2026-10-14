#!/usr/bin/env python3
"""Durable Claudex/T3 turn recovery. No Claude cron, no T3 DB writes.

The independent systemd timer invokes this once per minute. Only explicitly
enrolled ClaudeAgent/Claudex threads qualify. Intent is written durably before
the idempotent T3 RPC dispatch; retries retain the same command/message UUID.
No replays of external writes or unapproved actions are performed here.
"""
from __future__ import annotations
import argparse
import asyncio
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import uuid

BASE = Path(os.environ.get("CLAUDEX_RECOVERY_HOME", str(Path.home()/".local/state/claudex-recovery")))
T3_DB = Path(os.environ.get("CLAUDEX_T3_DB", str(Path.home()/".t3/userdata/state.sqlite")))
def find_t3_cli():
    configured=os.environ.get("CLAUDEX_T3_CLI")
    if configured:return Path(configured)
    home=Path.home()
    for preferred in (home/".local/bin/t3",home/".t3/bin/t3"):
        if preferred.is_file() and os.access(preferred,os.X_OK):return preferred
    root=home/".t3/runtime/versions"
    if root.is_dir():
        candidates=[p/"t3" for p in root.iterdir() if p.is_dir() and
                    (p/".install-complete").is_file() and (p/"t3").is_file()]
        candidates.sort(key=lambda p:tuple(int(n) for n in re.findall(r"\d+",p.parent.name)),reverse=True)
        if candidates:return candidates[0]
    return Path("t3")

T3_CLI = find_t3_cli()
ORIGIN = os.environ.get("CLAUDEX_T3_ORIGIN", "http://127.0.0.1:3773")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SCHEMA = 1
MAX_ATTEMPTS_PER_CHAIN = 2
MIN_SETTLE_SECONDS = 30
RETRY_WAIT_SECONDS = (30,120)
MAX_ERROR_AGE = 86400
MIN_CONCURRENT_QUIET_SECONDS = 30
STALE_TURN_SECONDS = 900
STALE_ACTIVITY_SECONDS = 180

RECOVERY_TEXT = (
    "Recover the unfinished work from the previous transport/runtime failure. "
    "Resume from the existing thread context and verified files, not from scratch. "
    "First reconcile uncertain operations read-only: NEVER repeat an external write, "
    "sudo change, browser mutation, payment or pending grant if its outcome is ambiguous. "
    "Honor existing approval and permission decisions; no privilege escalation. "
    "Complete independent safe tasks and verification, but if explicit human approval "
    "is required, state the exact blocker and stop. Do NOT create recurring CronCreate, "
    "ScheduleWakeup or polling loops. Do not claim the original task complete "
    "without evidence. This is a one-time automated crash recovery, not a new goal."
)

def timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")

def parse_time(value):
    if not value: return None
    try: return dt.datetime.fromisoformat(value.replace("Z","+00:00"))
    except (ValueError,TypeError): return None

def age_seconds(value, now):
    instant=parse_time(value)
    return (now-instant).total_seconds() if instant else None

def emit(kind, **fields):
    # Deliberately no free-text exceptions, prompts, journal data, IDs of sessions, or tokens.
    print(json.dumps({"at":timestamp(),"event":kind,**fields},sort_keys=True),flush=True)

def strict_directory(path):
    if path.is_symlink():raise RuntimeError("symlink state directory")
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    os.chmod(path,0o700)
    if path.stat().st_uid!=os.geteuid():raise RuntimeError("wrong state owner")

def atomic_json(path, obj):
    data=(json.dumps(obj,sort_keys=True,indent=2)+"\n").encode()
    import tempfile
    fd, tmp=tempfile.mkstemp(prefix=".pending-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600)
        os.replace(tmp,path)
        fd_dir=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd_dir)
        finally:os.close(fd_dir)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def read_json(path, fallback):
    if not path.exists():return fallback
    if path.is_symlink():raise RuntimeError("symlink file refused")
    if path.stat().st_size>128000:raise RuntimeError("oversized state")
    return json.loads(path.read_text())

def deterministic_id(namespace, thread, failed_turn, chain_index):
    raw=("claudex-durable-v1:"+namespace+":"+thread+":"+failed_turn+":"+str(chain_index)).encode()
    return str(uuid.UUID(bytes=hashlib.sha256(raw).digest()[:16],version=4))

def classify_error(message):
    text=(message or "").lower()
    permanent=("permission denied","requires approval","approval required","unauthorized scope",
        "401 unauthorized","http 401","http 403","forbidden","invalid credentials",
        "invalid api key","insufficient_quota","billing","invalid request","bad request",
        "maximum retries","cancelled by user","user interrupted","permission blocked",
        "security policy","rate limit exhausted")
    if any(term in text for term in permanent):
        return "blocked"
    retryable=("http 429","429 too many","rate limit","http 500","http 502","http 503",
        "http 504","server error","gateway error","service unavailable","stream failed",
        "runtime stream failed","repeated api errors","connection reset","connection refused",
        "connection closed","network error","socket hang up","timeout","timed out",
        "econnreset","econnrefused","eai_again","fetch failed","upstream error")
    if any(term in text for term in retryable):
        return "transient"
    return "unknown"

def db_connect(path=None):
    if path is None: path=T3_DB
    uri="file:"+str(path)+"?mode=ro"
    c=sqlite3.connect(uri,uri=True,timeout=4)
    c.row_factory=sqlite3.Row
    c.execute("PRAGMA query_only=ON")
    c.execute("PRAGMA busy_timeout=2500")
    return c

def inspect_thread(c, thread_id):
    row=c.execute("""SELECT t.turn_id, t.state, t.requested_at, t.started_at, t.completed_at,
      s.provider_name,s.provider_instance_id,s.status AS session_status,s.last_error,
      p.project_id,p.archived_at,p.deleted_at,p.pending_approval_count,
      p.pending_user_input_count,p.runtime_mode,p.interaction_mode,
      p.latest_user_message_at
      FROM projection_turns t
      JOIN projection_thread_sessions s ON s.thread_id=t.thread_id
      JOIN projection_threads p ON p.thread_id=t.thread_id
      WHERE t.thread_id=? ORDER BY t.requested_at DESC LIMIT 1""",(thread_id,)).fetchone()
    if not row:return None
    info=dict(row)
    info["pending_approval_count"]=info["pending_approval_count"] or 0
    info["pending_user_input_count"]=info["pending_user_input_count"] or 0
    events=c.execute("""SELECT kind,created_at,payload_json FROM projection_thread_activities
       WHERE thread_id=? AND (turn_id=? OR turn_id IS NULL)
       AND created_at>=? AND kind IN
       ('runtime.error','provider.turn.start.failed','runtime.warning')
       ORDER BY created_at DESC LIMIT 12""",(thread_id,info["turn_id"],info["started_at"] or info["requested_at"])).fetchall()
    texts=[]
    for event in events:
        if event["kind"]=="runtime.warning":continue
        try:
            data=json.loads(event["payload_json"] or "{}")
        except (ValueError,TypeError):continue
        for key in ("message","error","reason","detail"):
            val=data.get(key) if isinstance(data,dict) else None
            if isinstance(val,str):texts.append(val[:1024])
    if info["last_error"]:texts.append(str(info["last_error"])[:1024])
    info["error_class"]=next((kind for text in texts if (kind:=classify_error(text))!="unknown"),"unknown")
    info["interrupted"]=bool(c.execute("""SELECT 1 FROM orchestration_events
      WHERE stream_id=? AND event_type='thread.turn-interrupt-requested'
      AND occurred_at>=? LIMIT 1""",(thread_id,info["requested_at"] or "")).fetchone())
    activity=c.execute("SELECT max(created_at) FROM projection_thread_activities WHERE thread_id=?",(thread_id,)).fetchone()
    info["last_activity_at"]=activity[0] if activity else None
    receipt=None
    return info

def has_newer_user_message(c,thread_id,after):
    return bool(c.execute("""SELECT 1 FROM projection_thread_messages
      WHERE thread_id=? AND role='user' AND created_at>? LIMIT 1""",(thread_id,after)).fetchone())

def accepted_receipt(c,command_id):
    row=c.execute("""SELECT status FROM orchestration_command_receipts WHERE command_id=?""",(command_id,)).fetchone()
    return row["status"] if row else None

def message_exists(c,message_id):
    return bool(c.execute("SELECT 1 FROM projection_thread_messages WHERE message_id=? LIMIT 1",(message_id,)).fetchone())

def no_live_claudex_lease():
    """Conservative negative evidence: no Claudex active-session lease anywhere for this user."""
    session_dir=Path.home()/".local/state/claudex/sessions"
    if not session_dir.is_dir() or session_dir.is_symlink():return False
    try:return not any(path.is_file() for path in session_dir.iterdir())
    except OSError:return False


def orphaned_turn(info, now):
    """Require stopped provider, long age and inactivity AND no active Claude lease.

    A stalled but live agent is NOT orphaned. We never kill or interrupt an
    existing turn. False negatives are preferable to duplicate tool writes.
    """
    if not info or info["state"] not in ("running","starting","pending"):return False
    if info.get("session_status") not in ("stopped","error","failed"):return False
    started=age_seconds(info.get("started_at") or info.get("requested_at"),now)
    last_activity=age_seconds(info.get("last_activity_at"),now)
    if started is None or started<STALE_TURN_SECONDS:return False
    if last_activity is None or last_activity<STALE_ACTIVITY_SECONDS:return False
    return no_live_claudex_lease()


def safe_snapshot(info, goal, now):
    if not info:return "missing"
    if info["provider_name"]!="claudeAgent" or info["provider_instance_id"]!="claudex":return "other_provider"
    if info["project_id"]!=goal["project_id"]:return "project_mismatch"
    if info["archived_at"] or info["deleted_at"]:return "archived"
    if info["pending_approval_count"] or info["pending_user_input_count"]:return "awaiting_human"
    if info["interrupted"]:return "user_interrupt"
    if info["runtime_mode"] in ("danger-full-access","bypassPermissions"):return "unsafe_runtime"
    # Treat a live turn as active even if it appears temporarily stuck.
    if info["state"] in ("running","pending","requested","starting"):
        return "recoverable" if orphaned_turn(info,now) else "active_turn"
    if info["state"]=="completed":return "completed"
    if info["state"] not in ("error","failed"):return "unknown_turn"
    if info["error_class"]!="transient" and not orphaned_turn(info,now):return "not_transient"
    elapsed=age_seconds(info["completed_at"] or info["requested_at"],now)
    if elapsed is None or elapsed<MIN_SETTLE_SECONDS:return "settling"
    if elapsed>MAX_ERROR_AGE:return "old_error"
    if info["requested_at"]<goal["enrolled_at"]:return "pre_enrollment"
    return "recoverable"

def make_intent(thread, turn, n):
    return {"failed_turn_id":turn,"attempt":n,
        "command_id":deterministic_id("cmd",thread,turn,n),
        "message_id":deterministic_id("msg",thread,turn,n),
        "state":"prepared","prepared_at":timestamp(),"send_attempts":0}

def choose_action(c,goal,state,now):
    """Pure decision from project-owned state and authoritative T3 projections."""
    info=inspect_thread(c,goal["thread_id"])
    status=safe_snapshot(info,goal,now)
    active=state.get("intent")
    if not active and info and state.get("last_dispatched_failed_turn")==info["turn_id"]:
        return "already_dispatched",info
    if active:
        receipt=accepted_receipt(c,active["command_id"])
        if receipt:
            if receipt not in ("accepted","applied","completed","success"):
                return "blocked_receipt", info
            return "already_accepted",info
        if message_exists(c,active["message_id"]):
            return "already_accepted",info
        # Never resend an ambiguous command if the original errored turn has
        # been superseded, or if someone resumed the conversation themselves.
        if not info or info["turn_id"]!=active["failed_turn_id"]:
            return "superseded",info
        if status!="recoverable":return status,info
        if has_newer_user_message(c,goal["thread_id"],active["prepared_at"]):
            return "human_superseded",info
        if active.get("send_attempts",0)>=3:return "transport_ambiguous",info
        return "resend_same_id",info
    if status!="recoverable":return status,info
    if has_newer_user_message(c,goal["thread_id"],info["completed_at"] or info["requested_at"]):
        return "human_superseded",info
    if state.get("attempts",0)>=MAX_ATTEMPTS_PER_CHAIN:return "retry_budget_exhausted",info
    if state.get("root_turn_id") and state.get("latest_error_turn")!=info["turn_id"]:
        # This is a later error; maintain the root's retry budget, don't reset.
        pass
    if state.get("next_eligible_at"):
        next_time=parse_time(state["next_eligible_at"])
        if next_time and now<next_time:return "backoff",info
    return "prepare",info

def issue_token():
    # Short-lived, never logged or written; t3 signs the local session.
    proc=subprocess.run([str(T3_CLI),"auth","session","issue","--ttl","2m",
         "--label","Claudex recovery controller","--token-only"],
         cwd=str(Path.home()),capture_output=True,text=True,timeout=12)
    token=proc.stdout.strip()
    if proc.returncode or not (16<=len(token)<=10000) or any(c.isspace() for c in token):
        raise RuntimeError("auth issuance unavailable")
    return token

def validated_loopback_origin(origin):
    try:
        u=urllib.parse.urlsplit(origin)
        if (u.scheme!="http" or u.hostname!="127.0.0.1" or u.port is None
            or u.username is not None or u.password is not None or u.path not in ("", "/")
            or u.query or u.fragment):
            raise ValueError("invalid loopback T3 origin")
        return "http://127.0.0.1:"+str(u.port)
    except (TypeError,ValueError):
        raise ValueError("T3 origin must be bare http://127.0.0.1:<port>") from None

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise RuntimeError("T3 local API redirect refused")

def t3_http_health(token,origin=ORIGIN):
    url=validated_loopback_origin(origin)+"/api/orchestration/shell"
    req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,"Accept":"application/json"})
    opener=urllib.request.build_opener(NoRedirect)
    with opener.open(req,timeout=6) as response:
        result=json.load(response)
    if not isinstance(result,dict):raise RuntimeError("invalid T3 shell")
    return result

async def t3_dispatch(token,cmd,origin=ORIGIN):
    origin=validated_loopback_origin(origin)
    import websockets
    ws_url=origin.replace("http://","ws://")+"/ws?clientSurface=web&connectionMethod=direct"
    async with websockets.connect(ws_url,additional_headers={"Authorization":"Bearer "+token},
            open_timeout=6,close_timeout=3,max_size=2_000_000) as ws:
        await ws.send(json.dumps({"_tag":"Request","id":"1","tag":"orchestration.dispatchCommand",
                                  "payload":cmd,"headers":[]}))
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            msg=json.loads(await asyncio.wait_for(ws.recv(),timeout=max(0.2,deadline-time.monotonic())))
            entries=msg if isinstance(msg,list) else [msg]
            for event in entries:
                if event.get("_tag")=="Chunk":
                    await ws.send(json.dumps({"_tag":"Ack","requestId":event.get("requestId")}))
                if event.get("_tag")=="Exit" and str(event.get("requestId"))=="1":
                    exitval=event.get("exit") or {}
                    if exitval.get("_tag")!="Success":raise RuntimeError("T3 dispatch rejected")
                    return "accepted"
        raise TimeoutError("T3 RPC timeout")

def dispatch_intent(goal,intent,token):
    command={"type":"thread.turn.start","commandId":intent["command_id"],"threadId":goal["thread_id"],
        "message":{"messageId":intent["message_id"],"role":"user","text":RECOVERY_TEXT,"attachments":[]},
        "runtimeMode":goal["runtime_mode"],"interactionMode":goal["interaction_mode"],
        "createdAt":intent["prepared_at"]}
    return asyncio.run(t3_dispatch(token,command))

def process(config,ledger,c,now,live):
    result=[]
    for goal in config["goals"]:
        thread=goal["thread_id"]
        state=ledger.setdefault("threads",{}).setdefault(thread,{"attempts":0,"intent":None,"root_turn_id":None})
        action,info=choose_action(c,goal,state,now)
        if action=="prepare":
            if state["root_turn_id"] is None:state["root_turn_id"]=info["turn_id"]
            state["intent"]=make_intent(thread,info["turn_id"],state["attempts"]+1)
            state["latest_error_turn"]=info["turn_id"]
            action="send_prepared"
        if action in ("already_accepted","superseded","completed","human_superseded","blocked_receipt"):
            if state.get("intent"):
                if action=="already_accepted":
                    state["attempts"]=max(state.get("attempts",0),state["intent"]["attempt"])
                state["last_intent"]=state["intent"]["command_id"]
                state["intent"]=None
                if action=="already_accepted":
                    # Remain idle until T3 creates a new turn, even if its read
                    # projection briefly continues showing the same failed turn.
                    state["last_dispatched_failed_turn"]=info["turn_id"] if info else None
                elif action=="completed":
                    state.update({"attempts":0,"root_turn_id":None,"latest_error_turn":None})
        if action=="prepare" or action=="send_prepared" or action=="resend_same_id":
            if not live:
                action="dry_run"
            else:
                intent=state["intent"]
                # Reserve the intent in the ledger BEFORE touching T3. Caller
                # performs the durable fsync prior to executing the dispatch.
                result.append((thread,action,intent))
                action="prepared_to_dispatch"
        if action in ("not_transient","awaiting_human","blocked_receipt","retry_budget_exhausted","user_interrupt"):
            # This is a real block, not an invitation to send recurring checks.
            state["last_block"]=action
        if info and info.get("state")=="completed" and state.get("intent") is None:
            state["root_turn_id"]=None
            state["attempts"]=0
        old_action=state.get("last_action")
        state["last_action"]=action
        if state.get("last_dispatched_failed_turn") and info and info["turn_id"]==state["last_dispatched_failed_turn"]:
            result=[r for r in result if r[0]!=thread]
        if state.get("last_dispatched_failed_turn") and info and info["turn_id"]!=state["last_dispatched_failed_turn"]:
            state["last_dispatched_failed_turn"]=None
        if old_action!=action:
            emit("state_changed",thread_suffix=thread[-8:],status=action)
    return result

def run_once(live=False):
    strict_directory(BASE)
    lock_path=BASE/"lock"
    with open(lock_path,"a+") as file:
        try:fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            emit("busy");return 0
        config=read_json(BASE/"config.json",{"version":1,"enabled":False,"goals":[]})
        if config.get("version")!=SCHEMA or not isinstance(config.get("goals"),list):
            raise RuntimeError("invalid config")
        if not config.get("enabled") or (BASE/"pause").exists():
            emit("paused");return 0
        seen=set()
        for goal in config["goals"]:
            if set(goal)!= {"thread_id","project_id","enrolled_at","runtime_mode","interaction_mode"}:
                raise RuntimeError("unsupported goal fields")
            if not UUID.fullmatch(goal["thread_id"]) or not UUID.fullmatch(goal["project_id"]):
                raise RuntimeError("invalid goal ID")
            if goal["thread_id"] in seen:raise RuntimeError("duplicate goal")
            seen.add(goal["thread_id"])
            if goal["runtime_mode"] not in ("approval-required","approvalRequired","default","workspace-write","workspaceWrite","full-access"):
                raise RuntimeError("unsupported runtime mode")
            if goal["interaction_mode"] not in ("default","code","plan"):
                raise RuntimeError("unsupported interaction mode")
        ledger=read_json(BASE/"ledger.json",{"version":1,"threads":{}})
        if ledger.get("version")!=SCHEMA:raise RuntimeError("ledger version")
        original=json.dumps(ledger,sort_keys=True)
        now=dt.datetime.now(dt.timezone.utc)
        with db_connect() as c:
            dispatches=process(config,ledger,c,now,live)
        if not live:
            # Dry-run shows what would happen without creating an actual intent
            # or changing the persisted retry budget.
            return 0
        if json.dumps(ledger,sort_keys=True)!=original:
            atomic_json(BASE/"ledger.json",ledger)
        for thread,action,intent in dispatches:
            state=ledger["threads"][thread]
            goal=next(g for g in config["goals"] if g["thread_id"]==thread)
            # One auth and send only when a genuinely failed turn is eligible.
            try:
                token=issue_token()
                t3_http_health(token)
                # A 2nd DB snapshot narrows the race with a new human turn.
                with db_connect() as c:
                    info=inspect_thread(c,thread)
                    if not info or info["turn_id"]!=intent["failed_turn_id"] or (
                            safe_snapshot(info,goal,dt.datetime.now(dt.timezone.utc))!="recoverable"):
                        emit("dispatch_skipped_superseded",thread_suffix=thread[-8:])
                        state["intent"]=None
                        atomic_json(BASE/"ledger.json",ledger)
                        continue
                    if has_newer_user_message(c,thread,intent["prepared_at"]):
                        emit("dispatch_skipped_human",thread_suffix=thread[-8:])
                        state["intent"]=None
                        atomic_json(BASE/"ledger.json",ledger)
                        continue
                intent["send_attempts"]=intent.get("send_attempts",0)+1
                intent["last_send_at"]=timestamp()
                atomic_json(BASE/"ledger.json",ledger)
                dispatch_intent(goal,intent,token)
                state["attempts"]=state.get("attempts",0)+1
                state["last_dispatched_failed_turn"]=intent["failed_turn_id"]
                state["last_dispatch_at"]=timestamp()
                state["intent"]=None
                atomic_json(BASE/"ledger.json",ledger)
                emit("resumed_once",thread_suffix=thread[-8:],attempt=state["attempts"])
            except Exception as error:
                # An API timeout is ambiguous. Keep EXACT SAME ID for next
                # retry, never start a new independent turn from that failure.
                emit("dispatch_deferred",thread_suffix=thread[-8:],
                     error_type=type(error).__name__)
                state["next_eligible_at"]=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=RETRY_WAIT_SECONDS[0])).isoformat()
                atomic_json(BASE/"ledger.json",ledger)
        return 0

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--once",action="store_true")
    ap.add_argument("--live",action="store_true")
    ap.add_argument("--status",action="store_true")
    ap.add_argument("--probe-auth",action="store_true")
    ap.add_argument("--enroll-thread",default=None)
    opts=ap.parse_args()
    if opts.probe_auth:
        try:
            token=issue_token()
            snap=t3_http_health(token)
            emit("authenticated_read_pass",schema="dict" if isinstance(snap,dict) else "unknown")
            return 0
        except Exception as exc:
            emit("authenticated_read_failed",error_type=type(exc).__name__)
            return 2
    if opts.enroll_thread:
        try:
            tid=opts.enroll_thread
            if not UUID.fullmatch(tid):raise RuntimeError("invalid thread")
            strict_directory(BASE)
            config_path=BASE/"config.json"
            if config_path.exists():raise RuntimeError("existing config, enrollment requires review")
            with db_connect() as c:
                r=c.execute("""SELECT s.provider_name,s.provider_instance_id,t.project_id,
                   t.runtime_mode,t.interaction_mode FROM projection_thread_sessions s
                   JOIN projection_threads t ON t.thread_id=s.thread_id WHERE s.thread_id=?""",(tid,)).fetchone()
                if not r or r["provider_name"]!="claudeAgent" or r["provider_instance_id"]!="claudex":
                    raise RuntimeError("not a Claudex thread")
                goal={"thread_id":tid,"project_id":r["project_id"],"enrolled_at":timestamp(),
                   "runtime_mode":r["runtime_mode"],"interaction_mode":r["interaction_mode"]}
            if goal["runtime_mode"] not in ("approval-required","approvalRequired","default",
                 "workspace-write","workspaceWrite","full-access"):
                 raise RuntimeError("runtime mode not validated")
            if goal["interaction_mode"] not in ("default","code","plan"):
                 raise RuntimeError("interaction mode not validated")
            atomic_json(config_path,{"version":1,"enabled":True,"goals":[goal]})
            emit("thread_enrolled",thread_suffix=tid[-8:],trigger="new_transient_errors_only")
            return 0
        except Exception as exc:
            emit("enrollment_failed",error_type=type(exc).__name__)
            return 2
    if opts.status:
        cfg=read_json(BASE/"config.json",{})
        ledger=read_json(BASE/"ledger.json",{})
        emit("status",enabled=bool(cfg.get("enabled")),goal_count=len(cfg.get("goals",[])),
             tracked_count=len(ledger.get("threads",{})),paused=(BASE/"pause").exists())
        return
    try:
        return run_once(live=opts.live)
    except Exception as exc:
        emit("controller_failed",error_type=type(exc).__name__)
        return 2

if __name__=="__main__":
    sys.exit(main() or 0)
