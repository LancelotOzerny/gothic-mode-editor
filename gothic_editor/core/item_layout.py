"""Category-based component locations shared by repositories and resource panels."""
from pathlib import Path
import re


class ItemLayout:
    CATEGORIES = {'potions': 'Potions'}

    def __init__(self, project, category='potions'):
        self.project = Path(project).resolve()
        self.items = self.project / 'Assets' / 'Items'
        # Read old projects in place; new projects and manually moved items use Assets.
        if not self.items.exists() and (self.project / 'Items').is_dir():
            self.items = self.project / 'Items'
        self.root = self.items / self.CATEGORIES[category]

    def checked(self, path):
        path = Path(path)
        if self.project not in path.resolve().parents:
            raise ValueError(f'Путь ресурса выходит за пределы проекта: {path}')
        return path

    def folder(self, instance):
        if not re.fullmatch(r'[A-Za-z_]\w*', instance, re.ASCII):
            raise ValueError('Неверный идентификатор Daedalus: ' + instance)
        return self.checked(self.root / instance)

    def legacy_files(self):
        return sorted(self.items.glob('*/item.json'))

    def files(self):
        paths = sorted(self.root.glob('*/item.json')) + self.legacy_files()
        seen = {}
        for path in paths:
            self.checked(path)
            key = path.parent.name.casefold()
            if key in seen:
                raise ValueError(f'Конфликт папок предмета: {seen[key]} / {path}')
            seen[key] = path
        return paths

    def owns(self, path):
        path = Path(path)
        return (path.name == 'item.json' and path.parent.parent in (self.root, self.items)
                and self.checked(path) == path)

    def find_folder(self, instance):
        target = self.folder(instance)
        for folder in (target, self.items / instance):
            if (folder / 'item.json').is_file():
                return self.checked(folder)
        # On case-sensitive filesystems preserve Daedalus' case-insensitive IDs.
        for parent in (self.root, self.items):
            if not parent.is_dir():continue
            for folder in parent.iterdir():
                if folder.name.casefold() == instance.casefold() and (folder/'item.json').is_file():
                    return self.checked(folder)
        return target


def project_scripts(project):
    project = Path(project)
    scripts = project / 'Assets' / 'Scripts'
    legacy = project / 'Scripts'
    return scripts if scripts.exists() or not legacy.is_dir() else legacy
