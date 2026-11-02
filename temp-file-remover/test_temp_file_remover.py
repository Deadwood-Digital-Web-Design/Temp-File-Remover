import os
import tempfile
import time
import unittest
from pathlib import Path

import temp_file_remover as t


def make_old(path, hours_old):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 100)
    ts = time.time() - hours_old * 3600
    os.utime(path, (ts, ts))


class TempFileRemoverTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.targets = {"Test": self.root}

    def tearDown(self):
        self._tmp.cleanup()

    def test_scan_skips_new_files(self):
        make_old(self.root / "old.tmp", 48)
        make_old(self.root / "new.tmp", 1)
        names = [i.path.name for i in t.scan(self.targets, 24)]
        self.assertEqual(names, ["old.tmp"])

    def test_delete_removes_files_and_empty_dirs(self):
        make_old(self.root / "sub" / "deep" / "a.tmp", 48)
        items = t.scan(self.targets, 24)
        freed, deleted, failed = t.delete_items(items, self.targets)
        self.assertEqual((freed, deleted, failed), (100, 1, []))
        self.assertFalse((self.root / "sub").exists())
        self.assertTrue(self.root.exists())  # root itself is never removed

    def test_refuses_files_outside_targets(self):
        with tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "keep.txt"
            make_old(outside, 48)
            item = t.Item(outside, 100, outside.stat().st_mtime, "Test")
            _, deleted, failed = t.delete_items([item], self.targets)
            self.assertEqual(deleted, 0)
            self.assertEqual(len(failed), 1)
            self.assertTrue(outside.exists())

    @unittest.skipIf(os.name == "nt", "symlinks need admin on Windows")
    def test_symlinks_are_ignored(self):
        make_old(self.root / "real.tmp", 48)
        (self.root / "link.tmp").symlink_to(self.root / "real.tmp")
        names = sorted(i.path.name for i in t.scan(self.targets, 24))
        self.assertEqual(names, ["real.tmp"])

    def test_human_size(self):
        self.assertEqual(t.human_size(500), "500 B")
        self.assertEqual(t.human_size(2048), "2.0 KB")


if __name__ == "__main__":
    unittest.main()
