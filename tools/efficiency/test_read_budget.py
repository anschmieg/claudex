import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from read_budget import Read, target


class Tests(unittest.TestCase):
    def test_small_read(self):
        self.assertEqual(target(Read('Read', 1000, 10000)), 256000)

    def test_large_read(self):
        self.assertEqual(target(Read('Read', 50000, 230000)), 768000)

    def test_exact_fit(self):
        self.assertEqual(target(Read('Read', 100000, 636000)), 768000)

    def test_overflow_explicitly_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exceeding expanded'):
            target(Read('Read', 400000, 550000))

    def test_unknown_tool(self):
        self.assertEqual(target(Read('Bash', 100000, 50000)), 256000)

    def test_invalid(self):
        for read in (Read('Read', -1, 0), Read('Read', True, 0),
                     Read('Read', 0, -1), Read('Read', 1.5, 0)):
            with self.subTest(read=read), self.assertRaises(ValueError):
                target(read)
        with self.assertRaises(ValueError):
            target(Read('Read', 100, 200), normal=256000, expanded=100000)


if __name__ == '__main__':
    unittest.main(verbosity=2)
