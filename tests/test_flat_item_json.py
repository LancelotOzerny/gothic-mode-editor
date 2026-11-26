"""Flat JSON item layout and lossless legacy-project migration."""
import json
import tempfile
import unittest
from pathlib import Path

from gothic_editor.core.item_migration import ItemMigrationService
from gothic_editor.core.project import ProjectRepository


class FlatItemJsonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'mod'
        self.repo = ProjectRepository()
        self.repo.create(self.root, 'Mod')

    def test_create_duplicate_rename_delete_use_only_json(self):
        first = self.repo.create_item('potions')
        folder = self.root / 'Assets/Items/Potions'
        self.assertEqual(first.path, folder / f'{first.instance}.json')
        self.assertEqual(set(folder.iterdir()), {first.path})
        copy = self.repo.duplicate(first)
        self.assertEqual(copy.path.parent, folder)
        renamed = self.repo.edit(copy, {'value': '123'}, instance='ItPo_Renamed')
        self.assertEqual(renamed.path, folder / 'ItPo_Renamed.json')
        self.assertEqual(renamed.fields['value'], '123')
        self.assertFalse(copy.path.exists())
        self.repo.delete(first)
        self.assertEqual(set(folder.iterdir()), {renamed.path})
        self.repo.open(self.root)
        self.assertEqual([item.instance for item in self.repo.project_items], ['ItPo_Renamed'])

    def test_old_item_with_informational_files_is_backed_up_and_flattened(self):
        item = self.repo.create_item('potions')
        legacy = self.root / 'Assets/Items/Potions' / item.instance
        legacy.mkdir()
        item.path.rename(legacy / 'item.json')
        (legacy / 'functions.d').write_text('// only comments', 'utf-8')
        (legacy / 'functions.json').write_text(json.dumps({'source_functions': []}), 'utf-8')
        (legacy / 'params.json').write_text(json.dumps({'variables': [], 'source_constants': []}), 'utf-8')
        self.assertEqual(ItemMigrationService(self.root).pending(), [legacy])
        self.repo.open(self.root, confirm_migration=lambda count: count == 1)
        self.assertFalse(legacy.exists())
        self.assertTrue(item.path.exists())
        backups = list((self.root / 'backups').glob('item-migration-*'))
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / 'Assets/Items/Potions' / item.instance / 'functions.d').exists())

    def test_scripted_legacy_item_is_not_deleted(self):
        item = self.repo.create_item('potions')
        legacy = self.root / 'Assets/Items/Potions' / item.instance
        legacy.mkdir()
        item.path.rename(legacy / 'item.json')
        (legacy / 'functions.d').write_text('func void Custom() {};', 'utf-8')
        with self.assertRaisesRegex(ValueError, 'пользовательские функции'):
            ItemMigrationService(self.root).migrate()
        self.assertTrue((legacy / 'item.json').is_file())
        self.assertFalse(item.path.exists())

    def test_build_uses_flat_json_without_sidecar_code(self):
        first = self.repo.create_item('potions')
        replacements, additions, helpers = self.repo.components.generated()
        self.assertEqual(replacements, {})
        self.assertEqual(len(additions), 1)
        self.assertIn(first.instance, additions[0])
        self.assertEqual(helpers, [])
