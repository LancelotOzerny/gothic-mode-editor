"""Invalidate loose compiled geometry supplied as source meshes by this mod."""
from pathlib import Path, PurePosixPath
from uuid import uuid4

from .artifact_transaction import publish_files
from .daedalus_merge import target_path


class MeshCache:
    def __init__(self, project, game):
        self.project = Path(project).resolve()
        self.game = Path(game).resolve()

    def plan(self, files):
        names = set()
        for filename in files:
            path = PurePosixPath(filename.replace('\\', '/').casefold())
            if (path.parts[:3] == ('_work', 'data', 'meshes') and path.suffix == '.3ds'
                    and '_compiled' not in path.parts and '..' not in path.parts):
                names.add(path.stem)
        if not names:return []
        folder = target_path(self.game, Path('_work/Data/Meshes/_compiled'))
        self._inside(folder, self.game)
        if not folder.is_dir():return []
        backup = self.project/'backups'/('mesh-cache-'+uuid4().hex)
        pairs = []
        removals = []
        for path in sorted(folder.iterdir()):
            if path.stem.casefold() not in names or path.suffix.casefold() not in ('.mrm', '.msh'):continue
            self._inside(path, self.game)
            if not path.is_file():continue
            destination = backup/path.relative_to(self.game)
            self._inside(destination, self.project)
            pairs.append((path, destination))
            removals.append((None, path))
        return pairs + removals

    @staticmethod
    def _inside(path, root):
        if root not in path.resolve().parents or path.is_symlink() or getattr(path,'is_junction',lambda:False)():
            raise ValueError(f'Небезопасный путь кэша модели: {path}')

    @staticmethod
    def report(pairs, log):
        for source, destination in pairs:
            if source is not None:
                log(f'Сброшен кэш модели: {source.name}. Резервная копия: {destination}')

    def invalidate(self, files, log):
        pairs = self.plan(files)
        if pairs:
            publish_files(pairs)
            self.report(pairs, log)
