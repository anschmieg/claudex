"""Ensure the UserPromptSubmit hook never outputs the user's prompt."""
import contextlib,importlib.util,io,json,os,sys,tempfile,unittest
from pathlib import Path
HOOK=Path(__file__).parent/'plugin/scripts/session.py'
spec=importlib.util.spec_from_file_location('goal_governor_session_hook',HOOK)
hook=importlib.util.module_from_spec(spec);spec.loader.exec_module(hook)
class HookTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  root=Path(self.tmp.name);self.cwd=root/'project';self.cwd.mkdir()
  self.goals=root/'governor/goals';self.goals.mkdir(parents=True)
  (self.goals/'goal.json').write_text(json.dumps({'workspace':str(self.cwd),
   'status':'blocked','auto_enabled':True,'revision':5}))
  self.previous=os.environ.get('CLAUDEX_GOAL_HOME')
  os.environ['CLAUDEX_GOAL_HOME']=str(self.goals.parent)
  self.addCleanup(self.restore_env)
 def restore_env(self):
  if self.previous is None:os.environ.pop('CLAUDEX_GOAL_HOME',None)
  else:os.environ['CLAUDEX_GOAL_HOME']=self.previous
 def invoke(self,event):
  old=sys.stdin;sys.stdin=io.StringIO(json.dumps(event));out=io.StringIO()
  try:
   with contextlib.redirect_stdout(out):hook.main()
  finally:sys.stdin=old
  return out.getvalue()
 def test_blocked_goal_receives_new_user_prompt_sync_hint(self):
  out=self.invoke({'hook_event_name':'UserPromptSubmit','cwd':str(self.cwd),
                   'prompt':'My bank password is hypothetical secret content'})
  self.assertIn('reconcile',out)
  self.assertNotIn('password',out)
  self.assertNotIn('hypothetical',out)
 def test_other_project_no_output(self):
  self.assertEqual(self.invoke({'hook_event_name':'UserPromptSubmit','cwd':'/tmp/unknown'}),'')
 def test_no_prompt_echo_in_session_start(self):
  out=self.invoke({'hook_event_name':'SessionStart','cwd':str(self.cwd)})
  self.assertTrue(0<len(out)<=700)
if __name__=='__main__':unittest.main(verbosity=2)
