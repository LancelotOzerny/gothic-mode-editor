"""Project management and safe copy-on-write repository."""
from __future__ import annotations
import json,re,os
from .localization import tr
from pathlib import Path
from .scripts import Item,parse_items,replace_field,replace_instance,write_modified_item,clean_id,ITEM_OVERRIDES_HEADER
from .categories import classify,get_category,leaf_for
from .archive_models import ArchiveModels
from .potion_components import PotionComponents

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
        self.archive_models=ArchiveModels()

    def create(self,root:Path,name:str):
        root=root.resolve();root.mkdir(parents=True,exist_ok=True)
        config=root/'project.json'
        if config.exists():raise ValueError(tr('project.already_exists'))
        (root/'Scripts'/'Content'/'Items').mkdir(parents=True,exist_ok=True)
        (root/'Assets'/'Models').mkdir(parents=True,exist_ok=True)
        config.write_text(json.dumps({'name':name,'game_path':''},ensure_ascii=False,indent=2),encoding='utf-8')
        self.open(root)

    def open(self,root:Path):
        root=root.resolve();cfg=root/'project.json'
        if not cfg.is_file():raise ValueError(tr('project.not_project'))
        data=json.loads(cfg.read_text('utf-8'))
        self.name=data.get('name',root.name)
        resources=data if self.shared_resources is None else {**data,**self.shared_resources}
        raw=resources.get('game_path','')
        game=Path(raw).resolve() if raw else None
        self._validate_roots(root,game)
        self.root=root
        self.components=PotionComponents(root)
        self.game=game
        self.compiler_path=resources.get('compiler_path','')
        self.resource_editor_path=resources.get('resource_editor_path','')
        self.refresh()

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

    def _project_content(self):return self.root/'Scripts'/'Content'

    def refresh(self):
        if not self.root:return
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
        if game_content and self.root not in game_content.parents and game_content!=self.root:
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
        self.mesh_index={}
        for base in (self.root/'Assets',self.root/'Scripts',self.game/'_work'/'data'/'Meshes' if self.game else None):
            if base and base.exists():
                for directory,_,names in os.walk(base):
                    for name in names:
                        if name.lower().endswith('.3ds'):
                            self.mesh_index.setdefault(name.lower(),Path(directory)/name)
        self.errors.extend(self.archive_models.refresh(self.root,self.game))

    def exists(self,instance):return any(it.instance.casefold()==instance.casefold() for it in self.items)

    def new_id(self,original='GE_Item'):
        base=clean_id(original)
        if not base.startswith('GE_'):base='GE_'+base
        candidate=base;n=2
        while self.exists(candidate):candidate=f'{base}_{n}';n+=1
        return candidate

    def _write_new(self,instance,code):
        folder=self._project_content()/'Items'/'GE_Generated'
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/(instance+'.d')
        if path.exists():raise ValueError(tr('project.file_exists'))
        path.write_text('// Generated by Gothic Editor\n'+code.strip()+'\n',encoding='cp1251')
        self.refresh()
        return next(x for x in self.items if x.instance==instance)

    def create_item(self,category_key,name=None):
        title=(name or tr('items.default_name')).replace('\\','\\\\').replace('"','\\"')
        if category_key=='potions':
            instance=self.new_id('GE_ItPo_New')
            code=(f'INSTANCE {instance} (C_Item)\n{{\n'
                  f'    name = NAME_Trank;\n    mainflag = ITEM_KAT_POTIONS;\n'
                  f'    flags = ITEM_MULTI;\n    value = 0;\n'
                  f'    visual = "ItPo_Perm_Health.3ds";\n'
                  f'    material = MAT_GLAS;\n    scemeName = "POTIONFAST";\n'
                  f'    description = "{title if name else tr("items.default_potion")}";\n}};')
            item=Item(instance,self.root/'__new__','project',code,{},0,len(code))
            self.components.import_item(item)
            self.refresh()
            return next(x for x in self.project_items if x.instance==instance)
        cat=leaf_for(get_category(category_key))
        instance=self.new_id('GE_'+cat.key+'_Item')
        code=(f'INSTANCE {instance} (C_Item)\n{{\n'
              f'    name = "{title}";\n    mainflag = {cat.mainflag};\n'
              f'    flags = {cat.flags};\n    value = 0;\n'
              f'    description = name;\n}}')
        return self._write_new(instance,code)

    def duplicate(self,item:Item):
        """Duplicate a single item definition; original game files untouched."""
        instance=self.new_id(item.instance+'_Copy')
        code=replace_instance(item.text,item.instance,instance)
        if classify(item)=='potions':
            self.components.import_item(item,instance)
            self.refresh()
            return next(x for x in self.project_items if x.instance==instance)
        return self._write_new(instance,code)

    def copy_to_project(self,item:Item):
        """Copy an original definition without renaming its INSTANCE or replacing a project edit."""
        existing=next((current for current in self.project_items if current.instance.casefold()==item.instance.casefold()),None)
        if existing is not None:return existing
        if classify(item)=='potions':
            self.components.import_item(item)
            self.refresh()
            return next(x for x in self.project_items if x.instance.casefold()==item.instance.casefold())
        destination=self._destination_for(item)
        destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists():
            from .scripts import load_text
            text,codec=load_text(destination)
            destination.write_bytes((text.rstrip()+'\n\n'+item.text+';\n').encode(codec))
        else:
            destination.write_bytes((ITEM_OVERRIDES_HEADER+'\n\n'+item.text+';\n').encode(item.encoding))
        self.refresh()
        return next(current for current in self.project_items if current.instance.casefold()==item.instance.casefold())

    def _destination_for(self,item:Item):
        if item.origin=='project':return item.path
        base=self._game_content()
        try:rel=item.path.relative_to(base)
        except ValueError:rel=Path('Items')/item.path.name
        return self._project_content()/rel

    def edit(self,item:Item,values:dict[str,str]):
        if not values:return item
        if item.path.name=='item.json' and item.path.parent.parent==self.components.root:
            self.components.edit(item,values)
            self.refresh()
            return next(x for x in self.project_items if x.instance.casefold()==item.instance.casefold())
        if item.origin=='game':item=self.copy_to_project(item)
        dest=self._destination_for(item)
        write_modified_item(item,dest,values)
        self.refresh()
        return next(x for x in self.items if x.instance.casefold()==item.instance.casefold())

    def delete(self,item:Item):
        if item.origin!='project':raise ValueError(tr('project.cannot_delete_original'))
        if item.path.name=='item.json' and item.path.parent.parent==self.components.root:
            self.components.delete(item)
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
        self.refresh()
