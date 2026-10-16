import tempfile,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from read_hook import evaluate
class Tests(unittest.TestCase):
 def test_large_read_denied_with_range_hint(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'large.txt';p.write_bytes(b'a'*180000)
   x=evaluate({'hook_event_name':'PreToolUse','tool_name':'Read','tool_input':{'file_path':str(p)}})
   self.assertEqual(x['hookSpecificOutput']['permissionDecision'],'deny')
 def test_small_read_passes(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'small.txt';p.write_bytes(b'a'*1200)
   self.assertIsNone(evaluate({'hook_event_name':'PreToolUse','tool_name':'Read','tool_input':{'file_path':str(p)}}))
 def test_explicit_bounded_read_passes(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'large.txt';p.write_bytes(b'a'*180000)
   self.assertIsNone(evaluate({'hook_event_name':'PreToolUse','tool_name':'Read','tool_input':{'file_path':str(p),'limit':80}}))
 def test_other_tools_unaffected(self):
  self.assertIsNone(evaluate({'hook_event_name':'PreToolUse','tool_name':'Bash','tool_input':{'file_path':'/tmp/a'}}))
if __name__=='__main__':unittest.main(verbosity=2)
