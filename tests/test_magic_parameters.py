"""Mana costs must be editable without touching the installed game."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from gothic_editor.core.magic_parameters import (
    discover_mana_cost, import_mana_metadata, apply_magic_costs)
from gothic_editor.core.scripts import parse_items, with_item_metadata


class MagicParameterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.game = self.root/'game'
        self.project = self.root/'project'
        self.staging = self.root/'staging'
        for directory in (self.game/'Items', self.project/'Assets/Scripts/Content/Items',
                          self.staging/'Items'):
            directory.mkdir(parents=True)
        self.constants = 'const int SPL_Cost_Fireball = 5;\nconst int SPL_Cost_Scroll = 5;\n'
        for base in (self.game, self.staging):
            (base/'Constants.d').write_text(self.constants, encoding='utf-8')
        self.item_path = self.game/'Items/Runes.d'
        self.item_path.write_text(
            'INSTANCE ItRu_Fireball(C_Item) {\n'
            'mainflag = ITEM_KAT_RUNE;\nspell = SPL_Fireball;\n};\n', encoding='utf-8')
        self.item = parse_items(self.item_path, 'game')[0]
        self.repo = SimpleNamespace(options_cache={}, _game_content=lambda:self.game)

    def test_import_detects_original_cost_and_preserves_original_game(self):
        metadata = discover_mana_cost(self.repo, self.item)
        self.assertEqual(metadata['magic_cost'], '5')
        self.assertEqual(metadata['magic_cost_symbol'], 'SPL_Cost_Fireball')
        self.assertEqual(metadata['magic_cost_original'], '5')
        imported = self.project/'Assets/Scripts/Content/Items/Runes.d'
        imported.write_text(import_mana_metadata(self.repo, self.item), 'utf-8')
        self.assertEqual(parse_items(imported, 'project')[0].editor_metadata, metadata)
        self.assertEqual(apply_magic_costs(self.project,self.staging), [])
        self.assertEqual((self.game/'Constants.d').read_text(),self.constants)

    def test_changed_cost_updates_only_staging(self):
        metadata = discover_mana_cost(self.repo, self.item)
        metadata['magic_cost'] = '12'
        imported = self.project/'Assets/Scripts/Content/Items/Runes.d'
        imported.write_text(with_item_metadata(self.item.text,metadata),'utf-8')
        modified = apply_magic_costs(self.project,self.staging)
        self.assertEqual(modified,[self.staging/'Constants.d'])
        self.assertIn('SPL_Cost_Fireball = 12;', (self.staging/'Constants.d').read_text())
        self.assertIn('SPL_Cost_Fireball = 5;', (self.game/'Constants.d').read_text())

    def test_invalid_cost_and_missing_constant_fail(self):
        path = self.project/'Assets/Scripts/Content/Items/Runes.d'
        meta = discover_mana_cost(self.repo,self.item)
        meta['magic_cost'] = '-5'
        path.write_text(with_item_metadata(self.item.text,meta),'utf-8')
        with self.assertRaisesRegex(ValueError,'расход маны'):
            apply_magic_costs(self.project,self.staging)
        meta['magic_cost'] = '12'
        meta['magic_cost_symbol'] = 'SPL_Cost_NotFound'
        path.write_text(with_item_metadata(self.item.text,meta),'utf-8')
        with self.assertRaisesRegex(ValueError,'не найдена'):
            apply_magic_costs(self.project,self.staging)

    def test_conflicting_shared_cost_is_rejected(self):
        first = self.item.text
        second = first.replace('ItRu_Fireball','ItRu_Fireball2')
        meta = {'magic_cost_symbol':'SPL_Cost_Scroll','magic_cost_original':'5'}
        path = self.project/'Assets/Scripts/Content/Items/Runes.d'
        path.write_text(with_item_metadata(first,{**meta,'magic_cost':'8'})+'\n'+
                        with_item_metadata(second,{**meta,'magic_cost':'9'}),'utf-8')
        with self.assertRaisesRegex(ValueError,'Разный расход'):
            apply_magic_costs(self.project,self.staging)


if __name__ == '__main__':
    unittest.main()
