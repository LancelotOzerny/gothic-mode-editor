"""Markdown document layout and staging-only Daedalus generation."""
import tempfile
import unittest
from pathlib import Path

from gothic_editor.core.document_pages import (
    document_files, load_document, paginate, render_document,
)
from gothic_editor.core.document_build import apply_documents
from gothic_editor.core.daedalus_merge import definitions


class DocumentPagesTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.project = self.root / 'Project'
        self.content = self.root / 'Stage'
        self.documents = self.project / 'Assets/Texts/Documents'
        self.scripts = self.project / 'Assets/Scripts/Content/Items'
        self.documents.mkdir(parents=True)
        self.scripts.mkdir(parents=True)
        self.content.mkdir()

    def text(self, name='healing.md', content='# Настой\n\nТрава и вода.'):
        file = self.documents / name
        file.write_text(content, 'utf-8')
        return file.relative_to(self.project).as_posix()

    def stage(self, instance='ITWR_RECIPE', metadata=None, original_callback=''):
        import json
        metadata = metadata or {}
        raw = ('instance ' + instance + '(C_Item) {\n'
               '  // @GE_METADATA ' + json.dumps(metadata) + '\n'
               '  mainflag = ITEM_KAT_DOCS;\n'
               '  visual = "ItWr_Book_01.3ds";\n' +
               ('  on_state[0] = ' + original_callback + ';\n' if original_callback else '') +
               '};\n')
        file = self.scripts / 'Docs.d'
        file.write_text(raw, 'cp1251')
        target = self.content / 'Docs.d'
        target.write_text(raw, 'cp1251')
        return target

    def test_choices_and_reading(self):
        path = self.text()
        self.assertEqual(document_files(self.project), (path,))
        self.assertIn('# Настой', load_document(self.project, path))
        with self.assertRaisesRegex(ValueError, 'Недоступный'):
            load_document(self.project, '../secret.md')

    def test_nested_text_files_are_listed_and_loaded(self):
        nested = self.project / 'Assets/Texts/Recepts/Potions/recept-potions-exp-100.md'
        nested.parent.mkdir(parents=True)
        nested.write_text('# Эссенция опыта\n\nМандибулы полевого хищника.', 'utf-8')
        reference = nested.relative_to(self.project).as_posix()
        self.assertIn(reference, document_files(self.project))
        self.assertIn('Мандибулы', load_document(self.project, reference))

    def test_text_paths_outside_assets_texts_are_rejected(self):
        self.text()
        outside = self.project / 'Assets/Other/hidden.md'
        outside.parent.mkdir(parents=True)
        outside.write_text('# Не документ', 'utf-8')
        self.assertNotIn('Assets/Other/hidden.md', document_files(self.project))
        with self.assertRaisesRegex(ValueError, 'Недоступный'):
            load_document(self.project, 'Assets/Other/hidden.md')
        with self.assertRaisesRegex(ValueError, 'Недоступный'):
            load_document(self.project, 'Assets/Texts/../Other/hidden.md')

    def test_document_schema_exposes_markdown_picker(self):
        from gothic_editor.core.properties_schema import schema_for
        schema = schema_for('documents')
        fields = [field for section in schema.sections for field in section.fields]
        selected = next(field for field in fields if field.key == 'document_text')
        self.assertEqual(selected.source, 'editor_metadata')
        self.assertEqual(selected.options_source, 'document_texts')

    def test_title_and_paragraph_generate_document(self):
        script = render_document('ITWR_RECIPE', '# Рецепт\n\nСмешайте траву и воду.', book=True)
        self.assertIn('Doc_SetPages(doc, 1);', script)
        self.assertIn('Book_Mage_L.tga', script)
        self.assertIn('FONT_BookHeadline', script)
        self.assertIn('FONT_Book', script)
        self.assertIn('Doc_PrintLines(doc, 0, "Смешайте траву и воду.")', script)
        self.assertEqual(len(definitions(script)), 1)

    def test_two_pages_and_overflow(self):
        raw = '# Страница\n\n' + ' '.join(['трава'] * 42)
        # A long paragraph is supported only when it fits a single page in v1.
        self.assertEqual(len(paginate(raw)), 1)
        long = ('# Заголовок\n\n' + ' '.join(['трава'] * 40) + '\n\n') * 4
        with self.assertRaisesRegex(ValueError, 'двух страниц'):
            paginate(long)

    def test_apply_documents_changes_staging_only(self):
        path = self.text()
        target = self.stage(metadata={'document_text': path})
        original = target.read_bytes()
        changed = apply_documents(self.project, self.content)
        self.assertEqual(len(changed), 1)
        self.assertIn('GE_ShowDocument_ITWR_RECIPE', target.read_text('cp1251'))
        self.assertEqual((self.scripts / 'Docs.d').read_bytes(), original)
        generated = (self.content / changed[0]).read_text('cp1251')
        self.assertIn('Doc_Show(doc);', generated)

    def test_selected_actions_are_kept(self):
        path = self.text()
        import json
        target = self.stage(metadata={
            'document_text': path,
            'item_actions': json.dumps([{'id': 'recipe:learn#GE_LearnRecipe', 'values': {'recipe': '123'}}])
        })
        changed = apply_documents(self.project, self.content)
        generated = (self.content / changed[0]).read_text('cp1251')
        self.assertIn('GE_ItemActions_ITWR_RECIPE();', generated)

    def test_missing_document_blocks_generation(self):
        target = self.stage(metadata={'document_text': 'Assets/Texts/Documents/missing.md'})
        before = target.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Недоступный'):
            apply_documents(self.project, self.content)
        self.assertEqual(target.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
