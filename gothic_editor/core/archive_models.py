"""Index VDF model names and load only the requested model's geometry."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from .mesh import read_3ds_bytes, read_mrm
from .vdf import VdfArchive, VdfEntry


class ArchiveModels:
    def __init__(self):
        self.entries: dict[str, VdfEntry] = {}
        self._catalogs = {}

    def refresh(self, project: Path, game: Path | None):
        self.entries = {}
        errors = []
        catalogs = {}
        # Project archives override game archives. Inactive Data/ModVDF mods
        # are deliberately excluded: selecting their load order needs a mod profile.
        groups = [[project / 'Data', project / 'Assets'], [game / 'Data'] if game else []]
        for directories in groups:
            archives = []
            paths = set()
            for directory in directories:
                if directory.is_dir():
                    paths.update(path for path in directory.iterdir()
                                 if path.is_file() and path.suffix.lower() == '.vdf')
            for path in sorted(paths):
                try:
                    stat = path.stat()
                    key = (path, stat.st_mtime_ns, stat.st_size)
                    archive = self._catalogs.get(key)
                    if archive is None:
                        archive = VdfArchive(path)
                    catalogs[key] = archive
                    archives.append(archive)
                except (OSError, ValueError) as exc:
                    errors.append(f'{path.name}: {exc}')
            for archive in sorted(archives, key=lambda item: (item.timestamp, item.path.name.lower()), reverse=True):
                for name, entry in archive.entries.items():
                    self.entries.setdefault(name, entry)
        self._catalogs = catalogs
        return errors

    def find(self, visual: str):
        name = visual.replace('\\', '/').rsplit('/', 1)[-1].lower()
        suffix = Path(name).suffix
        if suffix not in ('.3ds', '.mrm'):
            return None
        # Prefer an archived source mesh if present, then its compiled MRM.
        names = (name, str(Path(name).with_suffix('.mrm'))) if suffix == '.3ds' else (name,)
        return next((self.entries[candidate] for candidate in names if candidate in self.entries), None)


def load_archive_model(entry: VdfEntry):
    stat = entry.archive.stat()
    return _load_archive_model(entry, stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=8)
def _load_archive_model(entry: VdfEntry, modified: int, size: int):
    data = entry.read_bytes()
    if Path(entry.name).suffix.lower() == '.3ds':
        return read_3ds_bytes(data)
    return read_mrm(data)
