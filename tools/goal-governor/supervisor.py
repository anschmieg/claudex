#!/usr/bin/env python3
"""One-shot Goal Governor for T3/Claudex. No modifications to any core runtime."""
from __future__ import annotations
import argparse, asyncio, datetime as dt, fcntl, hashlib, importlib.util, json, os, sys, uuid
from pathlib import Path
import state

RECOVERY=Path(os.environ.get("CLAUDEX_RECOVERY_PY",
   str(Path.home()/".local/share/claudex/recovery/controller.py")))
MAX_PER_HOUR=6
MAX_PER_DAY=24
SETTLE_SECONDS=20
MIN_GAP_SECONDS=90
MAX_TRANSPORT_ATTEMPTS=3
MESSAGE=(
  "Continue the existing approved goal in this T3 thread. Use the goal-governor "
  "plugin to inspect the current goal and its explicit next action. Execute "
  "substantial verified work rather than returning a status report. Before "
  "ending, checkpoint with a different actionable next step, meaningful "
  "progress evidence and a changed workspace artifact. If all acceptance "
  "criteria appear met, propose completion for verification. If genuinely "
  "blocked by approval, ownership or an external condition, record a blocked "
  "state. No /loop, CronCreate, ScheduleWakeup, or recurring LLM polling. "
  "Do not repeat any ambiguous browser, sudo, external API, or protected write "
  "without safe read-only reconciliation; preserve all approval requirements."
)

def adapter():
    if not RECOVERY.is_file() or RECOVERY.is_symlink():
        raise RuntimeError("missing deployed Claudex recovery controller")
    spec=importlib.util.spec_from_file_location("governor_recovery_adapter",str(RECOVERY))
    mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    return mod

def make_intent(goal,info):
    stamp=goal["thread_id"]+":"+str(goal["revision"])
    def det(label):
        return str(uuid.UUID(bytes=hashlib.sha256(
          ("claudex-goal-governor-v1:"+label+":"+stamp).encode()
        ).digest()[:16],version=4))
    return dict(command_id=det("command"),message_id=det("message"),
      base_turn=info["turn_id"],revision=goal["revision"],
      created_at=state.now(),send_attempts=0)

def check_receipt(db,intent):
    rec=db.execute("SELECT status FROM orchestration_command_receipts WHERE command_id=?",
      (intent["command_id"],)).fetchone()
    if rec:
        return "accepted" if rec["status"]=="accepted" else "rejected"
    row=db.execute("SELECT 1 FROM projection_thread_messages WHERE message_id=? LIMIT 1",
      (intent["message_id"],)).fetchone()
    return "accepted" if row else "absent"

def human_message_after(db,thread,when):
    return bool(db.execute("""SELECT 1 FROM projection_thread_messages
       WHERE thread_id=? AND role='user' AND created_at>? LIMIT 1""",
       (thread,when)).fetchone())

def choose(goal,ledger,info,db,at):
    if goal.get("status")!="active" or not goal.get("auto_enabled"):
        return "inactive",None
    if not info or info.get("provider_name")!="claudeAgent" or info.get("provider_instance_id")!="claudex":
        return "other_provider",None
    if info.get("project_id")!=goal["project_id"] or info.get("archived_at") or info.get("deleted_at"):
        return "project_invalid",None
    if info.get("pending_user_input_count") or info.get("pending_approval_count"):
        return "awaiting_human",None
    if info.get("interrupted"):
        return "user_stop",None
    if info.get("state") in ("pending","starting","requested","running"):
        return "running",None
    if info.get("state") in ("error","failed"):
        return "failure_recovery_owns",None
    if info.get("state")!="completed" or info.get("session_status")!="ready":
        return "not_ready",None
    if not state.evidence_valid(goal) or len(goal.get("next_action",""))<20:
        return "missing_evidence",None
    completed=state.timeparse(info.get("completed_at"))
    if completed is None or (at-completed).total_seconds()<SETTLE_SECONDS:
        return "settling",None
    intent=ledger.get("intent")
    if intent:
        receipt=check_receipt(db,intent)
        if receipt!="absent":
            return ("received" if receipt=="accepted" else "rejected"),intent
        if intent["send_attempts"]>=MAX_TRANSPORT_ATTEMPTS:
            return "transport_ambiguous_exhausted",None
        if info["turn_id"]!=intent["base_turn"] or goal["revision"]!=intent["revision"]:
            return "superseded",None
        interval=30 if intent["send_attempts"]==1 else 120
        last=state.timeparse(ledger.get("last_send_at"))
        if last and (at-last).total_seconds()<interval:
            return "transport_backoff",None
        return "retry_same_id",intent

    # This check comes after receipt reconciliation: our own already-accepted
    # idempotent continuation appears as a user message in T3's projection.
    if human_message_after(db,goal["thread_id"],info["completed_at"]):
        return "human_resumed",None
    previous=ledger.get("dispatched_revision")
    if previous is not None:
        if info["turn_id"]==ledger.get("anchor_turn"):
            return "await_new_turn",None
        if goal["revision"]<=previous:
            return "stalled_no_checkpoint",None
    times=[state.timeparse(t) for t in ledger.get("launches",[])]
    times=[t for t in times if t is not None]
    if sum((at-t).total_seconds()<3600 for t in times)>=MAX_PER_HOUR:
        return "hourly_budget",None
    if sum((at-t).total_seconds()<86400 for t in times)>=MAX_PER_DAY:
        return "daily_budget",None
    latest=state.timeparse(ledger.get("last_dispatch_at"))
    if latest and (at-latest).total_seconds()<MIN_GAP_SECONDS:
        return "cooldown",None
    return "prepare",make_intent(goal,info)

