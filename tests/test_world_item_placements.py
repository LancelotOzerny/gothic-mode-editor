"""Round-trip and validation tests for project-local world item placements."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gothic_editor.core.world_item_placements import WorldItemPlacements


class WorldItemPlacementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = WorldItemPlacements(Path(self.temporary.name) / 'Project')

    def test_add_update_remove_and_reload(self):
        first = self.store.add('NEWWORLD.ZEN', 'ItFo_Apple', (1, 2.5, -3))
        second = self.store.add('OLDWORLD.ZEN', 'ItMi_Gold', (4, 5, 6), (0, 90, 0))
        reloaded = WorldItemPlacements(self.store.root)
        self.assertEqual(reloaded.list('newworld.zen'), [first])
        self.assertEqual(len(reloaded.list()), 2)
        changed = reloaded.update(first.id, position=(10, 20, 30), rotation=(0, 180, 0))
        self.assertEqual(changed.position, (10, 20, 30))
        self.assertEqual(changed.item, 'ItFo_Apple')
        self.assertEqual(reloaded.list('NEWWORLD.ZEN'), [changed])
        reloaded.remove(first.id)
        self.assertEqual(reloaded.list(), [second])

    def test_multiple_instances_of_same_item_are_independent(self):
        first = self.store.add('NEWWORLD.ZEN', 'ItFo_Apple', (0, 0, 0))
        second = self.store.add('NEWWORLD.ZEN', 'ItFo_Apple', (2, 0, 0))
        self.assertNotEqual(first.id, second.id)
        self.store.remove(first.id)
        self.assertEqual(self.store.list(), [second])

    def test_reject_invalid_coordinates_without_writing(self):
        for position in ((1, 2), (float('nan'), 0, 0), (True, 1, 2), ('1', 2, 3)):
            with self.subTest(position=position):
                with self.assertRaises(ValueError):
                    self.store.add('NEWWORLD.ZEN', 'ItFo_Apple', position)
        self.assertFalse(self.store.path.exists())

    def test_reject_corrupt_manifest_and_duplicate_ids(self):
        first = self.store.add('NEWWORLD.ZEN', 'ItFo_Apple', (0, 0, 0))
        data = json.loads(self.store.path.read_text(encoding='utf-8'))
        data['placements'].append(dict(data['placements'][0]))
        self.store.path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Повторяющиеся'):
            self.store.list()
        self.assertEqual(first.item, 'ItFo_Apple')

    def test_unknown_id_keeps_file_unchanged(self):
        self.store.add('NEWWORLD.ZEN', 'ItFo_Apple', (0, 0, 0))
        before = self.store.path.read_bytes()
        with self.assertRaises(ValueError):
            self.store.update('nonexistent', position=(1, 1, 1))
        with self.assertRaises(ValueError):
            self.store.remove('nonexistent')
        self.assertEqual(self.store.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
