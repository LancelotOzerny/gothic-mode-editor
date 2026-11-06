import json
import os
import shutil
import subprocess
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from time import monotonic
from unittest.mock import patch

from gothic_editor.app import EditorApp
from gothic_editor.core.project import ProjectRepository
from gothic_editor.core.project_tools import ProjectTools, ToolResult
from gothic_editor.core.settings import SettingsStore
from gothic_editor.core.scripts import parse_items


class ProjectToolsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='gothic tools ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'project'
        self.game = self.root / 'game'
        self.source = self.project / 'Scripts/Content'
        self.target = self.game / '_work/Data/Scripts/Content'
        for content in (self.source, self.target):
            (content / 'Items').mkdir(parents=True)
        (self.target / 'Gothic.src').write_text('Items\\IT_*.d\n', encoding='utf-8')
        (self.target / 'Items/IT_Test.d').write_bytes(b'const int TEST_VALUE = 1;')
        (self.target / 'Items/IT_Other.d').write_bytes(b'const int OTHER_VALUE = 3;')
        (self.source / 'Items/IT_Test.d').write_bytes(b'const int TEST_VALUE = 2;')
        (self.source / 'Items/GE_Generated').mkdir()
        (self.source / 'Items/GE_Generated/GE_New.d').write_bytes(b'INSTANCE GE_NEW (C_Item) { name = "New"; };')
        self.compiler = self.root / 'DaedalusCompiler/DaedalusCompiler.dll'
        self.compiler.parent.mkdir()
        self.compiler.write_bytes(b'test compiler')
        self.tools = ProjectTools(self.project, self.game, str(self.compiler))

    def test_single_item_override_preserves_siblings_and_helpers_in_build_and_sync(self):
        original=('const int SHARED = 100;\n'
                  'INSTANCE ITMI_FIRST (C_Item) { name = "First"; };\n'
                  'INSTANCE ITMI_SECOND (C_Item) { name = "Second"; };\n'
                  'func void Helper() {};\n')
        game_file=self.target/'Items/IT_Test.d'
        game_file.write_text(original,encoding='utf-8')
        (self.source/'Items/IT_Test.d').unlink()
        (self.project/'project.json').write_text(json.dumps({'name':'Test','game_path':str(self.game)}),encoding='utf-8')
        repository=ProjectRepository()
        repository.open(self.project)
        first=next(item for item in repository.game_items if item.instance=='ITMI_FIRST')
        copied=repository.copy_to_project(first)
        repository.edit(copied,{'name':'"Edited"'})
        self.assertNotIn('ITMI_SECOND',copied.path.read_text('utf-8-sig'))
        self.tools.build_dir.mkdir()
        with tempfile.TemporaryDirectory(dir=self.tools.build_dir) as temporary:
            content,_,_=self.tools._prepare(Path(temporary),lambda _:None)
            staged=content/'Items/IT_Test.d'
            items=parse_items(staged,'project')
            self.assertEqual([(item.instance,item.title) for item in items],
                             [('ITMI_FIRST','Edited'),('ITMI_SECOND','Second')])
            self.assertIn('const int SHARED = 100;',staged.read_text('utf-8-sig'))
            self.assertIn('func void Helper()',staged.read_text('utf-8-sig'))
        self.assertEqual(game_file.read_text('utf-8'),original)
        self.tools.synchronize()
        self.assertEqual([(item.instance,item.title) for item in parse_items(game_file,'game')],
                         [('ITMI_FIRST','Edited'),('ITMI_SECOND','Second')])
        self.assertIn('const int SHARED = 100;',game_file.read_text('utf-8-sig'))
        self.assertIn('func void Helper()',game_file.read_text('utf-8-sig'))

    def test_sync_overlays_sources_and_backs_up_before_overwrite(self):
        result = self.tools.synchronize()
        self.assertEqual(result.files, 3)
        self.assertEqual((self.target / 'Items/IT_Test.d').read_bytes(), b'const int TEST_VALUE = 2;')
        self.assertEqual((self.target / 'Items/IT_Other.d').read_bytes(), b'const int OTHER_VALUE = 3;')
        self.assertEqual((self.target / 'Items/GE_Generated/GE_New.d').read_bytes(), b'INSTANCE GE_NEW (C_Item) { name = "New"; };')
        self.assertEqual((result.backup / 'Items/IT_Test.d').read_bytes(), b'const int TEST_VALUE = 1;')
        self.assertIn('Items\\GE_Generated\\GE_New.d', (self.target / 'Gothic.src').read_text('utf-8-sig'))
        self.assertFalse((self.game / '_work/Data/Scripts/_compiled/Gothic.dat').exists())
        again = self.tools.synchronize()
        self.assertEqual(again.files, 0)
        self.assertIsNone(again.backup)

    def test_compile_uses_staged_overlay_and_preserves_game_and_project_sources(self):
        before = {path.relative_to(self.game): path.read_bytes() for path in self.game.rglob('*') if path.is_file()}
        environment = os.environ.get('DOTNET_ROLL_FORWARD')

        def compile_command(command, **kwargs):
            manifest = Path(command[2])
            self.assertEqual((manifest.parent / 'Items/IT_Test.d').read_bytes(), b'const int TEST_VALUE = 2;')
            self.assertEqual((manifest.parent / 'Items/IT_Other.d').read_bytes(), b'const int OTHER_VALUE = 3;')
            text = manifest.read_text('utf-8-sig')
            self.assertEqual(text.count('Items\\GE_Generated\\GE_New.d'), 1)
            self.assertEqual(command[3], '--output-dat')
            self.assertEqual(kwargs['env']['DOTNET_ROLL_FORWARD'], 'Major')
            self.assertNotIn('shell', kwargs)
            kwargs['stdout'].write('Test.d:1: warning W5: uninitialized attribute\n'
                                   'Other.d:2: warning W1: expression hack\n2 warnings generated.\n')
            Path(command[4]).write_bytes(b'compiled dat')
            return subprocess.CompletedProcess(command, 0)

        with patch('gothic_editor.core.project_tools.shutil.which', return_value='dotnet'), \
                patch('gothic_editor.core.compiler_runner.subprocess.run', side_effect=compile_command):
            result = self.tools.compile()
        self.assertEqual(result.output.read_bytes(), b'compiled dat')
        self.assertEqual(result.warnings,2)
        after = {path.relative_to(self.game): path.read_bytes() for path in self.game.rglob('*') if path.is_file()}
        self.assertEqual(before, after)
        self.assertEqual((self.source / 'Items/IT_Test.d').read_bytes(), b'const int TEST_VALUE = 2;')
        self.assertEqual(os.environ.get('DOTNET_ROLL_FORWARD'), environment)
        self.assertEqual(sorted(path.name for path in self.tools.build_dir.iterdir()),
                         ['Gothic.dat', 'compile.log', 'diagnostics.json', 'stderr.log', 'stdout.log'])

    def test_failed_compilation_cannot_succeed_using_previous_output(self):
        self.tools.build_dir.mkdir()
        output = self.tools.build_dir / 'Gothic.dat'
        output.write_bytes(b'last successful build')
        for code in (0, 1):
            with self.subTest(code=code), patch('gothic_editor.core.project_tools.shutil.which', return_value='dotnet'), \
                    patch('gothic_editor.core.compiler_runner.subprocess.run', return_value=subprocess.CompletedProcess([], code)):
                with self.assertRaises(ValueError):
                    self.tools.compile()
            self.assertEqual(output.read_bytes(), b'last successful build')

    def test_crash_retains_sources_and_separate_process_diagnostics(self):
        def crash(command, **kwargs):
            kwargs['stdout'].write('Index was outside the bounds of the array.\n')
            kwargs['stderr'].write('compiler stderr\n')
            return subprocess.CompletedProcess(command, 1)

        with patch('gothic_editor.core.project_tools.shutil.which', return_value='dotnet'), \
                patch('gothic_editor.core.compiler_runner.subprocess.run', side_effect=crash):
            with self.assertRaises(ValueError):
                self.tools.compile()
        staging = next(self.tools.build_dir.glob('compile-*'))
        metadata = json.loads((staging / 'diagnostics.json').read_text('utf-8'))
        self.assertEqual(metadata['returncode'], 1)
        self.assertEqual(metadata['environment']['DOTNET_ROLL_FORWARD'], 'Major')
        self.assertEqual(metadata['command'][2], str(staging / 'Content/Gothic.src'))
        self.assertEqual(metadata['cwd'], str(staging))
        self.assertTrue((staging / 'Content/Items/IT_Test.d').is_file())
        self.assertIn('Index was outside', (staging / 'stdout.log').read_text('utf-8'))
        self.assertEqual((staging / 'stderr.log').read_text('utf-8'), 'compiler stderr\n')
        log = (self.tools.build_dir / 'compile.log').read_text('utf-8')
        self.assertIn('Index was outside', log)
        self.assertIn('compiler stderr', log)

    def test_process_launch_error_retains_diagnostics(self):
        with patch('gothic_editor.core.project_tools.shutil.which', return_value='dotnet'), \
                patch('gothic_editor.core.compiler_runner.subprocess.run', side_effect=OSError('launch failed')):
            with self.assertRaisesRegex(OSError, 'launch failed'):
                self.tools.compile()
        staging = next(self.tools.build_dir.glob('compile-*'))
        metadata = json.loads((staging / 'diagnostics.json').read_text('utf-8'))
        self.assertIn('launch failed', metadata['exception'])
        self.assertTrue((staging / 'Content/Gothic.src').is_file())

    def test_compiler_autodetection_and_missing_runtime(self):
        self.assertEqual(ProjectTools(self.project, self.game).compiler_command()[-1], str(self.compiler))
        with patch('gothic_editor.core.project_tools.shutil.which', return_value=None):
            with self.assertRaises(ValueError):
                self.tools.compiler_command()
        with self.assertRaises(ValueError):
            ProjectTools(self.project, None)
        with self.assertRaises(ValueError):
            ProjectTools(self.project, self.project)

    def test_sync_rolls_back_when_copy_fails(self):
        original_copy = shutil.copy2

        def copy(source, target, *args, **kwargs):
            target = Path(target)
            if target == self.target / 'Items/IT_Test.d' and self.tools.build_dir in Path(source).parents:
                target.write_bytes(b'partial write')
                raise OSError('Disk write error')
            return original_copy(source, target, *args, **kwargs)

        with patch('gothic_editor.core.project_tools.shutil.copy2', side_effect=copy):
            with self.assertRaises(OSError):
                self.tools.synchronize()
        self.assertEqual((self.target / 'Items/IT_Test.d').read_bytes(), b'const int TEST_VALUE = 1;')
        self.assertFalse((self.target / 'Items/GE_Generated/GE_New.d').exists())

    def test_nested_manifests_and_wildcards_do_not_include_script_twice(self):
        (self.target / 'Gothic.src').write_text('Items\\Items.src\n', encoding='utf-8')
        (self.target / 'Items/Items.src').write_text('IT_*.d\nGE_Generated\\*.d\n', encoding='utf-8')
        self.tools.synchronize()
        self.assertNotIn('GE_New.d', (self.target / 'Gothic.src').read_text('utf-8-sig'))

    def test_project_configuration_preserves_metadata_and_compiler(self):
        repository = ProjectRepository()
        config = {'name': 'Test', 'game_path': str(self.game), 'custom': {'keep': True}}
        (self.project / 'project.json').write_text(json.dumps(config), encoding='utf-8')
        repository.open(self.project)
        repository.set_configuration(str(self.game), str(self.compiler))
        repository.set_game_path('')
        saved = json.loads((self.project / 'project.json').read_text('utf-8'))
        self.assertEqual(saved['compiler_path'], str(self.compiler))
        self.assertEqual(saved['custom'], {'keep': True})


class ToolbarTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        with patch('gothic_editor.app.SettingsStore', return_value=SettingsStore(self.root / 'settings.json')):
            try:
                self.app = EditorApp()
            except tk.TclError as exc:
                self.skipTest(str(exc))
        self.addCleanup(self.app.destroy)
        self.app.withdraw()

    def test_compiler_setting_is_rendered_and_saved_with_project(self):
        self.app.repo.create(self.root / 'project', 'Test')
        compiler = self.root / 'DaedalusCompiler.dll'
        compiler.write_bytes(b'compiler')
        self.app.show_settings()
        window = self.app.settings_window
        window.navigation.selection_clear(0, 'end')
        window.navigation.selection_set(2)
        window.show_category()
        window.values['build.compiler.path'][0].set(str(compiler))
        window.save()
        self.assertFalse(window.winfo_exists())
        self.assertEqual(self.app.repo.compiler_path, str(compiler))
        config = json.loads((self.app.repo.root / 'project.json').read_text('utf-8'))
        self.assertNotIn('compiler_path', config)
        self.assertEqual(self.app.settings_store.load().get_value('build.compiler.path'), str(compiler))

    def test_buttons_are_centered_disabled_without_project_and_job_log_is_responsive(self):
        self.assertEqual(self.app.play_button.cget('state'), 'disabled')
        self.assertEqual(self.app.play_button.master.grid_info()['column'], 1)
        self.app.repo.create(self.root / 'project', 'Test')
        game = self.root / 'game'
        (game / '_work/Data/Scripts/Content').mkdir(parents=True)
        self.app.repo.set_game_path(str(game))
        self.app.show_project()
        self.assertEqual(self.app.play_button.cget('state'), 'normal')
        output = self.root / 'project/build/Gothic.dat'
        with patch('gothic_editor.app.ProjectTools.compiler_command', return_value=['compiler']), \
                patch('gothic_editor.app.ProjectTools.compile', return_value=ToolResult(output)):
            self.app.play_button.invoke()
            self.assertEqual(self.app.play_button.cget('state'), 'disabled')
            window = self.app.terminal
            deadline = monotonic() + 5
            while self.app._tool_runner.running and monotonic() < deadline:
                self.app.update()
            self.assertFalse(self.app._tool_runner.running)
            self.assertEqual(self.app.play_button.cget('state'), 'normal')
            self.assertIn('Gothic.dat', window.log.get('1.0', 'end'))
            self.app.hide_terminal()


if __name__ == '__main__':
    unittest.main()