def record_dispatch(ledger,intent):
    ledger.update(intent=None,dispatched_revision=intent["revision"],
      anchor_turn=intent["base_turn"],last_dispatch_at=state.now())
    ledger["launches"]=(ledger.get("launches",[])+[state.now()])[-MAX_PER_DAY:]

def advance(goal,ledger,info,db,at,send=None):
    """Pure tests may provide fake send callback. No work is sent without send."""
    decision,intent=choose(goal,ledger,info,db,at)
    if decision=="received":
        record_dispatch(ledger,intent)
        return "receipt_committed"
    if decision=="rejected":
        ledger["intent"]=None
        ledger["blocked_turn"]=intent["base_turn"]
        return "rejected_command"
    if decision=="stalled_no_checkpoint":
        goal["status"]="needs_review"
        goal["blocked_reason"]="Previous autonomous turn ended without a new evidence-backed checkpoint."
        return "stalled"
    if decision not in ("prepare","retry_same_id") or send is None:
        return decision
    if ledger.get("blocked_turn")==info["turn_id"]:
        return "rejected_command"
    if decision=="prepare":
        ledger["intent"]=intent
    return ("to_send",intent)

def one_tick(live=False):
    recovery=adapter()
    ledger_path=state.ROOT/"ledger.json"
    # Cooperate with the already installed HTTP/crash recovery controller.
    # Both supervisors share one nonblocking execution lease, so even across
    # rapid turn transitions they cannot dispatch at the same instant.
    recovery_lock_path=recovery.BASE/"lock"
    if not recovery_lock_path.is_file() or recovery_lock_path.is_symlink():
        raise RuntimeError("Claudex failure recovery lock unavailable")
    with open(recovery_lock_path,"a+") as shared:
        try:fcntl.flock(shared,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return 0
        return _tick_with_shared_lock(recovery,ledger_path,live)

def _tick_with_shared_lock(recovery,ledger_path,live):
    with state.locked():
        ledger=state.read(ledger_path) if ledger_path.exists() else {"version":1,"threads":{}}
        if ledger.get("version")!=1:raise RuntimeError("invalid ledger")
        for file in sorted(state.home().glob("*.json")):
            goal=state.read(file)
            if goal.get("version")!=1 or not goal.get("auto_enabled") or goal.get("status")!="active":
                continue
            thread=state.uuidcheck(goal["thread_id"])
            row=ledger["threads"].setdefault(thread,{"intent":None,"launches":[]})
            with recovery.db_connect() as db:
                info=recovery.inspect_thread(db,thread)
                result=advance(goal,row,info,db,dt.datetime.now(dt.timezone.utc),
                               send=bool(live))
            if not live:
                print(json.dumps({"thread_suffix":thread[-8:],"decision":result if isinstance(result,str) else result[0]}))
                continue
            if result=="stalled":
                state.write(file,goal)
                continue
            if result in ("receipt_committed","rejected_command"):
                state.write(ledger_path,ledger)
                continue
            if not (isinstance(result,tuple) and result[0]=="to_send"):
                continue
            intent=result[1]
            # Durable intent before any network request. Fixed id on timeout.
            state.write(ledger_path,ledger)
            with recovery.db_connect() as db:
                new_info=recovery.inspect_thread(db,thread)
                # Race guard for newer human turns, permissions or changed goals.
                if (not new_info or new_info["turn_id"]!=intent["base_turn"] or
                    new_info["state"]!="completed" or new_info.get("pending_approval_count") or
                    new_info.get("pending_user_input_count") or
                    new_info.get("interrupted") or
                    state.load(thread).get("revision")!=intent["revision"] or
                    human_message_after(db,thread,new_info["completed_at"])):
                    continue
            intent["send_attempts"]+=1
            row["last_send_at"]=state.now()
            state.write(ledger_path,ledger)
            try:
                token=recovery.issue_token()
                recovery.t3_http_health(token)
                cmd={"type":"thread.turn.start","commandId":intent["command_id"],
                    "threadId":thread,"message":{"messageId":intent["message_id"],
                    "role":"user","text":MESSAGE,"attachments":[]},
                    "runtimeMode":new_info["runtime_mode"],
                    "interactionMode":new_info["interaction_mode"],
                    "createdAt":intent["created_at"]}
                asyncio.run(recovery.t3_dispatch(token,cmd))
                record_dispatch(row,intent)
                state.write(ledger_path,ledger)
                print(json.dumps({"event":"goal_continued","thread_suffix":thread[-8:]}))
            except Exception as exc:
                # Ambiguous dispatch retains exactly the original command UUID.
                print(json.dumps({"event":"goal_dispatch_deferred",
                  "error_type":type(exc).__name__,"thread_suffix":thread[-8:]}))
    return 0

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--live",action="store_true")
    args=p.parse_args()
    try:return one_tick(args.live)
    except Exception as exc:
        print(json.dumps({"event":"governor_failed","error_type":type(exc).__name__}))
        return 2
if __name__=="__main__":sys.exit(main())
