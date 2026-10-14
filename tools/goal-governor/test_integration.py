#!/usr/bin/env python3
"""Full one-shot/ledger tests with mocked T3 provider; zero live requests."""
import contextlib,datetime as dt,fcntl,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT))
import state,supervisor

THREAD="11111111-2222-4333-8444-555555555555"
PROJECT="66666666-7777-4888-9999-aaaaaaaaaaaa"
def iso(seconds=-90):
    return (dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=seconds)).isoformat().replace("+00:00","Z")

class FakeDB:
    def __init__(self,recovery):self.recovery=recovery
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def execute(self,sql,values=()):
        if "FROM orchestration_command_receipts" in sql:
            return Cursor([{"status":self.recovery.receipt_status}]) if self.recovery.receipt_status else Cursor([])
        if "FROM orchestration_events" in sql:
            return Cursor([x for x in self.recovery.events if x["occurred_at"]>values[1]])
        if "SELECT message_id,created_at,text FROM projection_thread_messages" in sql:
            return Cursor([self.recovery.message] if self.recovery.message and values[1]==self.recovery.message['message_id'] else [])
        if "FROM projection_thread_messages" in sql:return Cursor([])
        raise AssertionError("unexpected query")
class Cursor:
    def __init__(self,data):self.data=data
    def fetchone(self):return self.data[0] if self.data else None
    def fetchall(self):return list(self.data)

class FakeRec:
    def __init__(self):
        self.calls=[]
        self.turn="11111111-2222-4333-8444-000000000001"
        self.turn_status="completed"
        self.receipt_status=None
        self.fail_next=False
        self.events=[]
        self.message=None
    def db_connect(self):return FakeDB(self)
    def inspect_thread(self,db,thread):
        return {"turn_id":self.turn,"thread_id":thread,
            "provider_name":"claudeAgent","provider_instance_id":"claudex",
            "project_id":PROJECT,"state":self.turn_status,"session_status":"ready",
            "archived_at":None,"deleted_at":None,"pending_approval_count":0,
            "pending_user_input_count":0,"interrupted":False,
            "requested_at":iso(-250),"completed_at":iso(-90),
            "runtime_mode":"full-access","interaction_mode":"default"}
    def issue_token(self):return "not-a-real-token"
    def t3_http_health(self,token):assert token=="not-a-real-token"
    async def t3_dispatch(self,token,cmd):
        assert token=="not-a-real-token"
        self.calls.append(cmd)
        if self.fail_next:
            self.fail_next=False
            raise TimeoutError("synthetic lost HTTP acknowledgment")
        return "accepted"

class Integration(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        old=state.ROOT;state.ROOT=self.root/"goals-root"
        self.addCleanup(lambda:setattr(state,"ROOT",old))
        project=self.root/"workspace";project.mkdir()
        self.goal=state.create(THREAD,PROJECT,project,"Deliver tested ChatGPT-compatible API",
            ["Provide working authenticated endpoint","Pass comprehensive tests"],
            "Inspect project state and execute the next ready baseline test suite.")
        state.enabled(THREAD,True)
        self.fake=FakeRec()
        self.fake.BASE=self.root/"recovery"
        self.fake.BASE.mkdir()
        (self.fake.BASE/"lock").write_text("")
    def run_tick(self,live):
        with patch.object(supervisor,"adapter",return_value=self.fake):
            with contextlib.redirect_stdout(io.StringIO()):
                return supervisor.one_tick(live)
    def ledger(self):
        return state.read(state.ROOT/"ledger.json")
    def test_initial_auto_continuation_exactly_once(self):
        self.assertEqual(self.run_tick(live=True),0)
        self.assertEqual(len(self.fake.calls),1)
        cmd=self.fake.calls[0]
        self.assertEqual(cmd["threadId"],THREAD)
        self.assertEqual(cmd["type"],"thread.turn.start")
        self.assertIn("checkpoint",cmd["message"]["text"])
        ledger=self.ledger()["threads"][THREAD]
        self.assertEqual(ledger["dispatched_revision"],0)
        self.assertIsNone(ledger["intent"])
        self.assertEqual(self.run_tick(live=True),0)
        self.assertEqual(len(self.fake.calls),1)
    def test_second_completed_turn_without_checkpoint_flags_stall(self):
        self.run_tick(live=True)
        self.fake.turn="11111111-2222-4333-8444-000000000002"
        self.run_tick(live=True)
        obj=state.load(THREAD)
        self.assertEqual(obj["status"],"needs_review")
        self.assertEqual(len(self.fake.calls),1)
    def test_failed_turn_never_replayed_by_governor(self):
        self.fake.turn_status="error"
        self.run_tick(live=True)
        self.assertEqual(len(self.fake.calls),0)
    def test_pending_approval_suppresses_continuation(self):
        base=self.fake.inspect_thread
        def special(*a):
            x=base(*a);x["pending_approval_count"]=1;return x
        self.fake.inspect_thread=special
        self.run_tick(live=True)
        self.assertEqual(len(self.fake.calls),0)
    def test_ambiguous_transport_receipt_reuses_original_command(self):
        self.fake.fail_next=True
        self.run_tick(live=True)
        original=self.fake.calls[0]["commandId"]
        data=self.ledger()["threads"][THREAD]
        self.assertIsNotNone(data["intent"])
        self.assertEqual(data["intent"]["command_id"],original)
        self.fake.receipt_status="accepted"
        self.run_tick(live=True)
        self.assertEqual(len(self.fake.calls),1)
        updated=self.ledger()["threads"][THREAD]
        self.assertIsNone(updated["intent"])
        self.assertEqual(updated["dispatched_revision"],0)
    def test_busy_failure_supervisor_lock_prevents_competing_resume(self):
        with open(self.fake.BASE/"lock","a+") as busy:
            fcntl.flock(busy,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.assertEqual(self.run_tick(live=True),0)
        self.assertEqual(len(self.fake.calls),0)
        self.assertFalse((state.ROOT/"ledger.json").exists())

    def test_new_client_user_goal_change_reawakens_blocked_goal_once(self):
        goal=state.load(THREAD)
        goal['status']='blocked'
        goal['blocked_reason']='Prior browser maintenance awaits explicit approval'
        goal['updated_at']=iso(-500)
        goal['enrolled_at']=iso(-500)  # Synthetic user event must follow enrollment.
        state.write(state.path(THREAD),goal)
        msgid='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        self.fake.events=[dict(occurred_at=iso(-150),payload_json=json.dumps({'messageId':msgid}))]
        self.fake.message=dict(message_id=msgid,created_at=iso(-150),
            text='Please deliver a safe standalone alpha before production hardening')
        self.assertEqual(self.run_tick(live=True),0)
        updated=state.load(THREAD)
        self.assertEqual(updated['status'],'active')
        self.assertEqual(len(updated['intent_sync']['pending']),1)
        self.assertEqual(len(updated['tasks']),2)
        legacy=next(t for t in updated['tasks'] if t['id']=='legacy-blocker')
        self.assertEqual(legacy['state'],'blocked')
        self.assertIn('approval',legacy['blocker'])
        self.assertEqual(len(self.fake.calls),1)
        self.run_tick(live=True)
        self.assertEqual(len(self.fake.calls),1)

    def test_dry_run_does_not_persist_or_send(self):
        self.run_tick(live=False)
        self.assertEqual(len(self.fake.calls),0)
        self.assertFalse((state.ROOT/"ledger.json").exists())
if __name__=="__main__":unittest.main(verbosity=2)
