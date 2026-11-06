"""Resolve an item's project resources and open files with user-selected tools."""
import os
import subprocess
import sys
from pathlib import Path

from .localization import tr
from .item_layout import ItemLayout


def item_resource_files(project: Path, instance: str):
    project = Path(project).resolve()
    if not instance or '/' in instance or '\\' in instance or instance in ('.', '..'):
        raise ValueError(tr('resources.invalid_folder'))
    folder = ItemLayout(project).find_folder(instance)
    if project not in folder.resolve().parents:
        raise ValueError(tr('resources.invalid_folder'))
    if not folder.is_dir():
        return folder, []
    files = [path for path in folder.rglob('*')
             if path.is_file() and folder.resolve() in path.resolve().parents]
    return folder, sorted(files, key=lambda path: path.relative_to(folder).as_posix().casefold())


def open_in_editor(path: Path, editor_path: str, project: Path):
    if not editor_path.strip():
        raise ValueError(tr('resources.editor_required'))
    editor = Path(editor_path).expanduser()
    if not editor.is_absolute():
        editor = project / editor
    if not editor.is_file():
        raise ValueError(tr('resources.editor_missing', path=str(editor)))
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    subprocess.Popen([str(editor.resolve()), str(path)], cwd=path.parent,
                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def open_in_folder(path: Path):
    folder = Path(path).resolve().parent
    if not folder.is_dir():
        raise FileNotFoundError(str(folder))
    if os.name == 'nt':
        os.startfile(str(folder))
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(folder)])
