import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.core.localization import Localization, localization, tr
from gothic_editor.core.settings import EditorSettings, SettingsStore, field_key, validate_value
from gothic_editor.core.settings_schema import SettingsCatalog, all_fields


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_language_discovery_fallback_and_formatting(self):
        (self.root / 'ru.json').write_text(json.dumps({
            'language': {'code': 'ru', 'name': 'Russian'},
            'title': 'Default', 'greeting': 'Hello {name}',
        }), encoding='utf-8')
        (self.root / 'en.json').write_text(json.dumps({
            'language': {'code': 'en', 'name': 'English'}, 'title': 'Settings',
        }), encoding='utf-8')
        (self.root / 'bad.json').write_bytes(b'\xff')
        language = Localization(self.root)
        self.assertEqual(set(language.available_languages()), {'ru', 'en'})
        language.set_language('en')
        self.assertEqual(language.tr('title'), 'Settings')
        self.assertEqual(language.tr('greeting', name='Editor'), 'Hello Editor')
        self.assertEqual(language.tr('missing'), 'missing')
        self.assertEqual(language.set_language('unknown'), 'ru')

    def test_settings_round_trip_includes_shared_resources(self):
        store = SettingsStore(self.root / 'settings.json')
        settings = EditorSettings({'interface.general.window_size': [1400, 900],
                                   'resources.gothic.game_path': 'private/game/path'})
        store.save(settings)
        self.assertEqual(store.load().get_value('interface.general.window_size'), [1400, 900])
        self.assertEqual(store.load().get_value('resources.gothic.game_path'), '')
        self.assertFalse(store.path.with_suffix('.tmp').exists())

    def test_invalid_saved_value_falls_back_without_losing_valid_values(self):
        store = SettingsStore(self.root / 'settings.json')
        store.path.write_text(json.dumps({'interface.general.window_size': ['bad', 900],
                                          'interface.general.language': 'ru'}), encoding='utf-8')
        settings = store.load()
        self.assertEqual(settings.get_value('interface.general.window_size'), [1240, 760])
        self.assertEqual(settings.get_value('interface.general.language'), 'ru')
        store.path.write_bytes(b'\xff')
        self.assertEqual(store.load().values, {})

    def test_invalid_value_does_not_overwrite_settings_file(self):
        store = SettingsStore(self.root / 'settings.json')
        store.save(EditorSettings())
        previous = store.path.read_bytes()
        with self.assertRaises(ValueError):
            store.save(EditorSettings({'interface.general.window_size': [0, 900]}))
        self.assertEqual(store.path.read_bytes(), previous)

    def test_hierarchy_mode_persists_and_unknown_value_falls_back(self):
        key='project.hierarchy.display_mode'
        store=SettingsStore(self.root/'settings.json')
        self.assertEqual(store.load().get_value(key),'project_over_original')
        store.save(EditorSettings({key:'project_only'}))
        self.assertEqual(store.load().get_value(key),'project_only')
        store.path.write_text(json.dumps({key:'unknown'}),encoding='utf-8')
        self.assertEqual(store.load().get_value(key),'project_over_original')

    def test_catalog_extension_and_invalid_type(self):
        path = self.root / 'catalog.json'
        data = {'sections': [{'code': 'extra', 'name': 'extra.title'}], 'settings': [
            {'section_code': 'extra', 'code': 'general', 'name': 'extra.general', 'items': [
                {'code': 'enabled', 'name': 'extra.enabled', 'title': 'extra.hint',
                 'type': 'boolean', 'default': True}]}]}
        path.write_text(json.dumps(data), encoding='utf-8')
        catalog = SettingsCatalog()
        catalog.connect(path)
        field = catalog.fields()[0]
        self.assertEqual(field_key(field), 'extra.general.enabled')
        self.assertTrue(validate_value(field, EditorSettings().get(field)))
        data['settings'][0]['items'][0]['type'] = 'unsupported'
        path.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaises(ValueError):
            SettingsCatalog().connect(path)

    def test_all_literal_translation_keys_exist(self):
        import ast
        for path in Path('gothic_editor').rglob('*.py'):
            tree = ast.parse(path.read_text('utf-8'))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == 'tr' and node.args and isinstance(node.args[0], ast.Constant)):
                    key = node.args[0].value
                    self.assertIsNotNone(Localization._value(localization.languages['ru'], key), (path, key))
        for field in all_fields():
            for key in (field.label_key, field.title_key):
                self.assertNotEqual(tr(key), key)


class SettingsWindowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = SettingsStore(self.root / 'user-settings.json')
        self.store_patch = patch('gothic_editor.app.SettingsStore', return_value=self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        try:
            self.app = EditorApp()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(self.app.destroy)
        self.app.withdraw()
        self.app.update_idletasks()
        self.addCleanup(localization.set_language, 'ru')

    def open_dialog(self, resources=False):
        self.app.show_settings()
        window = self.app.settings_window
        window.withdraw()
        if resources:
            window.navigation.selection_clear(0, 'end')
            window.navigation.selection_set(1)
            window.show_category()
        window.update_idletasks()
        return window

    def test_single_window_cancel_and_save(self):
        window = self.open_dialog()
        self.app.show_settings()
        self.assertIs(self.app.settings_window, window)
        window.values['interface.general.window_size'][0].set('1450')
        window.destroy()
        self.assertFalse(self.store.path.exists())
        window = self.open_dialog()
        self.assertEqual(window.values['interface.general.window_size'][0].get(), '1240')
        window.values['interface.general.window_size'][0].set('1450')
        window.save()
        self.assertFalse(window.winfo_exists())
        self.assertEqual(self.store.load().get_value('interface.general.window_size'), [1450, 760])

    def test_invalid_input_keeps_dialog_and_settings_unchanged(self):
        window = self.open_dialog()
        window.values['interface.general.window_size'][0].set('bad')
        with patch('gothic_editor.ui.settings.messagebox.showerror') as error:
            window.save()
        error.assert_called_once()
        self.assertTrue(window.winfo_exists())
        self.assertFalse(self.store.path.exists())

    def test_hierarchy_mode_switches_visible_items_without_losing_project_drafts(self):
        from tkinter import ttk
        self.app.repo.create(self.root/'project','Test')
        item=self.app.repo.create_item('potions')
        content=self.root/'game/_work/Data/Scripts/Content/Items'
        content.mkdir(parents=True)
        (content/'IT_Test.d').write_text('INSTANCE ItPo_Original(C_Item) { name="Original"; };',encoding='utf-8')
        self.app.repo.set_game_path(str(self.root/'game'))
        self.app._remember_project()
        self.app.show_project()
        self.app.select(item)
        self.app.properties.inputs['name'].delete(0,'end')
        self.app.properties.inputs['name'].insert(0,'Draft')
        self.assertEqual(len(self.app.hierarchy.items),2)
        window=self.open_dialog()
        index=next(i for i,category in enumerate(window.categories) if category.key=='project')
        window.navigation.selection_clear(0,'end')
        window.navigation.selection_set(index)
        window.show_category()
        frame=next(child for child in window.content.winfo_children() if isinstance(child,tk.LabelFrame))
        self.assertEqual(frame.cget('text'),'Окно иерархии')
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        combo=next(child for child in descendants(frame) if isinstance(child,ttk.Combobox))
        self.assertEqual(str(combo['state']),'readonly')
        self.assertEqual(tuple(combo['values']),('Только проект','Проект поверх оригинала'))
        combo.current(0)
        combo.event_generate('<<ComboboxSelected>>')
        window.save()
        self.assertEqual(self.app.hierarchy.items,self.app.repo.project_items)
        self.assertEqual(self.app.properties.inputs['name'].get(),'Draft')
        self.assertEqual(self.store.load().get_value('project.hierarchy.display_mode'),'project_only')
        self.app.repo.refresh()
        self.app.update_hierarchy()
        self.assertEqual(self.app.hierarchy.items,self.app.repo.project_items)
        window=self.open_dialog()
        window.values['project.hierarchy.display_mode'][0].set('project_over_original')
        window.save()
        self.assertEqual(len(self.app.hierarchy.items),2)
        original=self.app.repo.game_items[0]
        self.app.select(original)
        window=self.open_dialog()
        window.values['project.hierarchy.display_mode'][0].set('project_only')
        window.save()
        self.assertIsNone(self.app.current)
        self.assertEqual(self.app.hierarchy.items,self.app.repo.project_items)

    def test_resource_connect_disconnect_and_unchanged_path_does_not_rescan(self):
        self.app.repo.create(self.root / 'mod', 'Test')
        self.app.show_project()
        game = self.root / 'game'
        game.mkdir()
        window = self.open_dialog(resources=True)
        window.values['resources.gothic.game_path'][0].set(str(game))
        window.save()
        self.assertEqual(self.app.repo.game, game.resolve())
        config = self.root / 'mod' / 'project.json'
        self.assertEqual(json.loads(config.read_text('utf-8'))['settings']['resources.gothic.game_path'], str(game.resolve()))
        self.assertEqual(json.loads(config.read_text('utf-8'))['game_path'], '')
        window = self.open_dialog(resources=True)
        with patch.object(self.app.repo, 'refresh') as refresh:
            window.save()
        refresh.assert_not_called()
        window = self.open_dialog(resources=True)
        window.values['resources.gothic.game_path'][0].set('')
        window.save()
        self.assertIsNone(self.app.repo.game)
        self.assertEqual(json.loads(config.read_text('utf-8'))['game_path'], '')

    def test_invalid_resource_path_does_not_save_any_changes(self):
        self.app.repo.create(self.root / 'mod', 'Test')
        window = self.open_dialog(resources=True)
        window.values['resources.gothic.game_path'][0].set(str(self.root / 'missing'))
        with patch('gothic_editor.ui.settings.messagebox.showerror') as error:
            window.save()
        error.assert_called_once()
        self.assertIsNone(self.app.repo.game)
        self.assertFalse(self.store.path.exists())

    def test_shared_paths_can_be_set_before_opening_and_apply_to_every_project(self):
        game, compiler, editor = self.root/'game', self.root/'compiler.dll', self.root/'editor.exe'
        game.mkdir()
        compiler.write_bytes(b'compiler')
        editor.write_bytes(b'editor')
        window = self.open_dialog(resources=True)
        for key,value in [('resources.gothic.game_path',game),('build.compiler.path',compiler),
                          ('resources.editor.path',editor)]:
            window.values[key][0].set(str(value))
        window.save()
        self.assertFalse(window.winfo_exists())
        for name in ('First', 'Second'):
            path = self.root/name
            self.app.repo.create(path,name)
            self.assertEqual(self.app.repo.game,game)
            self.assertEqual(self.app.repo.compiler_path,str(compiler))
            self.assertEqual(self.app.repo.resource_editor_path,str(editor))
            data = json.loads((path/'project.json').read_text('utf-8'))
            self.assertNotIn('compiler_path',data)
        # An explicit legacy project game path takes precedence over global defaults.
        legacy = self.root/'Legacy'
        legacy.mkdir()
        config = {'name':'Legacy','game_path':str(self.root/'other-game'),'compiler_path':'old.dll'}
        (legacy/'project.json').write_text(json.dumps(config),encoding='utf-8')
        self.app.open_project_path(legacy)
        self.assertEqual(self.app.repo.game,self.root/'other-game')
        self.assertEqual(self.app.repo.compiler_path,str(compiler))
        self.assertEqual(json.loads((legacy/'project.json').read_text('utf-8')),config)

    def test_legacy_paths_are_adopted_once_and_can_be_cleared_globally(self):
        game = self.root/'legacy-game'
        game.mkdir()
        legacy = self.root/'Legacy'
        legacy.mkdir()
        config = {'name':'Legacy','game_path':str(game)}
        (legacy/'project.json').write_text(json.dumps(config),encoding='utf-8')
        self.app.open_project_path(legacy)
        self.assertEqual(self.app.repo.game,game)
        window = self.open_dialog(resources=True)
        window.values['resources.gothic.game_path'][0].set('')
        window.save()
        self.app.open_project_path(legacy)
        self.assertIsNone(self.app.repo.game)
        self.assertEqual(json.loads((legacy/'project.json').read_text('utf-8'))['settings']['resources.gothic.game_path'],'')

    def test_language_change_keeps_selection_drafts_and_search(self):
        self.app.repo.create(self.root / 'mod', 'Test')
        item = self.app.repo.create_item('potions')
        self.app.show_project()
        self.app.select(item)
        self.app.hierarchy.search.set('GE_')
        self.app.properties.inputs['name'].delete(0, 'end')
        self.app.properties.inputs['name'].insert(0, '"Unsaved name"')
        window = self.open_dialog()
        languages = dict(localization.languages)
        self.addCleanup(setattr, localization, 'languages', languages)
        localization.languages['en'] = {'language': {'code': 'en', 'name': 'English'},
                                        'app': {'file': 'File'}}
        window.values['interface.general.language'][0].set('en')
        window.save()
        self.assertEqual(self.app.main_menu.entrycget(1, 'label'), 'File')
        self.assertEqual(self.app.current.instance, item.instance)
        self.assertEqual(self.app.properties.inputs['name'].get(), '"Unsaved name"')
        self.assertEqual(self.app.hierarchy.search.get(), 'GE_')
        self.assertNotEqual(self.app.repo.items[0].title, 'Unsaved name')


if __name__ == '__main__':
    unittest.main()
