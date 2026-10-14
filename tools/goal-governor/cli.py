#!/usr/bin/env python3
"""User/worker CLI for a goal governed by the independent T3 supervisor."""
from __future__ import annotations
import argparse, importlib.util, json, os, sys
from pathlib import Path
import state
import sync

RECOVERY=Path(os.environ.get("CLAUDEX_RECOVERY_PY",
    str(Path.home()/".local/share/claudex/recovery/controller.py")))

def project_for(thread):
    if not RECOVERY.is_file():raise RuntimeError("Claudex recovery module not installed")
    spec=importlib.util.spec_from_file_location("goal_cli_t3_recovery",str(RECOVERY))
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    with module.db_connect() as db:
        row=db.execute("""SELECT t.project_id,p.workspace_root,s.provider_name,
                          s.provider_instance_id FROM projection_threads t
                          JOIN projection_projects p ON p.project_id=t.project_id
                          JOIN projection_thread_sessions s ON s.thread_id=t.thread_id
                          WHERE t.thread_id=?""",(thread,)).fetchone()
    if not row or row["provider_name"]!="claudeAgent" or row["provider_instance_id"]!="claudex":
        raise ValueError("thread is not Claudex")
    return row

def run():
    parser=argparse.ArgumentParser(description="Durable Goal Governor (opt-in, no loops)")
    subs=parser.add_subparsers(dest="op",required=True)
    create=subs.add_parser("init",help="Enroll existing Claudex thread, initially disabled")
    create.add_argument("--thread",required=True)
    create.add_argument("--workspace",required=True)
    create.add_argument("--title",required=True)
    create.add_argument("--acceptance",action="append",required=True)
    create.add_argument("--next-action",required=True)
    update=subs.add_parser("checkpoint",help="Record progress and verified next step")
    update.add_argument("--thread",required=True)
    update.add_argument("--next-action",required=True)
    update.add_argument("--evidence",required=True)
    update.add_argument("--artifact")
    update.add_argument("--evidence-kind",choices=["artifact","test_report","user_decision"],default="artifact")
    update.add_argument("--evidence-ref")
    update.add_argument("--expected-revision",type=int)
    task_add=subs.add_parser("add-task")
    task_add.add_argument("--thread",required=True);task_add.add_argument("--id",required=True)
    task_add.add_argument("--title",required=True);task_add.add_argument("--depends",action="append",default=[])
    task_set=subs.add_parser("set-task")
    task_set.add_argument("--thread",required=True);task_set.add_argument("--id",required=True)
    task_set.add_argument("--state",choices=["ready","running","blocked","completed","deferred"],required=True)
    task_set.add_argument("--reason");task_set.add_argument("--evidence")
    sync_now=subs.add_parser("sync")
    sync_now.add_argument("--thread",required=True)
    sync=subs.add_parser("reconcile")
    sync.add_argument("--thread",required=True);sync.add_argument("--message-id",required=True)
    sync.add_argument("--title");sync.add_argument("--acceptance",action="append")
    sync.add_argument("--priority")
    for command in ("status","enable","disable","resume","pause","block"):
        x=subs.add_parser(command);x.add_argument("--thread",required=True)
        if command=="block":x.add_argument("--reason",required=True)
    review=subs.add_parser("propose-complete")
    review.add_argument("--thread",required=True)
    review.add_argument("--evidence",required=True)
    args=parser.parse_args()
    with state.locked():
        if args.op=="init":
            db=project_for(args.thread)
            if Path(args.workspace).resolve(strict=True)!=Path(db["workspace_root"]).resolve(strict=True):
                raise ValueError("project workspace mismatch")
            obj=state.create(args.thread,db["project_id"],args.workspace,args.title,
                args.acceptance,args.next_action)
        elif args.op=="status":
            obj=state.load(args.thread)
            print(json.dumps({key:obj.get(key) for key in
                ("title","status","auto_enabled","acceptance","revision","next_action",
                 "evidence","artifact","blocked_reason","completion_proposal","tasks","intent_sync","plan_revision","immutable_constraints","acceptance_history")},indent=2))
            return
        elif args.op=="checkpoint":
            if args.evidence_kind=='user_decision':
                recover=project_for(args.thread)
                import importlib.util
                spec=importlib.util.spec_from_file_location('goal_cli_reread_t3',str(RECOVERY))
                mod=importlib.util.module_from_spec(spec)
                sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
                with mod.db_connect() as db:
                    obj=state.checkpoint(args.thread,args.next_action,args.evidence,args.artifact,
                        args.expected_revision,args.evidence_kind,args.evidence_ref,db)
            else:
                obj=state.checkpoint(args.thread,args.next_action,args.evidence,args.artifact,
                    args.expected_revision,args.evidence_kind)
        elif args.op=="add-task":
            obj=state.add_task(args.thread,args.id,args.title,args.depends)
        elif args.op=="set-task":
            obj=state.task_state(args.thread,args.id,args.state,args.reason,args.evidence)
        elif args.op=="sync":
            obj=state.load(args.thread)
            if obj.get('auto_enabled'):
                import importlib.util
                spec=importlib.util.spec_from_file_location('goal_sync_t3',str(RECOVERY))
                mod=importlib.util.module_from_spec(spec)
                sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
                with mod.db_connect() as db:
                    updated=sync.ingest(obj,db)
                if updated:state.write(state.path(args.thread),obj)
            print(json.dumps({'result':'ok','pending_message_ids':
              [m['message_id'] for m in obj['intent_sync']['pending']],
              'ready_tasks':[t['id'] for t in __import__('tasks').ready(obj)]}))
            return
        elif args.op=="reconcile":
            obj=state.reconcile_intent(args.thread,args.message_id,args.title,args.acceptance,args.priority)
        elif args.op=="propose-complete":
            obj=state.mark_review(args.thread,args.evidence)
        elif args.op=="block":
            obj=state.state_change(args.thread,"blocked",args.reason)
        elif args.op in ("pause","resume"):
            obj=state.state_change(args.thread,
                {"pause":"paused","resume":"active"}[args.op])
        elif args.op in ("enable","disable"):
            obj=state.enabled(args.thread,args.op=="enable")
        else:
            raise ValueError("unknown operation")
        print(json.dumps({"result":"ok","status":obj["status"],"revision":obj["revision"],
                          "auto_enabled":obj["auto_enabled"],"thread_suffix":obj["thread_id"][-8:]}))

if __name__=="__main__":
    try:run()
    except (ValueError,RuntimeError,OSError,BlockingIOError) as error:
        print(json.dumps({"result":"error","type":type(error).__name__}),file=sys.stderr)
        sys.exit(2)
