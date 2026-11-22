"""Regression tests for narrowly scoped resource refreshes."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from gothic_editor.app import EditorApp


class ResourceFastOperationsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.assets = root / 'Assets'
        self.assets.mkdir()
        self.repo = SimpleNamespace(root=root, options_cache={'item_actions': object()},
                                    resource_revision=12)
        self.app = SimpleNamespace(repo=self.repo, refresh=Mock())

    def notify(self, old=None, new=None):
        EditorApp._resource_files_changed(self.app, old, new)

    def test_markdown_rename_does_not_reload_entire_project(self):
        old = self.assets / 'Texts/Recipes/old.md'
        new = old.with_name('new.md')
        self.notify(old, new)
        self.app.refresh.assert_not_called()
        self.assertEqual(self.repo.options_cache, {})
        self.assertEqual(self.repo.resource_revision, 13)

    def test_document_copy_does_not_reload_hierarchy(self):
        self.notify(None, self.assets / 'Texts/Recipes/copy.md')
        self.app.refresh.assert_not_called()

    def test_script_not_in_compiled_content_only_invalidates_actions(self):
        self.notify(None, self.assets / 'Scripts/CustomAction.d')
        self.app.refresh.assert_not_called()
        self.assertEqual(self.repo.resource_revision, 13)

    def test_compiled_content_script_requires_index_refresh(self):
        self.notify(None, self.assets / 'Scripts/Content/Items/Item.d')
        self.app.refresh.assert_called_once_with(project_only=True)

    def test_game_item_and_model_changes_require_index_refresh(self):
        for name in ('Items/Potions/health.json', 'Models/hero.3ds'):
            with self.subTest(name=name):
                self.app.refresh.reset_mock()
                self.notify(self.assets / name, None)
                self.app.refresh.assert_called_once_with(project_only=True)


if __name__ == '__main__':
    unittest.main()
