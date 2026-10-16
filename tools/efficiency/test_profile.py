import os,sys,unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
import profile
class ProfileTests(unittest.TestCase):
 def test_off_by_default(self):
  with patch.dict(os.environ,{},clear=True):self.assertEqual(profile.profile()['mode'],'off')
 def test_invalid_mode_fails(self):
  with patch.dict(os.environ,{'CLAUDEX_EFFICIENCY':'automatic'}):
   with self.assertRaises(ValueError):profile.profile()
 def test_mode_explicit(self):
  with patch.dict(os.environ,{'CLAUDEX_EFFICIENCY':'advisory'}):self.assertEqual(profile.profile()['mode'],'advisory')
 def test_long_context(self):
  self.assertIn('long_context',[i['code'] for i in profile.evaluate(profile.DEFAULTS,context_tokens=100000)])
 def test_small_context(self):
  self.assertEqual(profile.evaluate(profile.DEFAULTS,context_tokens=500),[])
 def test_cold_resume(self):
  self.assertIn('cold_resume',[i['code'] for i in profile.evaluate(profile.DEFAULTS,context_tokens=110000,idle_minutes=70)])
 def test_subagent_budget(self):
  self.assertIn('subagent_budget',[i['code'] for i in profile.evaluate(profile.DEFAULTS,agent_count=5)])
 def test_nested_delegation(self):
  self.assertIn('delegation_depth',[i['code'] for i in profile.evaluate(profile.DEFAULTS,depth=2)])
 def test_model_switch(self):
  self.assertIn('model_switch',[i['code'] for i in profile.evaluate(profile.DEFAULTS,model_switch=True)])
 def test_external_calls(self):
  self.assertIn('external_call_budget',[i['code'] for i in profile.evaluate(profile.DEFAULTS,external_calls=1)])
 def test_zero_valid(self):
  with patch.dict(os.environ,{'CLAUDEX_EFFICIENCY_MAX_SUBAGENTS':'0'}):self.assertEqual(profile.profile()['max_subagents'],0)
 def test_secret_not_present(self):
  self.assertNotIn('SECRET',str(profile.evaluate(profile.DEFAULTS,context_tokens=110000)))
if __name__=='__main__':unittest.main(verbosity=2)
