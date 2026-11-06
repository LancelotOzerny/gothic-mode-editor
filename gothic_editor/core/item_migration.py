"""Confirmed, backed-up, reversible migration to category directories."""
import json
import shutil
from uuid import uuid4

from .item_layout import ItemLayout


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

    def migrate(self):
        sources = self.pending()
        if not sources:
            return None
        destinations = {path.name.casefold() for path in self.layout.root.iterdir()} if self.layout.root.exists() else set()
        for source in sources:
            if source.name.casefold() in destinations:
                raise ValueError(f'Миграция остановлена: папка уже существует: {source.name}')
            destinations.add(source.name.casefold())
            for path in source.rglob('*'):
                self.layout.checked(path)
        backup = self.layout.project / 'backups' / ('item-migration-' + uuid4().hex)
        # Complete every backup before moving the first directory.
        for source in sources:
            shutil.copytree(source, backup / 'Items' / source.name)
        self.layout.root.mkdir(parents=True, exist_ok=True)
        moved = []
        try:
            for source in sources:
                destination = self.layout.folder(source.name)
                source.rename(destination)
                moved.append((source, destination))
        except Exception:
            for source, destination in reversed(moved):
                destination.rename(source)
            raise
        return backup
