"""Embedded location workspace regression tests."""
import tkinter as tk
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.ui.windows.world_preview import WorldPreviewPanel


class EmbeddedLocationModeTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        from gothic_editor.core.settings import SettingsStore
        self.settings_patch = patch('gothic_editor.app.SettingsStore',
                                    return_value=SettingsStore(Path(self.temp.name) / 'settings.json'))
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        try:
            self.app = EditorApp()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(self.app.destroy)
        self.app.withdraw()
        self.app.repo.create(Path(self.temp.name) / 'mod', 'Test')
        self.app.show_project()

    def test_location_mode_embedded_and_restores_normal_layout(self):
        self.app._switch_resource_browser('locations')
        self.assertEqual(self.app._resource_browser, 'locations')
        panel = self.app.location_viewer
        self.assertIsInstance(panel, WorldPreviewPanel)
        self.assertIs(panel.master, self.app.editor_middle)
        self.assertEqual(self.app.editor_panes.panecget(self.app.editor_sidebar, 'hide'), '1')
        self.assertEqual(self.app.editor_panes.panecget(self.app.editor_inspector, 'hide'), '1')
        self.assertFalse(panel._fly_mode)  # Reliable initial overview, not empty fly camera.
        self.app._switch_resource_browser('items')
        self.assertEqual(self.app.editor_panes.panecget(self.app.editor_sidebar, 'hide'), '0')
        self.assertEqual(self.app.editor_panes.panecget(self.app.editor_inspector, 'hide'), '0')
        self.app._switch_resource_browser('locations')
        self.assertIs(self.app.location_viewer, panel)


if __name__ == '__main__':
    unittest.main()
