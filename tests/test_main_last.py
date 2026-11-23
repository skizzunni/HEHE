import glob
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


class MainBlockLast(unittest.TestCase):
    def test_no_test_class_after_main(self):
        """A class below `unittest.main()` is skipped when its file is run
        directly (2026-11-23: ten files had appended classes after it)."""
        bad = []
        for f in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
            s = open(f).read()
            i = s.find('if __name__ == "__main__":')
            if i >= 0 and re.search(r"^class \w+", s[i:], re.M):
                bad.append(os.path.basename(f))
        self.assertEqual(bad, [], "move the __main__ block to the end of these files")


if __name__ == "__main__":
    unittest.main()
