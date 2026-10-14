#!/usr/bin/env python3
"""Synthetic Goal Governor tests; no T3 write, auth, or model inference."""
import contextlib,datetime as dt,importlib.util,io,json,os
from pathlib import Path
import sqlite3,sys,tempfile,unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
import state
import supervisor

THREAD="11111111-2222-4333-8444-555555555555"
PROJECT="66666666-7777-4888-9999-aaaaaaaaaaaa"
AT=dt.datetime(2026,10,14,12,tzinfo=dt.timezone.utc)
def stamp(seconds):
    return (AT+dt.timedelta(seconds=seconds)).isoformat().replace("+00:00","Z")
def info(**kw):
    d=dict(turn_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
      provider_name="claudeAgent",provider_instance_id="claudex",project_id=PROJECT,
      archived_at=None,deleted_at=None,pending_approval_count=0,pending_user_input_count=0,
      interrupted=False,state="completed",session_status="ready",
      requested_at=stamp(-180),completed_at=stamp(-70),
      runtime_mode="full-access",interaction_mode="default")
    d.update(kw);return d
class TestGovernor(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.old=state.ROOT
        state.ROOT=self.root/"state"
        self.addCleanup(lambda:setattr(state,"ROOT",self.old))
        self.project=self.root/"project";self.project.mkdir()
        self.artifact=self.project/"progress.md";self.artifact.write_text("actual verified progress v1\n")
        self.goal=state.create(THREAD,PROJECT,self.project,
            "Build working API",["responses endpoint works","tests passed"],
            "Inspect current repository state and run the existing baseline tests.")
        self.goal=state.enabled(THREAD,True)
        self.db=sqlite3.connect(":memory:");self.db.row_factory=sqlite3.Row
        self.db.execute("create table orchestration_command_receipts(command_id text,status text)")
        self.db.execute("create table projection_thread_messages(message_id text,thread_id text,role text,created_at text)")
        self.ledger={"intent":None,"launches":[]}
    def tearDown(self):self.db.close()
    def decide(self,info_val=None):
        return supervisor.choose(self.goal,self.ledger,info_val or info(),self.db,AT)
    def test_initial_opt_in_only(self):
        self.assertEqual(self.decide()[0],"prepare")
        self.goal["auto_enabled"]=False;self.assertEqual(self.decide()[0],"inactive")
    def test_current_running_turn_never_stopped(self):
        self.assertEqual(self.decide(info(state="running"))[0],"running")
    def test_error_turn_owned_by_failure_supervisor(self):
        self.assertEqual(self.decide(info(state="error"))[0],"failure_recovery_owns")
    def test_pending_user_approval_blocks(self):
        self.assertEqual(self.decide(info(pending_approval_count=1))[0],"awaiting_human")
        self.assertEqual(self.decide(info(pending_user_input_count=1))[0],"awaiting_human")
    def test_user_stop_blocks(self):
        self.assertEqual(self.decide(info(interrupted=True))[0],"user_stop")
    def test_invalid_provider_or_project_blocks(self):
        self.assertEqual(self.decide(info(provider_instance_id="codex"))[0],"other_provider")
        self.assertEqual(self.decide(info(project_id=THREAD))[0],"project_invalid")
    def test_durable_intent_deterministic(self):
        one=supervisor.make_intent(self.goal,info())
        two=supervisor.make_intent(self.goal,info())
        self.assertEqual(one["command_id"],two["command_id"])
        self.assertEqual(one["message_id"],two["message_id"])
        self.assertNotEqual(one["command_id"],one["message_id"])
    def test_completed_with_no_checkpoint_after_dispatch_flags_stall(self):
        self.ledger["dispatched_revision"]=0
        self.ledger["anchor_turn"]="older-turn"
        self.assertEqual(self.decide()[0],"stalled_no_checkpoint")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(supervisor.advance(self.goal,self.ledger,info(),self.db,AT,send=True),"stalled")
        self.assertEqual(self.goal["status"],"needs_review")
    def test_task_plan_changes_cannot_create_endless_unverified_turns(self):
        self.ledger["dispatched_revision"]=0
        self.ledger["dispatched_plan_revision"]=0
        self.ledger["anchor_turn"]="older-turn"
        self.goal["plan_revision"]=1
        self.ledger["plan_only_count"]=1
        self.assertEqual(self.decide()[0],"prepare")
        self.ledger["plan_only_count"]=2
        self.assertEqual(self.decide()[0],"stalled_no_checkpoint")

    def test_waits_for_new_turn_not_repeat(self):
        self.ledger["dispatched_revision"]=0
        self.ledger["anchor_turn"]=info()["turn_id"]
        self.assertEqual(self.decide()[0],"await_new_turn")
    def test_new_checkpoint_advances_after_new_turn(self):
        self.ledger["dispatched_revision"]=0
        self.ledger["anchor_turn"]="older-turn"
        self.artifact.write_text("actual verified progress v2\n")
        self.goal=state.checkpoint(THREAD,
            "Implement the next independent endpoint and run its regression tests.",
            "Baseline suite passed and new work was verified.",
            self.artifact)
        self.assertEqual(self.goal["revision"],1)
        self.assertEqual(self.decide()[0],"prepare")
    def test_checkpoint_requires_changed_artifact_and_step(self):
        self.goal=state.checkpoint(THREAD,
            "Implement one new endpoint and validate regression tests.",
            "New regression pass and independently inspected output.",
            self.artifact)
        with self.assertRaises(ValueError):
            state.checkpoint(THREAD,"New and different next actionable step for testing.",
                "Some tests ran again without file changes.",self.artifact)
        with self.assertRaises(ValueError):
            state.checkpoint(THREAD,self.goal["next_action"],
                "Existing file changed but step did not.",self.artifact)
    def test_checkpoint_stale_revision_rejected(self):
        with self.assertRaises(ValueError):
            state.checkpoint(THREAD,"Implement and verify API regression improvements.",
              "New durable progress checked with tests.",self.artifact,expected_revision=10)
    def test_no_outside_workspace_or_secret_artifact(self):
        outside=self.root/"outside.txt";outside.write_text("dummy")
        with self.assertRaises(ValueError):state.artifact_digest(self.project,outside)
        (self.project/".env").write_text("not a real secret")
        with self.assertRaises(ValueError):state.artifact_digest(self.project,".env")
        link=self.project/"link";link.symlink_to(self.artifact)
        with self.assertRaises(ValueError):state.artifact_digest(self.project,link)
    def test_pending_receipt_same_id_no_duplicate(self):
        intent=supervisor.make_intent(self.goal,info())
        self.ledger["intent"]=intent
        self.db.execute("insert into orchestration_command_receipts values (?,?)",
            (intent["command_id"],"accepted"))
        self.assertEqual(self.decide()[0],"received")
        self.assertEqual(supervisor.advance(self.goal,self.ledger,info(),self.db,AT),
                         "receipt_committed")
        self.assertIsNone(self.ledger["intent"])
        self.assertEqual(self.ledger["dispatched_revision"],0)
    def test_rejected_receipt_blocks_retry(self):
        intent=supervisor.make_intent(self.goal,info());self.ledger["intent"]=intent
        self.db.execute("insert into orchestration_command_receipts values (?,?)",
            (intent["command_id"],"rejected"))
        self.assertEqual(self.decide()[0],"rejected")
        self.assertEqual(supervisor.advance(self.goal,self.ledger,info(),self.db,AT),
                         "rejected_command")
        self.assertEqual(self.ledger["blocked_turn"],intent["base_turn"])
    def test_transport_retry_same_id(self):
        intent=supervisor.make_intent(self.goal,info());intent["send_attempts"]=1
        self.ledger["intent"]=intent;self.ledger["last_send_at"]=stamp(-90)
        decision,proposed=self.decide()
        self.assertEqual(decision,"retry_same_id")
        self.assertEqual(proposed["command_id"],intent["command_id"])
        self.ledger["last_send_at"]=stamp(-5)
        self.assertEqual(self.decide()[0],"transport_backoff")
    def test_transport_attempts_bounded(self):
        intent=supervisor.make_intent(self.goal,info());intent["send_attempts"]=3
        self.ledger["intent"]=intent
        self.assertEqual(self.decide()[0],"transport_ambiguous_exhausted")
    def test_human_message_after_turn_blocks(self):
        self.db.execute("insert into projection_thread_messages values (?,?,?,?)",
            ("new-message",THREAD,"user",stamp(-10)))
        self.assertEqual(self.decide()[0],"human_resumed")
    def test_hourly_and_daily_budget(self):
        self.ledger["launches"]=[stamp(-1000)]*6
        self.assertEqual(self.decide()[0],"hourly_budget")
        self.ledger["launches"]=[stamp(-7200)]*24
        self.assertEqual(self.decide()[0],"daily_budget")
    def test_completion_requires_review(self):
        self.goal=state.mark_review(THREAD,
            "All user acceptance criteria checked against independent test logs.")
        self.assertEqual(self.goal["status"],"needs_review")
        self.assertEqual(self.decide()[0],"inactive")
    def test_explicit_block_is_not_autoresumed(self):
        self.goal=state.state_change(THREAD,"blocked",
            "The browser writer needs explicit owner approval.")
        self.assertEqual(self.decide()[0],"inactive")
    def test_durable_reload(self):
        self.goal=state.checkpoint(THREAD,
            "Implement the documented endpoint and rerun tests.",
            "Regression suite passed with changed project files.",self.artifact)
        loaded=state.load(THREAD)
        self.assertEqual(loaded["revision"],1)
        self.assertEqual(loaded["artifact"],self.goal["artifact"])
        self.assertTrue(state.evidence_valid(loaded))
if __name__=="__main__":unittest.main(verbosity=2)
