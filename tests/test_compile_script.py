"""PowerShell build control flow, without launching Tk or running PyInstaller."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows PowerShell required')
class CompileScriptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='compile script ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copy2(Path(__file__).resolve().parents[1] / 'compile.ps1', self.root)
        (self.root / 'main.py').write_text('', 'utf-8')
        (self.root / 'assets').mkdir()
        self.python_root = self.root / 'Python with spaces'
        for folder, filename in [('tcl8.6', 'init.tcl'), ('tk8.6', 'tk.tcl')]:
            target = self.python_root / 'tcl' / folder / filename
            target.parent.mkdir(parents=True)
            target.write_text('', 'utf-8')
        self.modules = self.root / 'fake modules'
        self.modules.mkdir()
        (self.modules / 'sitecustomize.py').write_text('''
import os, sys, types
from pathlib import Path
sys.base_prefix = os.environ['TEST_PYTHON_ROOT']
tk = types.ModuleType('tkinter')
class Tk:
    def __init__(self):
        mode = os.environ['TEST_TK_MODE']
        expected = str(Path(sys.base_prefix) / 'tcl' / 'tcl8.6')
        if mode == 'broken' or (mode == 'fallback' and os.environ.get('TCL_LIBRARY') != expected):
            raise RuntimeError('probe failed: Tcl/Tk unavailable')
        if mode == 'clean' and (os.environ.get('TCL_LIBRARY') or os.environ.get('TK_LIBRARY')):
            raise RuntimeError('stale environment not removed')
    def withdraw(self):pass
    def update_idletasks(self):pass
    def destroy(self):pass
tk.Tk = Tk
sys.modules['tkinter'] = tk
''', 'utf-8')
        package = self.modules / 'PyInstaller'
        package.mkdir()
        (package / '__init__.py').write_text('', 'utf-8')
        (package / '__main__.py').write_text('''
from pathlib import Path
import sys
destination = Path(sys.argv[sys.argv.index('--distpath') + 1])
destination.mkdir(parents=True, exist_ok=True)
(destination / 'GothicEditor.exe').write_bytes(b'fake build')
''', 'utf-8')

    def run_build(self, mode, stale=False):
        environment = dict(os.environ, PYTHONPATH=str(self.modules),
                           TEST_PYTHON_ROOT=str(self.python_root), TEST_TK_MODE=mode)
        for variable in ('TCL_LIBRARY', 'TK_LIBRARY', 'VIRTUAL_ENV'):
            environment.pop(variable, None)
        if stale:
            for variable in ('TCL_LIBRARY', 'TK_LIBRARY'):
                path = self.root / '_MEI12345' / variable
                path.mkdir(parents=True)
                environment[variable] = str(path)
        return subprocess.run([
            'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(self.root / 'compile.ps1'), '-Python', sys.executable,
        ], cwd=self.modules, env=environment, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=30)

    def test_normal_probe_and_build_with_spaces_and_different_working_directory(self):
        result = self.run_build('clean')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / 'dist/GothicEditor.exe').is_file())

    def test_failed_probe_reaches_fallback_in_powershell_51(self):
        result = self.run_build('fallback')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Tcl:', result.stdout)
        self.assertIn('Tk:', result.stdout)

    def test_stale_frozen_environment_is_removed(self):
        result = self.run_build('clean', stale=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('Ignoring stale TCL_LIBRARY', result.stdout)
        self.assertIn('Ignoring stale TK_LIBRARY', result.stdout)

    def test_unavailable_tk_reports_diagnostic_instead_of_traceback(self):
        result = self.run_build('broken')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('probe failed: Tcl/Tk unavailable', result.stderr)
        self.assertIn('Tcl/Tk is still unavailable', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertFalse((self.root / 'dist/GothicEditor.exe').exists())

    def test_locked_executable_fails_before_packaging_and_remains_intact(self):
        import ctypes
        from ctypes import wintypes
        executable = self.root / 'dist/GothicEditor.exe'
        executable.parent.mkdir()
        executable.write_bytes(b'previous build')
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create_file.restype = wintypes.HANDLE
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        # Deny sharing to reproduce a locked output without launching an EXE.
        handle = create_file(str(executable), 0x80000000, 0, None, 3, 0, None)
        self.assertNotEqual(handle, wintypes.HANDLE(-1).value, ctypes.get_last_error())
        try:
            result = self.run_build('clean')
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('close all GothicEditor windows', result.stderr)
            self.assertNotIn('Python:', result.stdout)
        finally:
            close_handle(handle)
        self.assertEqual(executable.read_bytes(), b'previous build')
        result = self.run_build('clean')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(executable.read_bytes(), b'fake build')


if __name__ == '__main__':
    unittest.main()
