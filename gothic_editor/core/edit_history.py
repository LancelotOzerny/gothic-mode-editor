"""Bounded, project-local undo/redo for resource changes."""
from dataclasses import dataclass
from pathlib import Path
import shutil

MAX_ENTRY_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 30


class HistoryTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class Snapshot:
    files: tuple
    directories: tuple
    # A missing path is distinct from an empty directory.
    exists: bool


class EditHistory:
    def __init__(self):
        self.root = None
        self.undo_stack = []
        self.redo_stack = []

    def reset(self, project):
        self.root = (Path(project).resolve() / 'Assets') if project else None
        self.undo_stack.clear()
        self.redo_stack.clear()

    def _path(self, path):
        if self.root is None:
            raise ValueError('Проект не открыт')
        path = Path(path).absolute()
        if path != self.root and self.root not in path.parents:
            raise ValueError('История доступна только для ресурсов проекта')
        return path

    def _snapshot(self, path):
        path = self._path(path)
        if not path.exists():
            return Snapshot((), (), False)
        if path.is_symlink():
            raise ValueError('История не поддерживает символические ссылки')
        if path.is_file():
            if path.stat().st_size > MAX_ENTRY_BYTES:
                raise HistoryTooLarge('Файл слишком велик для истории изменений')
            return Snapshot(((Path('.'), path.read_bytes()),), (), True)
        files, directories, total = [], [Path('.')], 0
        for entry in path.rglob('*'):
            if entry.is_symlink() or getattr(entry, 'is_junction', lambda: False)():
                raise ValueError('История не поддерживает ссылки внутри папок')
            relative = entry.relative_to(path)
            if entry.is_dir():
                directories.append(relative)
            elif entry.is_file():
                size = entry.stat().st_size
                total += size
                if total > MAX_ENTRY_BYTES:
                    raise HistoryTooLarge('Папка слишком велика для истории изменений')
                files.append((relative, entry.read_bytes()))
        return Snapshot(tuple(files), tuple(directories), True)

    def capture(self, paths):
        try:
            return {self._path(path): self._snapshot(path) for path in paths}
        except HistoryTooLarge:
            self.undo_stack.clear()
            self.redo_stack.clear()
            return None

    def record(self, before, extra=()):
        if self.root is None or before is None:
            return False
        before = dict(before)
        for path in extra:
            path = self._path(path)
            if path not in before:
                before[path] = Snapshot((), (), False)
        after = self.capture(before)
        if after is None:return False
        changes = tuple((path, original, after[path]) for path, original in before.items()
                        if original != after[path])
        if not changes:
            return False
        self.undo_stack.append(changes)
        del self.undo_stack[:-MAX_ENTRIES]
        self.redo_stack.clear()
        return True

    def _restore(self, path, snapshot):
        path = self._path(path)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        if not snapshot.exists:
            return
        if snapshot.directories:
            for relative in sorted(snapshot.directories, key=lambda item: len(item.parts)):
                (path / relative).mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
        for relative, content in snapshot.files:
            destination = path if relative == Path('.') else path / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)

    def apply(self, redo=False):
        stack = self.redo_stack if redo else self.undo_stack
        if not stack:
            return False
        changes = stack[-1]
        # An external edit must never be silently overwritten.
        for path, before, after in changes:
            if self._snapshot(path) != (before if redo else after):
                raise ValueError('Ресурс изменился вне истории. Обновите проект.')
        # Roll back if writing any of the snapshots fails.
        restored = []
        try:
            for path, before, after in reversed(changes):
                self._restore(path, after if redo else before)
                restored.append((path, before if redo else after))
        except OSError:
            for path, state in reversed(restored):
                self._restore(path, state)
            raise
        stack.pop()
        (self.undo_stack if redo else self.redo_stack).append(changes)
        return True
