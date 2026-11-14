"""Category forms share persistence; rune actions run only through spell casting."""
from pathlib import Path
import os
import tempfile
import unittest

from gothic_editor.core.categories import EDITABLE_CATEGORIES, classify, walk_categories
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.properties_schema import schema_for


class CategorySchemaTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('GOTHIC_TEST_COMPILER') and os.environ.get('GOTHIC_TEST_GAME'),
                         'Optional compilation against installed game sources')
    def test_new_category_defaults_compile_against_game(self):
        from gothic_editor.core.project_tools import ProjectTools
        from gothic_editor.core.compiler_sources import prepare_compiler_sources
        from gothic_editor.core.compiler_runner import run_compiler
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            repo=ProjectRepository()
            repo.create(root/'project','Test')
            for category in sorted(EDITABLE_CATEGORIES-{'potions','scrolls'}):
                repo.create_item(category)
            stage=root/'stage'
            stage.mkdir()
            content,manifest,_=ProjectTools(repo.root,Path(os.environ['GOTHIC_TEST_GAME']))._prepare(stage,lambda _:None)
            prepare_compiler_sources(content,lambda _:None)
            log=root/'compile.log'
            output=root/'Gothic.dat'
            result=run_compiler([os.environ['GOTHIC_TEST_COMPILER'],str(manifest),'--output-dat',str(output)],root,log)
            self.assertEqual(result.returncode,0,log.read_text('utf-8'))
            self.assertGreater(output.stat().st_size,0)

    def test_every_leaf_has_a_schema_and_roundtrips_without_losing_fields(self):
        leaves={category.key for category in walk_categories() if not category.children}
        self.assertEqual(EDITABLE_CATEGORIES, leaves)
        with tempfile.TemporaryDirectory() as temporary:
            repo=ProjectRepository()
            repo.create(Path(temporary)/'project','Test')
            for category in sorted(leaves-{'potions'}):
                with self.subTest(category=category):
                    schema=schema_for(category)
                    self.assertIsNotNone(schema)
                    item=repo.create_item(category)
                    self.assertEqual(classify(item), category)
                    item=repo.edit(item, {'value':'BASE + 7', 'custom':'UNKNOWN + 1'})
                    copied=repo.duplicate(item)
                    self.assertEqual(classify(copied), category)
                    repo.open(repo.root)
                    saved=next(value for value in repo.project_items if value.instance==item.instance)
                    self.assertEqual(saved.fields['custom'],'UNKNOWN + 1')
                    self.assertEqual(saved.fields['value'],'BASE + 7')
                    self.assertEqual(saved.fields['text[5]'],'NAME_Value')
                    repo.delete(copied)
            self.assertIsNone(schema_for('weapons'))
            self.assertIsNone(schema_for('../outside'))
