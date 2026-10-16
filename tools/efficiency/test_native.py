import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from native import window
class NativeTests(unittest.TestCase):
 def test_disabled_original(self):self.assertEqual(window({}),272000)
 def test_advisory_unmodified(self):self.assertEqual(window({'CLAUDEX_EFFICIENCY':'advisory'}),272000)
 def test_adaptive_64k(self):self.assertEqual(window({'CLAUDEX_EFFICIENCY':'adaptive'}),64000)
 def test_custom_target(self):self.assertEqual(window({'CLAUDEX_EFFICIENCY':'adaptive','CLAUDEX_EFFICIENCY_TARGET_TOKENS':'48000'}),48000)
 def test_large_read_exception(self):self.assertEqual(window({'CLAUDEX_EFFICIENCY':'adaptive','CLAUDEX_EFFICIENCY_LARGE_READ':'1'}),192000)
 def test_invalid_range_rejected(self):
  with self.assertRaises(ValueError):window({'CLAUDEX_EFFICIENCY':'adaptive','CLAUDEX_EFFICIENCY_TARGET_TOKENS':'400'})
 def test_outside_mode_never_applies_override(self):self.assertEqual(window({'CLAUDEX_EFFICIENCY':'off','CLAUDEX_EFFICIENCY_LARGE_READ':'1'}),272000)
if __name__=='__main__':unittest.main(verbosity=2)
