"""Shared project models; disk folders and Gothic resource names are separate."""
from pathlib import Path
import shutil
from uuid import uuid4

from .asset_files import AssetFiles
from .scripts import clean_id


class ModelLibrary:
    def __init__(self, project):
        self.project = Path(project).resolve()
        self.root = self.project / 'Assets' / 'Models'
        self.files = AssetFiles(self.project)

    @staticmethod
    def name(model):
        model = Path(model)
        return model.parent.name + '.3ds' if model.name.casefold() == 'model.3ds' else model.name

    def index(self):
        from .world_resources import WorldResources
        replacements=set(WorldResources(self.project).overrides('model').values())
        result = {}
        for model in sorted(path for path in self.root.rglob('*')
                            if path.is_file() and path.suffix.lower()=='.3ds'
                            and path not in replacements
                            and (path.relative_to(self.root).parts[0].casefold() != 'world'
                                 or path.name.casefold()=='model.3ds')):
            self.files.checked(model)
            name = self.name(model).casefold()
            if name in result:raise ValueError(f'Конфликт моделей {name}: {result[name]} / {model}')
            result[name] = model
        return result

    def folder_for(self, visual):
        model = self.index().get(visual.casefold())
        if model is None:raise ValueError('Сначала назначьте модель из Assets/Models.')
        return model.parent

    def create(self, name, model, textures, preserve_name=False):
        self.root.mkdir(parents=True, exist_ok=True)
        self.files.checked(self.root)
        name = self.files.name(name) if preserve_name else clean_id(name)
        name.encode('cp1251')
        target = self.root / name
        index = 2
        occupied = {path.name.casefold() for path in self.root.iterdir()}
        while target.name.casefold() in occupied:
            target = self.root / f'{name}_{index}'
            index += 1
        temporary = self.project / ('.model-' + uuid4().hex)
        temporary.mkdir()
        try:
            (temporary / 'model.3ds').write_bytes(model)
            for texture in textures:
                self.files.name(texture.name)
                shutil.copy2(texture, temporary / texture.name)
            temporary.rename(target)
        finally:
            if temporary.exists():shutil.rmtree(temporary)
        return target / 'model.3ds'

    def migrate(self, store):
        """Move old owned models and flat model files, keeping backups and visuals."""
        from .model_resolver import ModelResolver
        from .item_assets import texture_references
        from .texture_names import texture_candidates
        def textures_for(model):
            available={}
            for folder in (self.project/'Assets/Textures',self.root,model.parent):
                for path in folder.glob('*'):
                    if path.is_file() and path.suffix.lower() in ('.tga','.tex'):
                        store.layout.checked(path)
                        available[path.name.casefold()]=path
            return list(dict.fromkeys(available[name] for reference in texture_references(model.read_bytes())
                        for name in texture_candidates(reference) if name in available))
        # Old item models had a unique generated visual; retain that name forever.
        for file in store.files():
            model = ModelResolver.custom_model(file.parent)
            if not model.is_file():continue
            store.layout.checked(model)
            data = store._read(file)
            textures = [path for path in model.parent.iterdir()
                        if path.is_file() and path.suffix.lower() in ('.tga', '.tex')]
            textures=list(dict.fromkeys([*textures,*textures_for(model)]))
            for path in textures:store.layout.checked(path)
            backup = self.project/'backups'/('model-migration-'+uuid4().hex)
            shutil.copytree(model.parent, backup/'assets')
            shutil.copy2(file, backup/'item.json')
            relocated = self.create(Path(ModelResolver.generated_name(data['instance'])).stem,
                                    model.read_bytes(), textures)
            data['fields']['visual'] = '"' + self.name(relocated) + '"'
            try:store._atomic_json(file, data)
            except Exception:
                shutil.rmtree(relocated.parent)
                raise
            # Remove only the resources actually relocated, retaining unrelated files.
            for path in [model, *textures]:
                if path.parent==model.parent:path.unlink()
            if not any(model.parent.iterdir()):model.parent.rmdir()
        # Earlier project-wide imports were loose files in Assets/Models.
        relocated_textures=set()
        for model in sorted(path for path in self.root.glob('*')
                            if path.is_file() and path.suffix.lower()=='.3ds'):
            self.files.checked(model)
            textures = textures_for(model)
            target = self.root/model.stem
            if target.exists():raise ValueError(f'Не удалось перенести модель: папка уже существует: {target}')
            backup = self.project/'backups'/('model-migration-'+uuid4().hex)
            backup.mkdir(parents=True)
            for path in [model,*textures]:shutil.copy2(path,backup/path.name)
            # create() preserves the stem, so existing visual values remain valid.
            relocated = self.create(model.stem,model.read_bytes(),textures,preserve_name=True)
            model.unlink()
            relocated_textures.update(path for path in textures if path.parent==self.root)
        for texture in relocated_textures:texture.unlink()
