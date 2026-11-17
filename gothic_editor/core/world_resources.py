"""Project-owned replacements of static Gothic resources, with original names."""
from dataclasses import dataclass
import json
from pathlib import Path
from uuid import uuid4

from .asset_files import AssetFiles
from .mesh import read_3ds_bytes,read_mrm
from .model_export import export_texture
from .texture_names import material_texture_name, texture_candidates
from .textures import read_texture, write_ztex


WORLD_CATEGORIES = {
    'architecture': 'Архитектура', 'vegetation': 'Растительность',
    'furniture': 'Мебель', 'decorations': 'Декорации',
}


def resource_name(name, kind):
    name = Path(name.replace('\\', '/')).name
    AssetFiles.name(name)
    if kind == 'model':
        if Path(name).suffix.lower() not in ('.3ds', '.mrm', '.mdm', '.mdl'):
            raise ValueError('Поддерживаются статические модели 3DS и MRM.')
        if Path(name).suffix.lower() in ('.3ds','.mrm'):name = str(Path(name).with_suffix('.3ds'))
    elif kind == 'texture':
        name = material_texture_name(name)
        if Path(name).suffix.lower() in ('', '.tex'):
            name = str(Path(name).with_suffix('.tga'))
        if Path(name).suffix.lower() != '.tga':
            raise ValueError('Поддерживаются текстуры TGA и TEX.')
    else:
        raise ValueError('Неизвестный тип ресурса мира.')
    if len(name.encode('cp1251')) > (63 if kind == 'model' else 61):
        raise ValueError('Слишком длинное имя ресурса: ' + name)
    return name


@dataclass(frozen=True)
class WorldResource:
    name: str
    source: object
    category: str
    overridden: bool = False

    @property
    def title(self):
        return 'Сундук — '+self.name if self.name.casefold().startswith('chest') else self.name


def category_for(name):
    name = name.casefold()
    if any(word in name for word in ('tree', 'bush', 'plant', 'grass', 'flora', 'palm', 'baum')):
        return 'vegetation'
    if any(word in name for word in ('chair', 'table', 'bed', 'bench', 'shelf', 'furniture', 'stool','chest')):
        return 'furniture'
    if any(word in name for word in ('house', 'wall', 'tower', 'bridge', 'door', 'gate', 'building', 'arch', 'hut')):
        return 'architecture'
    return 'decorations'


