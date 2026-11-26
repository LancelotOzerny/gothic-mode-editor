"""Project management and safe copy-on-write repository."""
from __future__ import annotations
import json,re,os
from .localization import tr
from pathlib import Path
from .scripts import Item,parse_items,replace_field,replace_instance,write_modified_item,clean_id,ITEM_OVERRIDES_HEADER,with_item_metadata
from .categories import classify,get_category,leaf_for
from .archive_models import ArchiveModels
from .potion_components import PotionComponents
from .properties_schema import schema_for
from .potion_schemes import DEFAULT_POTION_SCHEME
from .item_migration import ItemMigrationService
from .item_layout import project_scripts
from .model_resolver import ModelResolver
from .model_library import ModelLibrary
from .settings import field_key, validate_value
from .settings_schema import all_fields
from .item_hierarchy import ItemHierarchy

class ProjectRepository:
    def __init__(self,shared_resources=None):
        self.shared_resources=shared_resources
        self.root:Path|None=None
        self.game:Path|None=None
        self.compiler_path=''
        self.resource_editor_path=''
        self.items:list[Item]=[]
        self.components=None
        self.project_items=[]
        self.game_items=[]
        self.errors=[]
        self.mesh_index={}
        self._game_mesh_index={}
        self._archive_errors=[]
        self.archive_models=ArchiveModels()
        self.project_settings={}
        self.options_cache={}
        self.resource_revision=0
        self.item_hierarchy=None

    def create(self,root:Path,name:str):
        root=root.resolve();root.mkdir(parents=True,exist_ok=True)
        config=root/'project.json'
        if config.exists():raise ValueError(tr('project.already_exists'))
        (root/'Assets'/'Scripts'/'Content'/'Items').mkdir(parents=True,exist_ok=True)
        (root/'Assets'/'Items'/'Potions').mkdir(parents=True,exist_ok=True)
        (root/'Assets'/'Texts'/'Documents').mkdir(parents=True,exist_ok=True)
        (root/'Assets'/'Models').mkdir(parents=True,exist_ok=True)
        config.write_text(json.dumps({'name':name,'game_path':''},ensure_ascii=False,indent=2),encoding='utf-8')
        self.open(root)

    def open(self,root:Path,confirm_migration=None):
        root=root.resolve();cfg=root/'project.json'
        if not cfg.is_file():raise ValueError(tr('project.not_project'))
        data=json.loads(cfg.read_text('utf-8'))
        if not isinstance(data,dict):raise ValueError('Некорректный project.json')
        project_settings=data.get('settings',{})
        if not isinstance(project_settings,dict):raise ValueError('Настройки проекта должны быть JSON-объектом')
        for field in all_fields():
            if field.scope=='project':validate_value(field,project_settings.get(field_key(field),field.default))
        migration=ItemMigrationService(root)
        pending=migration.pending()
        migrate_items = bool(pending and confirm_migration is not None and confirm_migration(len(pending)))
        self.name=data.get('name',root.name)
        resources=data if self.shared_resources is None else {**data,**self.shared_resources}
        raw=project_settings.get('resources.gothic.game_path',data.get('game_path') or resources.get('game_path',''))
        game=Path(raw).resolve() if raw else None
        self._validate_roots(root,game)
        self.root=root
        self.project_settings=dict(project_settings)
        self.components=PotionComponents(root)
        self.item_hierarchy=ItemHierarchy(root)
        ModelLibrary(root).migrate(self.components)
        if migrate_items:migration.migrate()
        self.game=game
        self.compiler_path=resources.get('compiler_path','')
        self.resource_editor_path=resources.get('resource_editor_path','')
        self.refresh()

    def save_project_settings(self,values):
        if not self.root:raise ValueError(tr('project.not_open'))
        updated=dict(self.project_settings)
        for field in all_fields():
            key=field_key(field)
            if field.scope=='project' and key in values:updated[key]=validate_value(field,values[key])
        config=self.root/'project.json'
        data=json.loads(config.read_text('utf-8'))
        data['settings']=updated
        temporary=config.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        temporary.replace(config)
        self.project_settings=updated

    @staticmethod
    def _validate_roots(root,game):
        if not game:return
        if root==game or root in game.parents or game in root.parents:
            raise ValueError(tr('project.overlapping_roots'))

    def validate_game_path(self,path:str):
        path=path.strip()
        if path and not Path(path).is_dir():raise ValueError(tr('project.game_missing'))
        target=Path(path).resolve() if path else None
        if self.root:self._validate_roots(self.root,target)
        return target

    def set_game_path(self,path:str):
        self.set_configuration(path,self.compiler_path)

    def set_configuration(self,path:str,compiler_path:str,resource_editor_path=None):
        target,compiler_path,editor_path=self.validate_configuration(path,compiler_path,resource_editor_path)
        resources=dict(game_path=str(target) if target else '',compiler_path=compiler_path,
                       resource_editor_path=editor_path)
        if self.shared_resources is None:
            if not self.root:raise ValueError(tr('project.not_open'))
            config=json.loads((self.root/'project.json').read_text('utf-8'))
            config.update(name=self.name,**resources)
            temporary=self.root/'project.json.tmp'
            temporary.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
            temporary.replace(self.root/'project.json')
        else:
            self.shared_resources.update(resources)
        if self.root and self.project_settings.get('resources.gothic.game_path')!=resources['game_path']:
            self.save_project_settings({'resources.gothic.game_path':resources['game_path']})
        changed=self.game!=target
        self.game=target
        self.compiler_path=compiler_path
        self.resource_editor_path=editor_path
        if changed:self.refresh()

    def validate_configuration(self,path,compiler_path,resource_editor_path=None):
        target=self.validate_game_path(path)
        compiler_path=compiler_path.strip()
        if compiler_path:
            compiler=Path(compiler_path).expanduser()
            if not compiler.is_absolute():compiler=(self.root or Path.cwd())/compiler
            if not compiler.is_file() or compiler.suffix.lower() not in ('.dll','.exe'):
                raise ValueError(tr('tools.compiler_missing'))
            if self.shared_resources is not None:compiler_path=str(compiler.resolve())
        editor_path=self.resource_editor_path if resource_editor_path is None else resource_editor_path.strip()
        if editor_path:
            editor=Path(editor_path).expanduser()
            if not editor.is_absolute():editor=(self.root or Path.cwd())/editor
            if not editor.is_file():raise ValueError(tr('resources.editor_missing',path=str(editor)))
            if self.shared_resources is not None:editor_path=str(editor.resolve())
        return target,compiler_path,editor_path

    def _game_content(self):
        if not self.game:return None
        for candidate in (self.game/'_work'/'data'/'Scripts'/'Content',self.game/'Scripts'/'Content',self.game/'Content',self.game):
            if candidate.is_dir() and (candidate/'Items').is_dir():return candidate
        return self.game

    def _project_content(self):return project_scripts(self.root)/'Content'

    def refresh(self,project_only=False):
        if not self.root:return
        self.options_cache.clear()
        self.resource_revision+=1
        self.errors=[]
        merged={}
        by_origin={'project':{},'game':{}}
        def scan(root,origin):
            if not root or not root.exists():return
            for path in root.rglob('*'):
                if not path.is_file() or path.suffix.lower()!='.d':continue
                try:
                    for item in parse_items(path,origin):
                        merged[item.instance.casefold()]=item
                        by_origin[origin][item.instance.casefold()]=item
                except (OSError,UnicodeError,ValueError) as e:
                    if len(self.errors)<12:self.errors.append(f'{path.name}: {e}')
        game_content=self._game_content()
        if project_only:
            by_origin['game']={item.instance.casefold():item for item in self.game_items}
            merged.update(by_origin['game'])
        elif game_content and self.root not in game_content.parents and game_content!=self.root:
            scan(game_content,'game')
        scan(self._project_content(),'project')
        # JSON components take precedence over the game and legacy project scripts.
        try:
            for item in self.components.list_items():
                merged[item.instance.casefold()]=item
                by_origin['project'][item.instance.casefold()]=item
        except (OSError,UnicodeError,ValueError,KeyError) as exc:
            self.errors.append(str(exc))
        self.items=sorted(merged.values(),key=lambda i:(i.title.casefold(),i.instance.casefold()))
        self.project_items=sorted(by_origin['project'].values(),key=lambda i:(i.title.casefold(),i.instance.casefold()))
        self.game_items=sorted(by_origin['game'].values(),key=lambda i:(i.title.casefold(),i.instance.casefold()))
        if not project_only:
            self._game_mesh_index={}
            for base in (self.game/'_work'/'data'/'Meshes' if self.game else None,):
                if base and base.exists():
                    for directory,_,names in os.walk(base):
                        for name in names:
                            if name.lower().endswith('.3ds'):
                                self._game_mesh_index.setdefault(name.lower(),Path(directory)/name)
            self._archive_errors=self.archive_models.refresh(self.root,self.game)
        self.mesh_index=dict(self._game_mesh_index)
        self.errors.extend(self._archive_errors)
        self.mesh_index.update(ModelResolver.index(self.components))
        self.mesh_index.update(ModelLibrary(self.root).index())
        from .world_resources import WorldResources
        self.mesh_index.update(WorldResources(self.root).overrides('model'))

    def exists(self,instance):return any(it.instance.casefold()==instance.casefold() for it in self.items)

    def _replace_project_file(self, old_path, updated):
        """Update the in-memory overlay after a write, without rescanning scripts or assets."""
        updated=list(updated)
        identifiers={item.instance.casefold() for item in updated}
        self.project_items=[item for item in self.project_items if item.path!=old_path and
                            item.instance.casefold() not in identifiers]+updated
        self.project_items.sort(key=lambda item:(item.title.casefold(),item.instance.casefold()))
        merged={item.instance.casefold():item for item in self.game_items}
        merged.update((item.instance.casefold(),item) for item in self.project_items)
        self.items=sorted(merged.values(),key=lambda item:(item.title.casefold(),item.instance.casefold()))

    def new_id(self,original='GE_Item',prefix='GE_'):
        base=clean_id(original)
        if not base.casefold().startswith(prefix.casefold()):base=prefix+base
        candidate=base;n=2
        existing={item.instance.casefold() for item in self.items}
        while candidate.casefold() in existing:candidate=f'{base}_{n}';n+=1
        return candidate

    def _import_component(self,item,instance=None,as_override=False):
        destination=self.components.import_item(item,instance,as_override)
        updated=self.components.read_item(destination)
        self._replace_project_file(updated.path,[updated])
        model=ModelResolver.custom_model(destination.parent)
        if model.is_file():self.mesh_index[ModelResolver.generated_name(updated.instance).casefold()]=model
        return updated

    def _write_new(self,instance,code,metadata=None):
        folder=self._project_content()/'Items'/'GE_Generated'
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/(instance+'.d')
        if path.exists():raise ValueError(tr('project.file_exists'))
        if metadata:code=with_item_metadata(code,metadata)
        path.write_text('// Generated by Gothic Editor\n'+code.strip()+'\n',encoding='cp1251')
        self._replace_project_file(path,parse_items(path,'project'))
        return next(x for x in self.items if x.instance==instance)

    def create_item_from_fields(self,instance,fields,metadata=None):
        """Create one explicitly named item through the existing storage mechanisms."""
        self.components._safe_id(instance)
        if self.exists(instance):raise ValueError(tr('project.file_exists'))
        code=f'INSTANCE {instance} (C_Item)\n{{\n'+''.join(
            f'    {key} = {value};\n' for key,value in fields.items() if value.strip())+'};'
        code.encode('cp1251')
        item=Item(instance,self.root/'__new__','project',code,dict(fields),0,len(code),editor_metadata=metadata or {})
        if classify(item)=='potions':return self._import_component(item)
        return self._write_new(instance,code,metadata)

    def create_item(self,category_key,name=None):
        title=(name or tr('items.default_name')).replace('\\','\\\\').replace('"','\\"')
        schema=schema_for(category_key)
        if schema is not None:
            number=schema.numbering_start
            instance=schema.instance_prefix+schema.instance_pattern.replace('{n}',str(number))
            while (self.exists(instance) or (category_key!='potions' and
                    (self._project_content()/'Items'/'GE_Generated'/(instance+'.d')).exists())):
                number+=1
                instance=schema.instance_prefix+schema.instance_pattern.replace('{n}',str(number))
            fields={field.key:field.default for section in schema.sections for field in section.fields
                    if field.source=='property' and field.export and field.default not in (None,'')}
            if name:fields['name']='"'+title+'"'
            else:fields.setdefault('name','"'+tr('items.default_potion' if category_key=='potions' else 'items.default_name')+'"')
            if fields.get('description') in (None,'name'):fields['description']=fields['name']
            fields.update(schema.generated_defaults)
            if category_key=='potions':
                fields={key:value for key,value in fields.items() if key.casefold()!='scemename'}
                fields['scemeName']=DEFAULT_POTION_SCHEME
            code=f'INSTANCE {instance} (C_Item)\n{{\n'+''.join(
                f'    {key} = {value};\n' for key,value in fields.items())+'};'
            code.encode('cp1251')
            if category_key!='potions':
                return self._write_new(instance,code)
            metadata={field.key:field.default for section in schema.sections for field in section.fields
                      if field.source=='editor_metadata' and field.default is not None}
            item=Item(instance,self.root/'__new__','project',code,{},0,len(code),editor_metadata=metadata)
            return self._import_component(item)
        cat=leaf_for(get_category(category_key))
        instance=self.new_id('GE_'+cat.key+'_Item')
        code=(f'INSTANCE {instance} (C_Item)\n{{\n'
              f'    name = "{title}";\n    mainflag = {cat.mainflag};\n'
              f'    flags = {cat.flags};\n    value = 0;\n'
              f'    description = name;\n}}')
        return self._write_new(instance,code)

    def duplicate(self,item:Item):
        """Duplicate a single item definition; original game files untouched."""
        instance=self.new_id(item.instance+'_Copy',prefix='ItSc_' if classify(item)=='scrolls' else 'GE_')
        code=replace_instance(item.text,item.instance,instance)
        if classify(item)=='potions':
            result=self._import_component(item,instance)
        else:result=self._write_new(instance,code)
        self.item_hierarchy.transfer(item,result,copy=True)
        return result

    def copy_to_project(self,item:Item):
        """Copy an original definition without renaming its INSTANCE or replacing a project edit."""
        existing=next((current for current in self.project_items if current.instance.casefold()==item.instance.casefold()),None)
        if existing is not None:return existing
        if classify(item)=='potions':
            return self._import_component(item)
        destination=self._destination_for(item)
        destination.parent.mkdir(parents=True,exist_ok=True)
        from .magic_parameters import import_mana_metadata
        imported=import_mana_metadata(self,item)
        if destination.exists():
            from .scripts import load_text
            text,codec=load_text(destination)
            destination.write_bytes((text.rstrip()+'\n\n'+imported+';\n').encode(codec))
        else:
            destination.write_bytes((ITEM_OVERRIDES_HEADER+'\n\n'+imported+';\n').encode(item.encoding))
        # Only the written script changed; rescanning the full Gothic installation is unnecessary.
        cached_magic=self.options_cache.get('magic_cost_constants')
        self._replace_project_file(destination,parse_items(destination,'project'))
        self.options_cache.clear()
        # The game's spell constants are unchanged by importing a project item.
        # Reuse their catalog while importing many runes/scrolls at once.
        if cached_magic is not None:self.options_cache['magic_cost_constants']=cached_magic
        return next(current for current in self.project_items if current.instance.casefold()==item.instance.casefold())

    def _destination_for(self,item:Item):
        if item.origin=='project':return item.path
        base=self._game_content()
        try:rel=item.path.relative_to(base)
        except ValueError:rel=Path('Items')/item.path.name
        return self._project_content()/rel

    def edit(self,item:Item,values:dict[str,str],instance=None,metadata=None):
        if not values and instance is None and metadata is None:return item
        target=instance if instance is not None else item.instance
        if instance is not None:
            self.components._safe_id(instance)
            if instance.casefold()!=item.instance.casefold() and self.exists(instance):
                raise ValueError(tr('project.file_exists'))
        if classify(item)=='potions' and not self.components.owns(item.path):
            item=self._import_component(item,as_override=item.origin=='project')
        if self.components.owns(item.path):
            updated=self.components.edit(item,values,instance,metadata)
            self._replace_project_file(item.path,[updated])
            old_model=ModelResolver.custom_model(item.path.parent)
            old_name=ModelResolver.generated_name(item.instance).casefold()
            if self.mesh_index.get(old_name)==old_model:self.mesh_index.pop(old_name)
            model=ModelResolver.custom_model(updated.path.parent)
            if model.is_file():self.mesh_index[ModelResolver.generated_name(updated.instance).casefold()]=model
            self.item_hierarchy.transfer(item,updated)
            return updated
        if item.origin=='game':item=self.copy_to_project(item)
        dest=self._destination_for(item)
        write_modified_item(item,dest,values,instance=instance,metadata=metadata)
        self._replace_project_file(item.path,parse_items(dest,'project'))
        result=next(x for x in self.items if x.instance.casefold()==target.casefold())
        self.item_hierarchy.transfer(item,result)
        return result

    def delete(self,item:Item):
        if item.origin!='project':raise ValueError(tr('project.cannot_delete_original'))
        if self.components.owns(item.path):
            self.components.delete(item)
            self.item_hierarchy.transfer(item)
            self.refresh()
            return
        from .scripts import load_text
        source,codec=load_text(item.path)
        parsed=parse_items(item.path,'project')
        target=next((x for x in parsed if x.instance.lower()==item.instance.lower()),None)
        if target is None:raise ValueError(tr('project.item_missing'))
        new=source[:target.begin]+source[target.end:]
        # A generated standalone file can be removed completely.
        if not any(x.instance.lower()!=item.instance.lower() for x in parsed) and (
                'GE_Generated' in item.path.parts or source.startswith(ITEM_OVERRIDES_HEADER)):
            item.path.unlink()
        else:
            item.path.write_bytes(new.encode(codec))
        self.item_hierarchy.transfer(item)
        self.refresh()
