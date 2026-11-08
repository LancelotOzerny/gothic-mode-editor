"""Persistent, most-recent-first project history independent of settings forms."""
import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RecentProject:
    path: Path
    name: str


class RecentProjects:
    LIMIT = 10

    def __init__(self, path: Path):
        self.path = Path(path)
        self.entries = []
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        if not isinstance(data, list):
            return
        seen = set()
        for entry in data:
            if (not isinstance(entry, dict) or not isinstance(entry.get('path'), str)
                    or not entry['path'].strip() or not isinstance(entry.get('name'), str)):
                continue
            try:
                project = Path(entry['path']).expanduser().resolve()
            except (OSError, ValueError):
                continue
            key = self._key(project)
            if key not in seen:
                self.entries.append(RecentProject(project, entry['name'] or project.name))
                seen.add(key)
            if len(self.entries) == self.LIMIT:
                break

    @staticmethod
    def _key(path):
        return os.path.normcase(str(path))

    def remember(self, path: Path, name: str):
        project = Path(path).resolve()
        entries = ([RecentProject(project, str(name))] +
                        [entry for entry in self.entries if self._key(entry.path) != self._key(project)])[:self.LIMIT]
        self._save(entries)

    def _save(self, entries):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps([{'path': str(entry.path), 'name': entry.name}
                                         for entry in entries], ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.path)
        self.entries = entries

    def parent_directory(self):
        if self.entries and self.entries[0].path.parent.is_dir():
            return self.entries[0].path.parent
        return None

    def forget(self, path: Path):
        """Remove only the history entry, never the project directory."""
        project = Path(path).resolve()
        entries = [entry for entry in self.entries if self._key(entry.path) != self._key(project)]
        self._save(entries)
