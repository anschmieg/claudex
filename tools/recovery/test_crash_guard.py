#!/usr/bin/env python3
"""Fail-closed crash detection regression tests (no T3 or provider processes)."""
import datetime as dt
import importlib.util
from pathlib import Path
import sys
from unittest.mock import patch
import unittest

src=Path(__file__).with_name("controller.py")
spec=importlib.util.spec_from_file_location("crash_guard_controller",src)
c=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=c
spec.loader.exec_module(c)

NOW=dt.datetime(2026,10,14,14,tzinfo=dt.timezone.utc)
def at(delta):
    return (NOW+dt.timedelta(seconds=delta)).isoformat().replace("+00:00","Z")
GOAL={"thread_id":"11111111-2222-4333-8444-555555555555",
      "project_id":"66666666-7777-4888-9999-aaaaaaaaaaaa",
      "enrolled_at":at(-86400),
      "runtime_mode":"full-access","interaction_mode":"default"}
def info():
    return {"turn_id":"77777777-7777-4777-8777-777777777777",
        "provider_name":"claudeAgent","provider_instance_id":"claudex",
        "project_id":GOAL["project_id"],"state":"running","session_status":"stopped",
        "archived_at":None,"deleted_at":None,"pending_approval_count":0,
        "pending_user_input_count":0,"interrupted":False,
        "runtime_mode":"full-access","requested_at":at(-1900),
        "started_at":at(-1800),"completed_at":None,"last_activity_at":at(-500),
        "error_class":"unknown"}

class OrphanSafetyTests(unittest.TestCase):
    def test_orphan_only_when_all_conditions_pass(self):
        with patch.object(c,"no_live_claudex_lease",return_value=True):
            self.assertTrue(c.orphaned_turn(info(),NOW))
            self.assertEqual(c.safe_snapshot(info(),GOAL,NOW),"recoverable")
    def test_live_lease_is_not_orphan(self):
        with patch.object(c,"no_live_claudex_lease",return_value=False):
            self.assertEqual(c.safe_snapshot(info(),GOAL,NOW),"active_turn")
    def test_recent_activity_blocks_orphan(self):
        d=info();d["last_activity_at"]=at(-12)
        with patch.object(c,"no_live_claudex_lease",return_value=True):
            self.assertEqual(c.safe_snapshot(d,GOAL,NOW),"active_turn")
    def test_provider_ready_blocks_orphan(self):
        d=info();d["session_status"]="ready"
        with patch.object(c,"no_live_claudex_lease",return_value=True):
            self.assertEqual(c.safe_snapshot(d,GOAL,NOW),"active_turn")
    def test_pending_approval_trumps_orphan(self):
        d=info();d["pending_approval_count"]=1
        with patch.object(c,"no_live_claudex_lease",return_value=True):
            self.assertEqual(c.safe_snapshot(d,GOAL,NOW),"awaiting_human")
    def test_user_interrupt_trumps_orphan(self):
        d=info();d["interrupted"]=True
        with patch.object(c,"no_live_claudex_lease",return_value=True):
            self.assertEqual(c.safe_snapshot(d,GOAL,NOW),"user_interrupt")

if __name__=="__main__":
    unittest.main(verbosity=2)
