import sys,unittest
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from lifecycle import Session,Policy,eligible,dispatch_if_safe
class Cases(unittest.TestCase):
 def setUp(self):
  self.s=Session('opaque-id', now=3570,last_model_request=0,
   cache_ttl_seconds=3600,context_tokens=150000,active_turn=False,
   active_tool_calls=0,awaiting_user=False,last_user_message=0,
   owner_verified=True)
 def test_ready(self):self.assertEqual(eligible(self.s),'ready')
 def test_unverified_owner(self):self.assertEqual(eligible(replace(self.s,owner_verified=False)),'unverified_session_owner')
 def test_unknown_ttl(self):self.assertEqual(eligible(replace(self.s,cache_ttl_seconds=None)),'cache_lifetime_unknown')
 def test_active_turn(self):self.assertEqual(eligible(replace(self.s,active_turn=True)),'active_work')
 def test_tool_active(self):self.assertEqual(eligible(replace(self.s,active_tool_calls=1)),'active_work')
 def test_human_boundary(self):self.assertEqual(eligible(replace(self.s,awaiting_user=True)),'human_boundary')
 def test_pending_approval(self):self.assertEqual(eligible(replace(self.s,pending_approval=True)),'human_boundary')
 def test_recent_user_message(self):self.assertEqual(eligible(replace(self.s,last_user_message=3565)),'recent_user_message')
 def test_small_context(self):self.assertEqual(eligible(replace(self.s,context_tokens=20000)),'small_context')
 def test_already_expired(self):self.assertEqual(eligible(replace(self.s,now=3601)),'cache_already_expired')
 def test_too_early(self):self.assertEqual(eligible(replace(self.s,now=1000)),'too_early')
 def test_gap(self):self.assertEqual(eligible(replace(self.s,last_compaction=3500)),'recent_compaction')
 def test_no_callback(self):self.assertEqual(dispatch_if_safe(self.s,None),'no_verified_dispatch')
 def test_safe_callback(self):
  called=[]
  self.assertEqual(dispatch_if_safe(self.s,lambda x: called.append(x) or True),'dispatched')
  self.assertEqual(called,['opaque-id'])
 def test_unsafe_callback_never_called(self):
  called=[]
  self.assertEqual(dispatch_if_safe(replace(self.s,active_turn=True),lambda _:called.append('bad')),'active_work')
  self.assertFalse(called)
if __name__=='__main__':unittest.main(verbosity=2)
