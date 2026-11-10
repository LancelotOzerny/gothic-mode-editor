"""Prepare owned item resources and detect Gothic's global filename conflicts."""
from pathlib import Path

from .item_assets import texture_references, replace_texture_references
from .texture_names import texture_candidates, material_texture_name
from .mesh import read_3ds_bytes
from .model_resolver import ModelResolver
from .potion_components import PotionComponents
from .mod_archive import write_mod


class BuildAssetService:
    def __init__(self, project):
        self.store = PotionComponents(project)

    def collect(self):
        files, names, models = {}, {}, []

        def add(name, path, label):
            key = Path(name).name.casefold()
            data = path.read_bytes()
            if key in names:
                raise ValueError(f'Конфликт имени ресурса {name}: {names[key]} / {label}')
            names[key] = label
            files[name] = data

        for file in self.store.files():
            data = self.store._read(file)
            assets = file.parent / 'assets'
            model = ModelResolver.custom_model(file.parent)
            if assets.exists():
                for path in assets.rglob('*'):self.store.layout.checked(path)
            if not model.exists():
                # A generated visual without its owned file must never silently build.
                visual = data.get('fields', {}).get('visual', '').strip('"')
                if visual.casefold().startswith('model_') and visual.casefold().endswith('.3ds'):
                    raise ValueError(f'Не найдена собственная модель {visual}: {model}')
            else:
                source = model.read_bytes()
                read_3ds_bytes(source)
                packed_name='_work/data/Meshes/' + ModelResolver.generated_name(data['instance'])
                models.append((file, texture_references(source), packed_name))
                add(packed_name, model, str(file))
            for path in sorted(assets.rglob('*')):
                if not path.is_file() or path == model:continue
                suffix = path.suffix.casefold()
                if suffix not in ('.tga', '.tex'):
                    raise ValueError(f'Нельзя упаковать ресурс: {path}. Поддерживаются model.3ds, TGA и TEX.')
                directory = '_work/data/Textures/' + ('_compiled/' if suffix == '.tex' else '')
                add(directory + path.name, path, str(file))
        # Existing project-wide models/textures are also mod resources, even when
        # the visual was selected from Assets rather than imported into an item.
        global_assets=self.store.layout.project/'Assets'
        for path in sorted(global_assets.rglob('*')):
            if not path.is_file():continue
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
        return files

    def package(self, output, compiled, files):
        contents = dict(files)
        contents['_work/data/Scripts/_compiled/Gothic.dat'] = compiled.read_bytes()
        write_mod(output, contents)
