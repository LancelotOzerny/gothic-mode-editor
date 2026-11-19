"""Reading callbacks retain the original effect and append project actions in staging."""
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from gothic_editor.core.properties_schema import schema_for
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.project_tools import ProjectTools
from gothic_editor.core.scripts import parse_items
from gothic_editor.core.item_options import item_options
from gothic_editor.ui.panels.properties import PropertiesPanel
from test_function_actions import ActionFixture


class DocumentFixture(ActionFixture):
    def setUp(self):
        super().setUp()
        self.book_source=self.content/'Items/Books.d'
        self.book_source.write_text('''const int ITEM_KAT_DOCS = 2048;
var int Learned;
func void UseZweihandBuch() {
    if (Learned == 0) { TotalExp += 5; Learned = 1; };
};
INSTANCE ItWr_ZweihandBuch(C_Item) {
    name = "Book"; mainflag = ITEM_KAT_DOCS; custom = BASE + 42;
    on_state[0] = UseZweihandBuch; on_state[1] = Previous;
};
INSTANCE OtherBook(C_Item) { name = "Other"; mainflag = ITEM_KAT_DOCS; };
''',encoding='cp1251')
        self.repo.refresh()
        self.original=next(item for item in self.repo.game_items if item.instance=='ItWr_ZweihandBuch')
        self.book=self.repo.copy_to_project(self.original)


class DocumentBuildTests(DocumentFixture,unittest.TestCase):
    def test_import_without_actions_preserves_book_and_other_definitions(self):
        before=self.book_source.read_bytes()
        project=self.book.path.read_bytes()
        content,_,_=self.prepare()
        result=next(item for item in parse_items(content/'Items/Books.d','project')
                    if item.instance==self.book.instance)
        self.assertEqual(result.fields,self.original.fields)
        self.assertEqual(self.book_source.read_bytes(),before)
        self.assertEqual(self.book.path.read_bytes(),project)
        self.assertIn('OtherBook',(content/'Items/Books.d').read_text('cp1251'))
        self.assertIn('Learned = 1',(content/'Items/Books.d').read_text('cp1251'))

    def test_reading_actions_keep_original_and_add_parameters_once(self):
        item=self.assign(self.book,75)
        before=item.path.read_bytes()
        game=self.book_source.read_bytes()
        content,manifest,_=self.prepare()
        staged=next(item for item in parse_items(content/'Items/Books.d','project')
                    if item.instance==self.book.instance)
        handler='GE_ItemActions_'+item.instance
        self.assertEqual(staged.fields['on_state[0]'],handler)
        self.assertEqual(staged.fields['on_state[1]'],'Previous')
        self.assertEqual(staged.fields['custom'],'BASE + 42')
        generated=(content/'Items/GE_ComponentPotions.d').read_text('cp1251')
        self.assertIn('UseZweihandBuch();',generated)
        self.assertIn('AddExperience(75);',generated)
        self.assertLess(generated.index('UseZweihandBuch();'),generated.index('AddExperience(75);'))
        self.assertEqual(generated.count('UseZweihandBuch();'),1)
        self.assertEqual(item.path.read_bytes(),before)
        self.assertEqual(self.book_source.read_bytes(),game)
        self.assertNotIn('spellFxInstanceNames',generated)
        self.repo.edit(item,{},metadata={'item_actions':'[]'})
        content,_,_=self.prepare()
        staged=next(item for item in parse_items(content/'Items/Books.d','project')
                    if item.instance==self.book.instance)
        self.assertEqual(staged.fields['on_state[0]'],'UseZweihandBuch')

    def test_new_document_actions_without_original(self):
        item=self.repo.create_item_from_fields('ItWr_New',{'name':'"New"','mainflag':'ITEM_KAT_DOCS'})
        self.assign(item,100)
        content,_,_=self.prepare()
        staged=parse_items(content/'Items/GE_Generated/ItWr_New.d','project')[0]
        self.assertEqual(staged.fields['on_state[0]'],'GE_ItemActions_ItWr_New')
        self.assertTrue(any(field.key=='item_actions' for section in schema_for('documents').sections
                            for field in section.fields))


