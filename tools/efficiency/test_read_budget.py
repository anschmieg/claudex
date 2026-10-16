import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from read_budget import Read,target
class Tests(unittest.TestCase):
 def test_small_read(self):self.assertEqual(target(Read('Read',1000,10000)),384000)
 def test_large_read(self):self.assertEqual(target(Read('Read',50000,350000)),768000)
 def test_unknown_tool(self):self.assertEqual(target(Read('Bash',100000,50000)),384000)
 def test_invalid(self):
  with self.assertRaises(ValueError):target(Read('Read',-1,0))
if __name__=='__main__':unittest.main(verbosity=2)
