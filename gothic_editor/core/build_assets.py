"""Prepare owned item resources and detect Gothic's global filename conflicts."""
from pathlib import Path

from .item_assets import texture_references, replace_texture_references
from .texture_names import texture_candidates, material_texture_name
from .mesh import read_3ds_bytes
from .model_resolver import ModelResolver
from .potion_components import PotionComponents
from .mod_archive import write_mod
from .model_library import ModelLibrary
from .world_resources import WorldResources
from .game_media import GameMedia


class BuildAssetService:
    def __init__(self, project, game=None):
        self.store = PotionComponents(project)
        self.game = game

    def collect(self):
        files, names, models = {}, {}, []
        library=ModelLibrary(self.store.layout.project)
        shared=library.index()

        def add(name, path, label):
            key = Path(name).name.casefold()
            data = path.read_bytes()
            if key in names:
                raise ValueError(f'Конфликт имени ресурса {name}: {names[key]} / {label}')
            names[key] = label
            files[name] = data

        def add_model(model,visual):
            source=model.read_bytes()
            read_3ds_bytes(source)
            textures={}
            for path in sorted(model.parent.iterdir()):
                if not path.is_file() or path.suffix.lower() not in ('.tga','.tex'):continue
                self.store.layout.checked(path)
                suffix=path.suffix.lower()
                packed_texture=Path(visual).stem+'_'+path.name
                directory='_work/data/Textures/'+('_compiled/' if suffix=='.tex' else '')
                add(directory+packed_texture,path,str(model.parent))
                textures[path.name.casefold()]=packed_texture
            replacements={}
            for reference in texture_references(source):
                matched=next((textures[name] for name in texture_candidates(reference) if name in textures),None)
                if matched is None:
                    raise ValueError(f'{model.parent.name}: отсутствует текстура {reference}. Добавьте её в {model.parent}.')
                replacements[reference]=material_texture_name(matched)
            packed_name='_work/data/Meshes/'+visual
            add(packed_name,model,str(model))
            files[packed_name]=replace_texture_references(source,replacements)

        # Every library folder is a shared bundle. Gothic needs unique basenames,
        # while the editable disk files remain model.3ds and their original textures.
        for model in shared.values():add_model(model,library.name(model))

        for file in self.store.files():
            data = self.store._read(file)
            assets = file.parent / 'assets'
            model = ModelResolver.custom_model(file.parent)
            if assets.exists():
                for path in assets.rglob('*'):self.store.layout.checked(path)
            if not model.exists():
                # A generated visual without its owned file must never silently build.
                visual = data.get('fields', {}).get('visual', '').strip('"')
                if visual.casefold().startswith('model_') and visual.casefold().endswith('.3ds') and visual.casefold() not in shared:
                    raise ValueError(f'Не найдена собственная модель {visual}: {model}')
            else:
                add_model(model,ModelResolver.generated_name(data['instance']))
            # Old texture-only directories are not independent MOD resources:
            # after model migration the library already owns the required copies.
        # Existing project-wide models/textures are also mod resources, even when
        # the visual was selected from Assets rather than imported into an item.
        global_assets=self.store.layout.project/'Assets'
        for path in sorted(global_assets.rglob('*')):
            if not path.is_file():continue
            relative=path.relative_to(global_assets)
            if relative.parts[0].casefold() in ('items','scripts','models','npc','recipes','media'):continue
            if (relative.as_posix().casefold() in ('worlds/overrides.json','worlds/catalog.json')
                    or tuple(part.casefold() for part in relative.parts[:2]) == ('textures','world')):continue
            self.store.layout.checked(path)
            suffix=path.suffix.casefold()
            if suffix in ('.3ds','.mrm','.msh'):
                directory='_work/data/Meshes/'+('_compiled/' if suffix!='.3ds' else '')
                if suffix=='.3ds':
                    source=path.read_bytes()
                    read_3ds_bytes(source)
                    models.append((path,texture_references(source),directory+path.name))
            elif suffix in ('.tga','.tex'):
                directory='_work/data/Textures/'+('_compiled/' if suffix=='.tex' else '')
            else:
                relative=path.relative_to(global_assets)
                roots={'sound':'Sound','anims':'Anims','worlds':'Worlds'}
                section=roots.get(relative.parts[0].casefold())
                if section is None:
                    if suffix in ('.vdf','.mod'):continue  # Catalog sources are not nested as files in a MOD.
                    raise ValueError(f'Неизвестное размещение ресурса {path}. Используйте Assets/Models, Textures, Sound, Anims или Worlds.')
                directory='_work/data/'+section+'/'
                add(directory+'/'.join(relative.parts[1:]),path,str(path))
                continue
            add(directory+path.name,path,str(path))
        textures={Path(name).name.casefold():Path(name).name for name in files
                  if Path(name).suffix.lower() in ('.tga','.tex')}
        for file, references, packed_name in models:
            replacements={}
            for reference in references:
                name = Path(reference.replace('\\', '/')).name
                matched=next((textures[candidate] for candidate in texture_candidates(reference)
                              if candidate in textures),None)
                if matched is None:
                    raise ValueError(f'{file.parent.name}: отсутствует текстура {name}. Добавьте её в assets.')
                logical_name=material_texture_name(matched)
                if reference.casefold()!=logical_name.casefold():replacements[reference]=logical_name
            files[packed_name]=replace_texture_references(files[packed_name],replacements)
        # World replacements intentionally retain global Gothic names and references.
        for name, data in WorldResources(self.store.layout.project).collect(self.game,files).items():
            key=Path(name).name.casefold()
            if key in names:raise ValueError(f'Конфликт имени ресурса мира {name}: {names[key]}')
            names[key]='Мир'
            files[name]=data
        # Media textures override the same logical resource names as the game.
        for name,data in GameMedia(self.store.layout.project).collect_images().items():
            key=Path(name).name.casefold()
            if key in names:raise ValueError(f'Конфликт имени медиа {name}: {names[key]}')
            names[key]='Медиа'
            files[name]=data
        from .npc_models import collect_npc_models
        for name,data in collect_npc_models(self.store.layout.project).items():
            key=Path(name).name.casefold()
            if key in names:raise ValueError(f'Конфликт модели NPC {name}: {names[key]}')
            names[key]='NPC'
            files[name]=data
        return files

    def package(self, output, compiled, files):
        contents = dict(files)
        contents['_work/data/Scripts/_compiled/Gothic.dat'] = compiled.read_bytes()
        write_mod(output, contents)
