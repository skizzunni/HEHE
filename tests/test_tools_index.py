import glob
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ToolsIndex(unittest.TestCase):
    def test_every_tool_listed(self):
        with open(os.path.join(ROOT, "tools", "README.md")) as fh:
            idx = fh.read()
        missing = [os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "tools", "*.py")) + glob.glob(os.path.join(ROOT, "tools", "*.sh"))
                   if f"`{os.path.basename(p)}`" not in idx]
        self.assertEqual(missing, [], "add these to tools/README.md")


if __name__ == "__main__":
    unittest.main()
