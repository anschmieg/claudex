#!/usr/bin/env python3
"""Failure-injection tests for read-only T3 projection + durable recovery intent state."""
import importlib.util
import datetime as dt
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

source=Path(__file__).with_name("controller.py")
spec=importlib.util.spec_from_file_location("recovery_controller",source)
rc=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=rc
spec.loader.exec_module(rc)

THREAD="11111111-2222-4333-8444-555555555555"
PROJECT="66666666-7777-4888-9999-aaaaaaaaaaaa"
NOW=dt.datetime(2026,10,14,12,0,0,tzinfo=dt.timezone.utc)
def at(seconds):
    return (NOW+dt.timedelta(seconds=seconds)).isoformat().replace("+00:00","Z")

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.db.row_factory=sqlite3.Row
        schema=[
            "create table projection_turns (turn_id text,thread_id text,state text,requested_at text,started_at text,completed_at text)",
            "create table projection_thread_sessions (thread_id text,provider_name text,provider_instance_id text,status text,last_error text)",
            "create table projection_threads (thread_id text,project_id text,archived_at text,deleted_at text,pending_approval_count integer,pending_user_input_count integer,runtime_mode text,interaction_mode text,latest_user_message_at text)",
            "create table projection_thread_activities (thread_id text,turn_id text,kind text,created_at text,payload_json text)",
            "create table orchestration_events (stream_id text,event_type text,occurred_at text)",
            "create table orchestration_command_receipts (command_id text,status text)",
            "create table projection_thread_messages (message_id text,thread_id text,role text,created_at text)",
        ]
        for sql in schema:self.db.execute(sql)
        self.db.execute("insert into projection_thread_sessions values (?,?,?,?,?)",
            (THREAD,"claudeAgent","claudex","ready",None))
        self.db.execute("insert into projection_threads values (?,?,?,?,?,?,?,?,?)",
            (THREAD,PROJECT,None,None,0,0,"full-access","default",at(-180)))
        self.failturn="8b840bea-3333-4222-aaaa-1f39f12a16dd"
        self.db.execute("insert into projection_turns values (?,?,?,?,?,?)",
            (self.failturn,THREAD,"error",at(-180),at(-179),at(-120)))
        self.db.execute("insert into projection_thread_activities values (?,?,?,?,?)",
            (THREAD,self.failturn,"runtime.error",at(-120),
             json.dumps({"message":"Claude gave up after repeated API errors."})))
        self.db.commit()
        self.goal={"thread_id":THREAD,"project_id":PROJECT,"enrolled_at":at(-86400),
            "runtime_mode":"full-access","interaction_mode":"default"}
        self.state={"attempts":0,"intent":None,"root_turn_id":None}
    def tearDown(self):self.db.close()
    def decision(self):return rc.choose_action(self.db,self.goal,self.state,NOW)[0]
    def test_known_http_failure_recovers_once(self):
        self.assertEqual(self.decision(),"prepare")
        ledger={"threads":{}}
        requests=rc.process({"goals":[self.goal]},ledger,self.db,NOW,True)
        self.assertEqual(len(requests),1)
        self.assertEqual(requests[0][1],"send_prepared")
        intent=requests[0][2]
        self.assertEqual(intent["attempt"],1)
        self.assertEqual(self.decision(),"prepare") # local manually-maintained state unaffected
        self.state=ledger["threads"][THREAD]
        self.assertEqual(self.decision(),"resend_same_id")
        requests2=rc.process({"goals":[self.goal]},ledger,self.db,NOW,True)
        self.assertEqual(requests2[0][2]["command_id"],intent["command_id"])
        self.assertEqual(requests2[0][2]["message_id"],intent["message_id"])
    def test_receipt_prevents_double_dispatch(self):
        intent=rc.make_intent(THREAD,self.failturn,1)
        self.state["intent"]=intent
        self.db.execute("insert into orchestration_command_receipts values (?,?)",(intent["command_id"],"accepted"))
        ledger={"threads":{THREAD:self.state}}
        self.assertEqual(rc.process({"goals":[self.goal]},ledger,self.db,NOW,True),[])
        self.assertIsNone(self.state["intent"])
        self.assertEqual(self.decision(),"already_dispatched")
    def test_rejected_receipt_blocks_all_retries_for_same_failed_turn(self):
        intent=rc.make_intent(THREAD,self.failturn,1)
        self.state["intent"]=intent
        self.db.execute("insert into orchestration_command_receipts values (?,?)",
            (intent["command_id"],"rejected"))
        ledger={"threads":{THREAD:self.state}}
        self.assertEqual(rc.process({"goals":[self.goal]},ledger,self.db,NOW,True),[])
        self.assertIsNone(self.state["intent"])
        self.assertEqual(self.state["blocked_failed_turn_id"],self.failturn)
        self.assertEqual(self.decision(),"blocked_rejected_command")
        self.assertEqual(rc.process({"goals":[self.goal]},ledger,self.db,NOW,True),[])

    def test_explicit_t3_session_stop_blocks_orphan_resume(self):
        self.db.execute("insert into orchestration_events values (?,?,?)",
            (THREAD,"thread.session-stop-requested",at(-150)))
        self.assertEqual(self.decision(),"user_interrupt")

    def test_old_error_never_retried(self):
        self.goal["enrolled_at"]=at(-60)
        self.assertEqual(self.decision(),"pre_enrollment")
    def test_completed_turn_never_resumed(self):
        self.db.execute("update projection_turns set state='completed' where turn_id=?",(self.failturn,))
        self.assertEqual(self.decision(),"completed")
    def test_running_turn_not_steered(self):
        self.db.execute("update projection_turns set state='running',completed_at=null where turn_id=?",(self.failturn,))
        self.assertEqual(self.decision(),"active_turn")
    def test_pending_approval_blocks(self):
        self.db.execute("update projection_threads set pending_approval_count=1 where thread_id=?",(THREAD,))
        self.assertEqual(self.decision(),"awaiting_human")
    def test_pending_user_input_blocks(self):
        self.db.execute("update projection_threads set pending_user_input_count=1 where thread_id=?",(THREAD,))
        self.assertEqual(self.decision(),"awaiting_human")
    def test_interrupt_never_recovered(self):
        self.db.execute("insert into orchestration_events values (?,?,?)",
            (THREAD,"thread.turn-interrupt-requested",at(-150)))
        self.assertEqual(self.decision(),"user_interrupt")
    def test_wrong_provider_refused(self):
        self.db.execute("update projection_thread_sessions set provider_instance_id='codex' where thread_id=?",(THREAD,))
        self.assertEqual(self.decision(),"other_provider")
    def test_wrong_project_refused(self):
        self.goal["project_id"]="11111111-1111-4111-8111-111111111111"
        self.assertEqual(self.decision(),"project_mismatch")
    def test_authorization_failure_not_retried(self):
        self.db.execute("update projection_thread_activities set payload_json=?",
            (json.dumps({"message":"HTTP 403 forbidden: user approval required"}),))
        self.assertEqual(self.decision(),"not_transient")
    def test_blocked_error_dominates_retryable_gateway_error(self):
        self.db.execute("insert into projection_thread_activities values (?,?,?,?,?)",
            (THREAD,self.failturn,"runtime.error",at(-110),
             json.dumps({"message":"HTTP 403 forbidden: explicit approval required"})))
        self.assertEqual(self.decision(),"not_transient")

    def test_stale_session_level_error_not_used_as_turn_evidence(self):
        self.db.execute("delete from projection_thread_activities where thread_id=?",(THREAD,))
        self.db.execute("update projection_thread_sessions set last_error=? where thread_id=?",
            ("HTTP 503 service unavailable",THREAD))
        self.assertEqual(self.decision(),"not_transient")

    def test_unknown_failure_not_retried(self):
        self.db.execute("update projection_thread_activities set payload_json=?",
            (json.dumps({"message":"Unknown mysterious provider condition"}),))
        self.assertEqual(self.decision(),"not_transient")
    def test_older_stale_error_not_counted_for_this_turn(self):
        self.db.execute("delete from projection_thread_activities")
        self.db.execute("insert into projection_thread_activities values (?,?,?,?,?)",
            (THREAD,None,"runtime.error",at(-10000),
             json.dumps({"message":"HTTP 503 service unavailable"})))
        self.assertEqual(self.decision(),"not_transient")
    def test_new_user_message_prevents_replay(self):
        self.db.execute("insert into projection_thread_messages values (?,?,?,?)",
            ("new-msg",THREAD,"user",at(-30)))
        self.assertEqual(self.decision(),"human_superseded")
    def test_budget_blocks_retry_storm(self):
        self.state["attempts"]=rc.MAX_ATTEMPTS_PER_CHAIN
        self.assertEqual(self.decision(),"retry_budget_exhausted")
    def test_ambiguous_accepted_message_prevents_resend(self):
        intent=rc.make_intent(THREAD,self.failturn,1)
        self.state["intent"]=intent
        self.db.execute("insert into projection_thread_messages values (?,?,?,?)",
            (intent["message_id"],THREAD,"user",at(-15)))
        self.assertEqual(self.decision(),"already_accepted")
    def test_pending_retry_honors_backoff_before_sending(self):
        self.state["intent"]=rc.make_intent(THREAD,self.failturn,1)
        self.state["intent"]["send_attempts"]=1
        self.state["next_eligible_at"]=at(90)
        self.assertEqual(self.decision(),"backoff")
        ledger={"threads":{THREAD:self.state}}
        self.assertEqual(rc.process({"goals":[self.goal]},ledger,self.db,NOW,True),[])
        self.state["next_eligible_at"]=at(-1)
        self.assertEqual(self.decision(),"resend_same_id")

    def test_accepted_receipt_clears_transport_backoff(self):
        intent=rc.make_intent(THREAD,self.failturn,1)
        self.state["intent"]=intent
        self.state["next_eligible_at"]=at(100)
        self.db.execute("insert into orchestration_command_receipts values (?,?)",
            (intent["command_id"],"accepted"))
        self.assertEqual(self.decision(),"already_accepted")
        ledger={"threads":{THREAD:self.state}}
        self.assertEqual(rc.process({"goals":[self.goal]},ledger,self.db,NOW,True),[])
        self.assertNotIn("next_eligible_at",self.state)

    def test_command_ids_are_deterministic_and_distinct(self):
        a=rc.make_intent(THREAD,self.failturn,1)
        b=rc.make_intent(THREAD,self.failturn,1)
        c=rc.make_intent(THREAD,self.failturn,2)
        self.assertEqual(a["command_id"],b["command_id"])
        self.assertEqual(a["message_id"],b["message_id"])
        self.assertNotEqual(a["command_id"],c["command_id"])
        self.assertNotEqual(a["message_id"],a["command_id"])
    def test_atomic_file_and_symlink_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            rc.atomic_json(p/"state.json",{"ok":True})
            self.assertEqual(rc.read_json(p/"state.json",{})["ok"],True)
            (p/"link").symlink_to(p/"state.json")
            with self.assertRaises(RuntimeError):rc.read_json(p/"link",{})
    def test_error_classifier(self):
        self.assertEqual(rc.classify_error("HTTP 503 gateway error"),"transient")
        self.assertEqual(rc.classify_error("Claude runtime stream failed."),"transient")
        self.assertEqual(rc.classify_error("HTTP 403 forbidden"),"blocked")
        self.assertEqual(rc.classify_error("permission denied"),"blocked")
        self.assertEqual(rc.classify_error("completed successfully"),"unknown")

if __name__=="__main__":unittest.main(verbosity=2)
