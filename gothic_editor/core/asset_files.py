"""File operations confined to the project's Assets directory."""
from pathlib import Path
import re
import shutil


class AssetFiles:
    def __init__(self, project):
        self.root = Path(project).resolve() / 'Assets'

    def checked(self, path, allow_root=False):
        path = Path(path)
        resolved = path.resolve()
        if ((resolved != self.root or not allow_root) and self.root not in resolved.parents):
            raise ValueError('Операция разрешена только внутри Assets проекта.')
        # Do not traverse links/junctions during recursive copies or deletion.
        for part in (path, *path.parents):
            if part == self.root.parent:break
            if part.is_symlink() or getattr(part, 'is_junction', lambda:False)():
                raise ValueError(f'Операции со ссылками не поддерживаются: {part.name}')
        return resolved

    @staticmethod
    def name(value):
        if (not value or value in ('.', '..') or value != value.strip()
                or value.endswith('.') or re.search(r'[<>:"/\\|?*\x00-\x1f]', value)
                or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', value, re.I)):
            raise ValueError('Укажите допустимое имя файла или папки без пути.')
        return value

    def create(self, folder, name, script=False, *, markdown=False):
        folder = self.checked(folder, allow_root=True)
        name = self.name(name)
        if script and markdown:
            raise ValueError('Выберите один тип создаваемого файла.')
        if script:
            if not name.lower().endswith('.d'):
                name += '.d'
            stem = Path(name).stem
            if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', stem, re.ASCII):
                raise ValueError('Имя скрипта должно быть идентификатором Daedalus: латиница, цифры, _.')
        if markdown:
            if not name.lower().endswith('.md'):
                name += '.md'
        target = self.checked(folder / name)
        if script:
            template = (
                f'// @INFO NAME="{stem}"\n\n'
                f'func void {stem}()\n'
                '{\n'
                '    // your script code\n'
                '};\n'
            )
            with target.open('x', encoding='utf-8', newline='\n') as output:
                output.write(template)
        elif markdown:
            with target.open('x', encoding='utf-8', newline='\n') as output:
                output.write('# Название\n\n')
        else:
            target.mkdir()
        return target

    def _check_tree(self, path):
        path = self.checked(path)
        if not path.exists():raise FileNotFoundError(str(path))
        if path.is_dir():
            for child in path.rglob('*'):self.checked(child)
        return path

    def copy(self, source, folder):
        source = self._check_tree(source)
        folder = self.checked(folder, allow_root=True)
        if not folder.is_dir():raise NotADirectoryError(str(folder))
        if source == folder or source in folder.parents:
            raise ValueError('Нельзя копировать папку внутрь неё самой.')
        stem, suffix = (source.name, '') if source.is_dir() else (source.stem, source.suffix)
        target = folder / source.name
        index = 1
        while target.exists():
            tail = '_copy' if index == 1 else f'_copy_{index}'
            target = folder / (stem + tail + suffix)
            index += 1
        target = self.checked(target)
        if source.is_dir():shutil.copytree(source, target)
        else:
            # Exclusive creation prevents replacing a file created concurrently.
            with source.open('rb') as src, target.open('xb') as dst:
                shutil.copyfileobj(src, dst)
        return target

    def rename(self, source, name):
        source = self._check_tree(source)
        target = source.with_name(self.name(name))
        resolved = self.checked(target)
        if target.name == source.name:
            return source
        if resolved.exists() and resolved != source:
            raise FileExistsError(f'Ресурс уже существует: {target.name}')
        return source.rename(target)

    def move_target(self, source, folder):
        source = self.checked(source)
        folder = self.checked(folder, allow_root=True)
        if not folder.is_dir():
            raise NotADirectoryError(str(folder))
        if source == folder or source in folder.parents:
            raise ValueError('Нельзя переносить папку внутрь неё самой.')
        target = self.checked(folder / source.name)
        if target.exists():
            raise FileExistsError(f'Ресурс уже существует: {target.name}')
        return target

    def move(self, source, folder):
        source = self._check_tree(source)
        return source.rename(self.move_target(source, folder))

    def delete(self, path):
        path = self._check_tree(path)
        if path.is_dir():shutil.rmtree(path)
        else:path.unlink()
