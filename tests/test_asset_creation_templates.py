"""Template creation for project scripts and Markdown recipe books."""
import tempfile
import unittest
from pathlib import Path

from gothic_editor.core.asset_files import AssetFiles
from gothic_editor.core.document_pages import document_files


class AssetCreationTemplateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name)
        self.files = AssetFiles(self.project)
        (self.project / 'Assets/Scripts').mkdir(parents=True)
        (self.project / 'Assets/Texts/Recipes').mkdir(parents=True)

    def test_script_has_daedalus_action_template(self):
        script = self.files.create(self.project/'Assets/Scripts', 'MyAction', script=True)
        self.assertEqual(script.name, 'MyAction.d')
        self.assertEqual(script.read_text('utf-8'),
                         '// @INFO NAME="MyAction"\n\n'
                         'func void MyAction()\n'
                         '{\n'
                         '    // your script code\n'
                         '};\n')

    def test_script_names_are_valid_daedalus_identifiers(self):
        for name in ('invalid script', '1test.d', 'script-name.d', 'Книга.d'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.files.create(self.project/'Assets/Scripts', name, script=True)
        self.assertEqual(list((self.project/'Assets/Scripts').iterdir()), [])

    def test_markdown_documents_are_listed_by_recipe_picker(self):
        file = self.files.create(self.project/'Assets/Texts/Recipes', 'essence.md', markdown=True)
        self.assertEqual(file.read_text('utf-8'), '# Название\n\n')
        self.assertIn('Assets/Texts/Recipes/essence.md', document_files(self.project))
        with self.assertRaises(FileExistsError):
            self.files.create(file.parent, file.name, markdown=True)

    def test_markdown_cannot_be_created_outside_texts(self):
        with self.assertRaisesRegex(ValueError, 'Assets/Texts'):
            self.files.create(self.project/'Assets/Scripts', 'bad.md', markdown=True)


if __name__ == '__main__':
    unittest.main()
