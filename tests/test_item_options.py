"""Animation restrictions using temporary scripts; no working property schema is read."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gothic_editor.core.item_options import item_options
from gothic_editor.core.potion_components import PotionComponents
from gothic_editor.core.potion_schemes import imported_potion_scheme
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.properties_schema import PropertiesSchema
from gothic_editor.core.scripts import parse_items


class ItemOptionsTests(unittest.TestCase):
    def test_only_two_schemes_even_when_other_items_have_custom_schemes(self):
        repo=SimpleNamespace(game_items=[SimpleNamespace(fields={'scemename':'"FOOD"'})],
                             project_items=[SimpleNamespace(fields={'scemename':'"CUSTOM"'})])
        self.assertEqual(item_options(repo,'item_schemes'),[
            ('Выпить','"POTION"'),('Выпить быстро','"POTIONFAST"')])

    def test_import_normalizes_unknown_values_to_first_option(self):
        for value in ('"FOOD"','CUSTOM_SCHEME','""'):
            self.assertEqual(imported_potion_scheme(value),'"POTION"')
        self.assertEqual(imported_potion_scheme(' "potionfast" '),'"POTIONFAST"')

    def test_import_preserves_source_unknown_fields_and_callback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            source=root/'Original.d'
            code=('func void Consume() {};\n'
                  'INSTANCE ItPo_Imported(C_Item) { name="Test"; scemeName="FOOD"; '
                  'custom=KEEP + 3; on_state[0]=Consume; };\n'
                  'INSTANCE Sibling(C_Item) { name="Sibling"; };')
            source.write_text(code,encoding='cp1251')
            before=source.read_bytes()
            original=parse_items(source,'game')[0]
            store=PotionComponents(root/'project')
            file=store.import_item(original)
            saved=json.loads(file.read_text('utf-8'))
            self.assertEqual(file.name,'ItPo_Imported.json')
            self.assertEqual(saved['fields']['scemename'],'"POTION"')
            self.assertEqual(saved['fields']['custom'],'KEEP + 3')
            self.assertEqual(saved['fields']['on_state[0]'],'Consume')
            self.assertEqual(store.list_items()[0].fields['scemename'],'"POTION"')
            self.assertEqual(source.read_bytes(),before)

    def test_missing_imported_scheme_is_not_added(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            source=root/'Original.d'
            source.write_text('INSTANCE ItPo_Imported(C_Item) { name="Test"; };',encoding='utf-8')
            store=PotionComponents(root/'project')
            store.import_item(parse_items(source,'game')[0])
            self.assertNotIn('scemename',store.list_items()[0].fields)

    def test_new_item_uses_fast_scheme_with_synthetic_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo=ProjectRepository()
            repo.create(Path(temporary)/'project','Test')
            schema=PropertiesSchema((),generated_defaults={'scemeName':'"FOOD"'},instance_prefix='ItPo_')
            with patch('gothic_editor.core.project.schema_for',return_value=schema):
                item=repo.create_item('potions')
            self.assertEqual(item.fields['scemename'],'"POTIONFAST"')