class WorldResources:
    def __init__(self, project):
        self.project = Path(project).resolve()
        self.files = AssetFiles(self.project)
        self.manifest = self.project / 'Assets/Worlds/overrides.json'

    def _load(self):
        self.files.checked(self.manifest)
        if not self.manifest.exists():
            return {}
        data = json.loads(self.manifest.read_text('utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('resources'), dict):
            raise ValueError(f'{self.manifest}: некорректный список замен ресурсов.')
        result = data['resources']
        for key, record in result.items():
            if (not isinstance(record, dict) or record.get('kind') not in ('model', 'texture')
                    or not isinstance(record.get('name'), str)):
                raise ValueError(f'{self.manifest}: некорректная запись {key}')
            name = resource_name(record['name'], record['kind'])
            category = record.get('category', 'decorations')
            if not isinstance(category,str) or category not in WORLD_CATEGORIES or key != record['kind'] + ':' + name.casefold():
                raise ValueError(f'{self.manifest}: некорректный идентификатор {key}')
            target=self._target(name,record['kind'])
            if record.get('format')=='mrm' and record['kind']=='model':target=target.with_suffix('.mrm')
            if record.get('path') != target.relative_to(self.project).as_posix():
                raise ValueError(f'{self.manifest}: некорректный путь {key}')
        return result

    def _target(self, name, kind):
        folder = 'Models/World' if kind == 'model' else 'Textures/World'
        return self.files.checked(self.project / 'Assets' / folder / name)

    def overrides(self, kind):
        return {record['name'].casefold(): self.files.checked(self.project / record['path'])
                for record in self._load().values() if record['kind'] == kind}

    def _save(self, records):
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest.with_name('.overrides-' + uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps({'version': 1, 'resources': records}, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.manifest)
        finally:
            temporary.unlink(missing_ok=True)

    def replace(self, kind, name, source, category='decorations'):
        name = resource_name(name, kind)
        if kind=='model' and Path(name).suffix.lower() in ('.mdm','.mdl'):
            raise ValueError('Сундук — анимированная модель. Заменить её статической 3DS/MRM нельзя.')
        if category not in WORLD_CATEGORIES:
            raise ValueError('Неизвестная категория объекта мира.')
        records = self._load()
        # Retain existing spelling on case-insensitive resource identity.
        key = kind + ':' + name.casefold()
        name = records.get(key, {}).get('name', name)
        target = self._target(name, kind)
        source = Path(source)
        compiled=kind=='model' and source.suffix.lower()=='.mrm'
        if compiled:target=target.with_suffix('.mrm')
        if source.stat().st_size > 64 * 1024 * 1024:
            raise ValueError('Ресурс превышает 64 МБ: ' + str(source))
        data = source.read_bytes()
        if kind == 'model':
            if source.suffix.lower() not in ('.3ds','.mrm'):
                raise ValueError('Для замены модели выберите файл 3DS или MRM.')
            mesh = read_mrm(data,preview=True) if compiled else read_3ds_bytes(data, preview=True)
            if not mesh.vertices or not mesh.faces:
                raise ValueError('Модель не содержит треугольников: ' + str(source))
        else:
            texture = read_texture(data)
        if target.exists() and key not in records:
            raise ValueError('Файл уже существует и не принадлежит замене: ' + str(target))
        previous = target.read_bytes() if target.exists() else None
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            if kind == 'texture':
                export_texture(texture, None, target)
            else:
                temporary = target.with_name('.' + uuid4().hex + '.tmp')
                try:
                    temporary.write_bytes(data)
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            old_path=self.project/records[key]['path'] if key in records else None
            records[key] = {'kind': kind, 'name': name, 'category': category,
                            'path': target.relative_to(self.project).as_posix()}
            if compiled:records[key]['format']='mrm'
            self._save(records)
            if old_path is not None and old_path!=target:self.files.checked(old_path).unlink(missing_ok=True)
        except Exception:
            if previous is None:target.unlink(missing_ok=True)
            else:target.write_bytes(previous)
            raise
        return target

    def remove(self, kind, name):
        key = kind + ':' + resource_name(name, kind).casefold()
        records = self._load()
        if key not in records:return
        target = self.files.checked(self.project / records[key]['path'])
        del records[key]
        # Manifest failure must leave the previous replacement active.
        self._save(records)
        try:target.unlink(missing_ok=True)
        except OSError:
            # An unreferenced file is not packed; preserve it rather than mask failure.
            raise ValueError('Замена отключена, но файл не удалось удалить: ' + str(target))

    def catalog(self, repo):
        records = self._load()
        result = {}
        used = {str(Path(item.visual.replace('\\', '/')).with_suffix('.3ds')).casefold()
                for item in repo.items if item.visual}
        for name, source in repo.mesh_index.items():
            if repo.game and repo.game in source.resolve().parents:
                logical = resource_name(name, 'model')
                result.setdefault(logical.casefold(), WorldResource(logical, source, category_for(str(source))))
        for source in repo.archive_models.entries.values():
            if Path(source.name).suffix.lower() not in ('.3ds', '.mrm'):continue
            logical = resource_name(source.name, 'model')
            key = logical.casefold()
            existing = result.get(key)
            if existing is None or (not isinstance(existing.source, Path) and Path(source.name).suffix.lower() == '.3ds'):
                result[key] = WorldResource(logical, source, category_for(source.name))
        # Loose compiled static objects are not part of the existing item mesh index.
        if repo.game:
            for source in sorted((repo.game / '_work/data/Meshes').rglob('*')):
                if source.is_file() and source.suffix.lower() == '.mrm':
                    logical = resource_name(source.name, 'model')
                    result.setdefault(logical.casefold(), WorldResource(logical, source, category_for(str(source))))
        result = {key: value for key, value in result.items()
                  if key not in used and not key.startswith(('it', 'model_it'))}
        animated={}
        for source in repo.archive_models.animation_entries.values():
            suffix=Path(source.name).suffix.lower()
            stem=Path(source.name).stem.casefold()
            if not stem.startswith('chest') or suffix not in ('.mdm','.mdl'):continue
            if stem not in animated or suffix=='.mdl':animated[stem]=source
        if repo.game:
            for source in sorted((repo.game/'_work/data/Anims').rglob('*')):
                if source.is_file() and source.stem.casefold().startswith('chest') and source.suffix.lower() in ('.mdm','.mdl'):
                    key=source.stem.casefold()
                    if key not in animated or source.suffix.lower()=='.mdl':animated[key]=source
        for source in animated.values():
            result[source.name.casefold()]=WorldResource(source.name,source,'furniture')
        for record in records.values():
            if record['kind'] != 'model':continue
            source = self.files.checked(self.project / record['path'])
            if not source.is_file():raise ValueError('Не найдена замена модели: ' + str(source))
            result[record['name'].casefold()] = WorldResource(record['name'], source, record['category'], True)
        return sorted(result.values(), key=lambda value: value.name.casefold())

    def collect(self, game=None, available=()):
        records=self._load()
        if not records:return {}
        result = {}
        textures = {Path(name).name.casefold() for name in available if Path(name).suffix.lower() in ('.tga','.tex')}
        textures.update(record['name'].casefold() for record in records.values() if record['kind']=='texture')
        if game is not None and any(record['kind']=='model' for record in records.values()):
            from .archive_models import ArchiveModels
            archives=ArchiveModels()
            archives.refresh(self.project,Path(game))
            textures.update(archives.texture_entries)
            textures.update(source.name.casefold() for source in (Path(game)/'_work/data/Textures').rglob('*')
                            if source.is_file() and source.suffix.lower() in ('.tga','.tex'))
        for record in records.values():
            source = self.files.checked(self.project / record['path'])
            if not source.is_file():raise ValueError('Не найден ресурс мира: ' + str(source))
            data = source.read_bytes()
            if record['kind'] == 'model':
                compiled=record.get('format')=='mrm'
                mesh=read_mrm(data,preview=True) if compiled else read_3ds_bytes(data,preview=True)
                original=archives.find(record['name']) if game is not None else None
                if not compiled and original is not None and Path(original.name).suffix.lower()=='.mrm':
                    raise ValueError(f'{source}: игра использует скомпилированную MRM из VDF. Для замены импортируйте готовую MRM; компиляция 3DS в MRM пока не поддерживается.')
                if not mesh.vertices or not mesh.faces:raise ValueError('Модель не содержит треугольников: '+str(source))
                if game is not None:
                    for reference in set(mesh.texture_names)-{''}:
                        if not any(candidate in textures for candidate in texture_candidates(reference)):
                            raise ValueError(f'{source}: отсутствует текстура {reference}. Добавьте замену текстуры в проект.')
                packed='_work/data/Meshes/_compiled/'+str(Path(record['name']).with_suffix('.mrm')) if compiled else '_work/data/Meshes/'+record['name']
                result[packed] = data
            else:
                texture = read_texture(data)
                result['_work/data/Textures/' + record['name']] = data
                compiled = Path(record['name']).stem + '-C.TEX'
                result['_work/data/Textures/_compiled/' + compiled] = write_ztex(texture)
        return result
