"""Discover Gothic ZEN levels inside VDF without extracting entire archives."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gothic_editor.core.vdf import VdfArchive, VdfEntry
from gothic_editor.core.world_preview import available_locations, is_location_zen, load_world_wireframe
from test_models import write_vdf


class ArchivedLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game = self.root / 'Gothic2'

    def test_archive_locations_are_listed_without_loading_contents(self):
        path = write_vdf(self.game / 'Data' / 'Worlds.vdf',
                         {'NEWWORLD.ZEN': b'fake-world',
                          'OLDWORLD.ZEN': b'another',
                          'Lensflare.zen': b'presets'})
        self.assertEqual(len(VdfArchive(path).entries), 0)
        choices = available_locations(self.game)
        self.assertEqual([entry.name.casefold() for entry in choices],
                         ['newworld.zen', 'oldworld.zen'])
        self.assertTrue(all(isinstance(entry, VdfEntry) for entry in choices))
        self.assertTrue(all(is_location_zen(entry) for entry in choices))
        self.assertFalse(is_location_zen('Lensflare.zen'))

    def test_loose_file_wins_over_archive_duplicate(self):
        write_vdf(self.game / 'Data' / 'Worlds.vdf', {'NEWWORLD.ZEN': b'archived'})
        folder = self.game / '_work' / 'data' / 'Worlds'
        folder.mkdir(parents=True)
        local = folder / 'NEWWORLD.ZEN'
        local.write_bytes(b'local')
        self.assertEqual(available_locations(self.game), [local])

    def test_loading_archived_member_does_not_modify_game(self):
        archive = write_vdf(self.game / 'Data' / 'Worlds.vdf',
                            {'NEWWORLD.ZEN': b'not-a-valid-zen'})
        entry = available_locations(self.game)[0]
        original = archive.read_bytes()
        with self.assertRaises(ValueError):
            load_world_wireframe(entry)
        self.assertEqual(archive.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
