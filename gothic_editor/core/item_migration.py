"""Backed-up migration from per-item directories to flat JSON files."""
import json
import shutil
from uuid import uuid4

from .item_layout import ItemLayout
from .scripts import mask_comments


class ItemMigrationService:
    def __init__(self, project):
        self.layout = ItemLayout(project)

    def pending(self):
        result = []
        for path in self.layout.legacy_files():
            self.layout.checked(path)
            data = json.loads(path.read_text('utf-8'))
            if data.get('format') == 'gothic-potion-v1':
                result.append(path.parent)
        return result

    @staticmethod
    def _check_sidecars(source):
        """Never silently discard executable sidecar data."""
        functions = source / 'functions.d'
        if functions.is_file() and mask_comments(functions.read_text('utf-8')).strip():
            raise ValueError(f'{functions}: перенесите пользовательские функции в Assets/Scripts перед миграцией.')
        for filename, array in (('params.json', 'variables'), ('functions.json', 'source_functions')):
            metadata = source / filename
            if not metadata.exists():
                continue
            values = json.loads(metadata.read_text('utf-8'))
            if filename == 'params.json':
                if values.get('variables') or any(value.get('override') for value in values.get('source_constants', [])):
                    raise ValueError(f'{metadata}: перенесите объявления и переопределения в скрипты перед миграцией.')
            elif any(value.get('override') for value in values.get(array, [])):
                raise ValueError(f'{metadata}: сначала перенесите переопределения функций в скрипты.')

    def migrate(self):
        sources = self.pending()
        if not sources:
            return None
        self.layout.root.mkdir(parents=True, exist_ok=True)
        destinations = {}
        for source in sources:
            self._check_sidecars(source)
            for path in source.rglob('*'):
                self.layout.checked(path)
            data = json.loads((source / 'item.json').read_text('utf-8'))
            destination = self.layout.path_for(data['instance'])
            key = destination.name.casefold()
            if key in destinations or destination.exists():
                raise ValueError(f'Миграция остановлена: предмет уже существует: {destination.name}')
            destinations[key] = (source, destination)

        backup = self.layout.project / 'backups' / ('item-migration-' + uuid4().hex)
        # Copy everything before removing any old directory.
        for source in sources:
            relative = source.relative_to(self.layout.project)
            shutil.copytree(source, backup / relative)
        written = []
        try:
            for source, destination in destinations.values():
                shutil.copy2(source / 'item.json', destination)
                written.append(destination)
        except Exception:
            for destination in written:
                destination.unlink(missing_ok=True)
            raise
        # The complete original tree survives in backups, including notes and assets.
        for source in sources:
            shutil.rmtree(source)
        return backup
