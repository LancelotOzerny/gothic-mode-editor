"""Disk-backed edit history regression tests without a Gothic installation."""
from pathlib import Path
import tempfile
import unittest

from gothic_editor.core.edit_history import EditHistory


class EditHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.assets = self.project / 'Assets'
        self.assets.mkdir()
        self.history = EditHistory()
        self.history.reset(self.project)

    def test_edit_undo_redo_and_new_edit_clears_redo(self):
        path = self.assets / 'item.d'
        path.write_bytes(b'first')
        before = self.history.capture((path,))
        path.write_bytes(b'second')
        self.history.record(before)
        self.assertTrue(self.history.apply())
        self.assertEqual(path.read_bytes(), b'first')
        self.assertTrue(self.history.apply(redo=True))
        self.assertEqual(path.read_bytes(), b'second')
        self.history.apply()
        before = self.history.capture((path,))
        path.write_bytes(b'third')
        self.history.record(before)
        self.assertFalse(self.history.apply(redo=True))

    def test_copy_delete_and_move_directories(self):
        source = self.assets / 'Original'
        source.mkdir()
        (source / 'contents.d').write_bytes(b'data')
        destination = self.assets / 'Moved'
        before = self.history.capture((source,))
        source.rename(destination)
        self.history.record(before, (destination,))
        self.assertTrue(self.history.apply())
        self.assertEqual((source / 'contents.d').read_bytes(), b'data')
        self.assertFalse(destination.exists())
        self.assertTrue(self.history.apply(redo=True))
        self.assertFalse(source.exists())
        self.assertEqual((destination / 'contents.d').read_bytes(), b'data')

    def test_does_not_overwrite_external_changes(self):
        path = self.assets / 'item.d'
        path.write_bytes(b'old')
        before = self.history.capture((path,))
        path.write_bytes(b'new')
        self.history.record(before)
        path.write_bytes(b'external edit')
        with self.assertRaises(ValueError):
            self.history.apply()
        self.assertEqual(path.read_bytes(), b'external edit')

    def test_history_is_scoped_to_project(self):
        outside = self.project / 'outside.d'
        outside.write_bytes(b'original')
        with self.assertRaises(ValueError):
            self.history.capture((outside,))
        self.history.reset(self.project)
        self.assertFalse(self.history.apply())


if __name__ == '__main__':
    unittest.main()
