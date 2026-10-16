import os,subprocess,tempfile,unittest
from pathlib import Path
WRAPPER=Path(__file__).resolve().parents[2]/'wrapper/claudex'
class WrapperTests(unittest.TestCase):
 def test_opt_out_does_not_invoke_python(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);exe=root/'launcher';exe.write_text('#!/bin/sh\nprintf "LAUNCHER\\n"\n');exe.chmod(0o755)
   env=os.environ.copy();env['CLAUDEX_DATA_HOME']=tmp;env.pop('CLAUDEX_EFFICIENCY',None)
   run=subprocess.run(['bash',str(WRAPPER)],env=env,capture_output=True,text=True)
   self.assertEqual(run.returncode,0);self.assertEqual(run.stdout.strip(),'LAUNCHER');self.assertEqual(run.stderr,'')
 def test_advisory_does_not_change_launcher_exit(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);exe=root/'launcher';exe.write_text('#!/bin/sh\nexit 7\n');exe.chmod(0o755)
   env=os.environ.copy();env.update(CLAUDEX_DATA_HOME=tmp,CLAUDEX_EFFICIENCY='advisory')
   run=subprocess.run(['bash',str(WRAPPER)],env=env,capture_output=True,text=True)
   self.assertEqual(run.returncode,7)
if __name__=='__main__':unittest.main()