class OriginalActionUITests(DocumentFixture,unittest.TestCase):
    def test_book_and_potion_source_callbacks_visible_without_metadata_writes(self):
        window=tk.Tk()
        self.addCleanup(window.destroy)
        form=PropertiesPanel(window,lambda *args,**kwargs:self.fail('Opening must not save'),
                             options_provider=lambda source:item_options(self.repo,source))
        form.pack()
        form.show(self.book)
        self.assertIn('item_actions',form.inputs)
        def displayed():
            def descendants(widget):
                yield widget
                for child in widget.winfo_children():yield from descendants(child)
            return [widget.get() for widget in descendants(form.original_actions) if isinstance(widget,tk.Entry)]
        self.assertTrue(any('UseZweihandBuch' in value for value in displayed()))
        self.assertFalse(form.editor.dirty)
        potion=self.repo.edit(self.item,{'on_state[0]':'UseItPo_Speed'})
        form.show(potion)
        self.assertTrue(any('UseItPo_Speed' in value for value in displayed()))
        self.assertNotIn('item_actions',potion.editor_metadata)
        form.show(self.item)  # Same schema reuses widgets; stale callback must disappear.
        self.assertIsNone(form.original_actions)
        self.assertFalse(form.editor.dirty)
        form.show(self.book)
        self.assertTrue(any('UseZweihandBuch' in value for value in displayed()))
        self.assertTrue(form.save(automatic=True))


class InstalledBookTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('GOTHIC_TEST_GAME') and os.environ.get('GOTHIC_TEST_COMPILER'),
                         'Requires installed scripts and compiler')
    def test_actual_book_and_speed_potion_compile_without_changing_game(self):
        from gothic_editor.core.compiler_runner import run_compiler
        with tempfile.TemporaryDirectory(prefix='document actions ') as temporary:
            root=Path(temporary)
            repo=ProjectRepository()
            repo.create(root/'project','Reading test')
            repo.game=Path(os.environ['GOTHIC_TEST_GAME'])
            repo.refresh()
            originals=[next(item for item in repo.game_items if item.instance.casefold()==name)
                       for name in ('itwr_zweihandbuch','itpo_speed')]
            sources={item.path:item.path.read_bytes() for item in originals}
            function=repo.root/'Assets/Scripts/Actions/Learn.d'
            function.parent.mkdir()
            function.write_text('func void GE_TestLearn(var int amount) { };','utf-8')
            copies=[repo.copy_to_project(item) for item in originals]
            for item in copies:
                repo.edit(item,{},metadata={'item_actions':json.dumps([{
                    'id':'project:Assets/Scripts/Actions/Learn.d#GE_TestLearn','values':{'amount':'5'}}])})
            stage=root/'stage'
            stage.mkdir()
            content,manifest,_=ProjectTools(repo.root,repo.game)._prepare(stage,lambda _:None)
            generated=(content/'Items/GE_ComponentPotions.d').read_text('cp1251')
            self.assertEqual(generated.count('UseZweihandBuch();'),1)
            self.assertEqual(generated.count('UseItPo_Speed();'),1)
            from gothic_editor.core.compiler_sources import prepare_compiler_sources
            prepare_compiler_sources(content,lambda _:None)
            output=root/'Gothic.dat'
            log=root/'compiler.log'
            try:
                result=run_compiler([os.environ['GOTHIC_TEST_COMPILER'],str(manifest),'--output-dat',str(output)],
                                    content.parent,log)
                self.assertEqual(result.returncode,0,log.read_text('utf-8'))
                self.assertTrue(output.stat().st_size)
            finally:
                for path,before in sources.items():self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
