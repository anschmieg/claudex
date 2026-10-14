#!/usr/bin/env python3
"""No-inference T3 RPC transport and durable recovery dry-run tests."""
import asyncio
import contextlib
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
from unittest.mock import patch
import unittest

P = Path(__file__).with_name("controller.py")
spec = importlib.util.spec_from_file_location("claudex_recovery_transport",P)
rc=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=rc
spec.loader.exec_module(rc)

THREAD = "11111111-2222-4333-8444-555555555555"
PROJECT = "66666666-7777-4888-9999-aaaaaaaaaaaa"

class FakeWs:
    def __init__(self,outcome="Success"):
        self.sent=[]
        self.outcome=outcome
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def send(self,text):self.sent.append(json.loads(text))
    async def recv(self):
        return json.dumps({"_tag":"Exit","requestId":"1",
            "exit":{"_tag":self.outcome,"value":{"commandId":"synthetic"}}
                    if self.outcome=="Success" else
                    {"_tag":"Failure","cause":[{"_tag":"Fail","error":{"_tag":"TestRejected"}}]}})

class TransportTests(unittest.TestCase):
    def test_websocket_dispatch_uses_authenticated_rpc_idempotency(self):
        fake=FakeWs()
        def connect(url,**kwargs):
            self.assertEqual(url,"ws://127.0.0.1:3773/ws?clientSurface=web&connectionMethod=direct")
            self.assertEqual(kwargs["additional_headers"]["Authorization"],"Bearer dummy-auth")
            return fake
        dummy=types.ModuleType("websockets")
        dummy.connect=connect
        cmd={"type":"thread.turn.start","commandId":rc.deterministic_id("cmd",THREAD,"failed-123",1)}
        with patch.dict(sys.modules,{"websockets":dummy}):
            self.assertEqual(asyncio.run(rc.t3_dispatch("dummy-auth",cmd)),"accepted")
        self.assertEqual(len(fake.sent),1)
        self.assertEqual(fake.sent[0]["_tag"],"Request")
        self.assertEqual(fake.sent[0]["tag"],"orchestration.dispatchCommand")
        self.assertEqual(fake.sent[0]["payload"],cmd)
        self.assertEqual(fake.sent[0]["headers"],[])
        self.assertNotIn("dummy-auth",json.dumps(fake.sent))
    def test_server_rejection_fails_closed(self):
        fake=FakeWs("Failure")
        dummy=types.ModuleType("websockets")
        dummy.connect=lambda *_a,**_kw:fake
        with patch.dict(sys.modules,{"websockets":dummy}):
            with self.assertRaises(RuntimeError):
                asyncio.run(rc.t3_dispatch("dummy",{"type":"thread.turn.start"}))
    def test_nonlocal_endpoint_rejected(self):
        with self.assertRaises(ValueError):
            asyncio.run(rc.t3_dispatch("dummy",{},origin="https://api.example.com"))
        with self.assertRaises(ValueError):
            asyncio.run(rc.t3_dispatch("dummy",{},origin="http://127.0.0.1:3773@evil.example"))
    def test_status_does_not_modify_state(self):
        with tempfile.TemporaryDirectory() as path:
            state=Path(path)
            rc.BASE=state
            rc.atomic_json(state/"config.json",{"version":1,"enabled":False,"goals":[]})
            before=(state/"config.json").read_bytes()
            with open("/dev/null","w") as devnull, contextlib.redirect_stdout(devnull):
                self.assertEqual(rc.run_once(live=False),0)
            self.assertEqual((state/"config.json").read_bytes(),before)
            self.assertFalse((state/"ledger.json").exists())
    def test_dry_run_of_recoverable_failure_does_not_persist_intent(self):
        with tempfile.TemporaryDirectory() as path:
            state=Path(path)
            rc.BASE=state
            rc.T3_DB=state/"state.sqlite"
            now=dt.datetime.now(dt.timezone.utc)
            timefmt=lambda x:x.isoformat().replace("+00:00","Z")
            conn=sqlite3.connect(rc.T3_DB)
            for sql in (
                "create table projection_turns (turn_id text,thread_id text,state text,requested_at text,started_at text,completed_at text)",
                "create table projection_thread_sessions (thread_id text,provider_name text,provider_instance_id text,status text,last_error text)",
                "create table projection_threads (thread_id text,project_id text,archived_at text,deleted_at text,pending_approval_count integer,pending_user_input_count integer,runtime_mode text,interaction_mode text,latest_user_message_at text)",
                "create table projection_thread_activities (thread_id text,turn_id text,kind text,created_at text,payload_json text)",
                "create table orchestration_events (stream_id text,event_type text,occurred_at text)",
                "create table orchestration_command_receipts (command_id text,status text)",
                "create table projection_thread_messages (message_id text,thread_id text,role text,created_at text)"):
                conn.execute(sql)
            fail_turn="88888888-8888-4888-8888-888888888888"
            at=lambda delta:timefmt(now+dt.timedelta(seconds=delta))
            conn.execute("insert into projection_turns values (?,?,?,?,?,?)",
                         (fail_turn,THREAD,"error",at(-300),at(-299),at(-240)))
            conn.execute("insert into projection_thread_sessions values (?,?,?,?,?)",
                         (THREAD,"claudeAgent","claudex","ready",None))
            conn.execute("insert into projection_threads values (?,?,?,?,?,?,?,?,?)",
                         (THREAD,PROJECT,None,None,0,0,"full-access","default",at(-300)))
            conn.execute("insert into projection_thread_activities values (?,?,?,?,?)",
                         (THREAD,fail_turn,"runtime.error",at(-240),
                         json.dumps({"message":"Claude runtime stream failed."})))
            conn.commit()
            conn.close()
            rc.atomic_json(state/"config.json",{"version":1,"enabled":True,"goals":[{
                "thread_id":THREAD,"project_id":PROJECT,"enrolled_at":at(-400),
                "runtime_mode":"full-access","interaction_mode":"default"}]})
            with open("/dev/null","w") as devnull,contextlib.redirect_stdout(devnull):
                self.assertEqual(rc.run_once(live=False),0)
            self.assertFalse((state/"ledger.json").exists(),
                "Dry-run accidentally wrote a recovery intent into the durable ledger")

if __name__=="__main__":
    unittest.main(verbosity=2)
