"""JSON-backed potion components. Never modify original Daedalus scripts.

Each INSTANCE is saved as Assets/Items/Potions/<INSTANCE>.json.
Legacy folders are supported for reading until explicitly migrated.
"""
from __future__ import annotations
import json
import os
import re
from pathlib import Path
from .scripts import Item, INST, FIELD, block_end, mask_comments, replace_field, replace_instance, load_text
from .item_layout import ItemLayout
from .model_resolver import ModelResolver
from .potion_schemes import imported_potion_scheme

class PotionComponents:
    def __init__(self, root: Path):
        self.layout = ItemLayout(root)
        self.root = self.layout.root

    def files(self):
        return self.layout.files()

    def owns(self, path):
        return self.layout.owns(path)

    @staticmethod
    def _safe_id(value):
        if not re.fullmatch(r'[A-Za-z_]\w*',value,flags=re.ASCII):
            raise ValueError('Неверный идентификатор Daedalus: '+value)
        return value

    def folder(self, instance):
        """Legacy folder location, retained for old projects."""
        return self.layout.folder(self._safe_id(instance))

    def item_path(self, instance):
        return self.layout.path_for(self._safe_id(instance))

    def _atomic_json(self, target, data):
        target.parent.mkdir(parents=True, exist_ok=True)
        temp=target.with_name(target.name+'.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
        temp.replace(target)

    def _read(self, path):
        data=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data,dict) or data.get('format') != 'gothic-potion-v1':
            raise ValueError('Неизвестный формат зелья: '+str(path))
        self._safe_id(data['instance'])
        return data

    def list_items(self):
        return [self.read_item(file) for file in self.files()]

    def read_item(self, file):
        data=self._read(file)
        block=self.render_instance(data,file.parent)
        masked=mask_comments(block)
        match=INST.search(masked)
        if match is None:raise ValueError('Не удалось распознать '+str(file))
        end=block_end(masked,match.end()-1)
        if end<0:raise ValueError('Незавершённый INSTANCE: '+str(file))
        fields={re.sub(r'\s+','',m.group(1)).lower():m.group(2).strip() for m in FIELD.finditer(masked[match.end():end-1])}
        return Item(data['instance'],file,'project',block,fields,0,len(block),'utf-8',data.get('editor_metadata',{}))

    def import_item(self, item:Item, instance=None, as_override=False):
        target=self._safe_id(instance or item.instance)
        destination=self.item_path(target)
        if (any(path.stem.casefold()==target.casefold() for path in self.layout.root.glob('*.json'))
                or (self.layout.find_folder(target)/'item.json').is_file()):
            raise ValueError('Предмет уже существует: '+target)
        source=replace_instance(item.text,item.instance,target) if target!=item.instance else item.text
        original=self._read(item.path) if self.owns(item.path) else None
        fields=dict(original['fields'] if original else item.fields)
        for key,value in fields.items():
            if key.casefold()=='scemename':fields[key]=imported_potion_scheme(value)
        if original:source=replace_instance(original['template'],item.instance,target)
        data={'format':'gothic-potion-v1','instance':target,'source_instance':item.instance if target==item.instance and (item.origin=='game' or as_override) else None,
              'source_file':self._relative_game_file(item) if target==item.instance and item.origin=='game' else None,
              'fields':fields,'template':source}
        if item.editor_metadata:data['editor_metadata']=dict(item.editor_metadata)
        self._atomic_json(destination,data)
        return destination

    @staticmethod
    def _related_functions(item):
        """Save original functions as references, not duplicate emitted declarations."""
        if not item.path.is_file():return []
        source,_=load_text(item.path)
        masked=mask_comments(source)
        functions=[]
        for key,value in item.fields.items():
            if not key.startswith('on_state') or not re.fullmatch(r'[A-Za-z_]\w*', value):continue
            pattern=re.compile(r'\bfunc\s+(?:void|int|float|string)\s+'+re.escape(value)+r'\s*\([^)]*\)\s*\{',re.I)
            m=pattern.search(masked)
            if not m:continue
            end=block_end(masked,m.end()-1)
            if end<0:continue
            functions.append({'code':value,'source':source[m.start():end], 'override':False})
        return functions

    @staticmethod
    def _related_constants(item):
        """Informational snapshots of constants used by the potion and its callback."""
        if not item.path.is_file():return []
        source,_=load_text(item.path)
        functions=PotionComponents._related_functions(item)
        referenced=item.text+'\n'+'\n'.join(f['source'] for f in functions)
        result=[]
        declaration=re.compile(r'\bconst\s+(int|float|string)\s+([A-Za-z_]\w*)\s*=\s*([^;]+);',re.I)
        for match in declaration.finditer(mask_comments(source)):
            name=match.group(2)
            if re.search(r'\b'+re.escape(name)+r'\b',referenced):
                result.append({'type':match.group(1),'code':name,'expression':source[match.start(3):match.end(3)].strip(), 'override':False})
        return result

    @staticmethod
    def _relative_game_file(item):
        path=item.path.as_posix()
        marker='/Content/'
        if marker.lower() in path.lower():return path[path.lower().rfind(marker.lower())+len(marker):]
        return 'Items/'+item.path.name

    def edit(self,item,updates,instance=None,metadata=None):
        data=self._read(item.path)
        target=self._safe_id(instance) if instance is not None else data['instance']
        legacy = item.path.name == 'item.json'
        destination = (item.path if target==data['instance'] else
                       (item.path.parent.with_name(target)/'item.json' if legacy else self.item_path(target)))
        self.layout.checked(destination)
        if destination!=item.path and destination.exists():
            raise ValueError('Предмет уже существует: '+target)
        if target!=data['instance']:
            renamed=target.casefold()!=data['instance'].casefold()
            data['template']=replace_instance(data['template'],data['instance'],target)
            data['instance']=target
            if renamed:
                data['source_instance']=None
                data['source_file']=None
        for key,value in updates.items():
            data['fields'][key.lower()]=value
        if metadata is not None:data.setdefault('editor_metadata',{}).update(metadata)
        # Validate encoding to avoid broken Russian strings when building CP1251 Gothic data.
        self.render_instance(data).encode('cp1251')
        if legacy and destination!=item.path:
            item.path.parent.rename(destination.parent)
        elif destination!=item.path:
            self._atomic_json(destination,data)
            item.path.unlink()
            return self.read_item(destination)
        self._atomic_json(destination,data)
        return self.read_item(destination)

    def delete(self,item):
        import shutil
        if not self.owns(item.path):
            raise ValueError('Это не компонент проекта')
        if item.path.name == 'item.json':shutil.rmtree(item.path.parent)
        else:item.path.unlink()

    @staticmethod
    def render_instance(data,folder=None):
        code=data['template']
        original={re.sub(r'\s+','',m.group(1)).lower():m.group(2).strip()
                  for m in FIELD.finditer(mask_comments(code))}
        for key,value in data['fields'].items():
            if original.get(re.sub(r'\s+','',key).lower())==value:continue
            code=replace_field(code,key,value)
        if folder is not None and ModelResolver.custom_model(folder).is_file():
            code=replace_field(code,'visual',ModelResolver.visual(data,folder))
        return code

    def generated(self,action_handlers=None):
        """Return original replacements and NEW instances, plus user-authored helpers."""
        replacements={}; additions=[]; helpers=[]
        identifiers={}
        for file in self.files():
            data=self._read(file)
            identifier=data['instance'].casefold()
            if identifier in identifiers:
                raise ValueError(f'Неоднозначный INSTANCE {data["instance"]}: {identifiers[identifier]} / {file}')
            identifiers[identifier]=file
            block=self.render_instance(data,file.parent)
            if action_handlers and identifier in action_handlers:
                block=replace_field(block,'on_state[0]',action_handlers[identifier])
            if data.get('source_instance'):
                replacements[data['instance'].casefold()]=block
            else:
                additions.append(block)
            if file.name != 'item.json':continue  # Flat JSON items have no sidecar files.
            folder=file.parent
            params=folder/'params.json'
            if params.exists():
                params_data=json.loads(params.read_text('utf-8'))
                for variable in params_data.get('variables',[]):
                    identifier=self._safe_id(variable['code'])
                    if variable['type'] not in ('int','float','string'):
                        raise ValueError('Неизвестный тип переменной: '+str(variable['type']))
                    helpers.append(f"var {variable['type']} {identifier};")
            func=folder/'functions.d'
            if func.exists():
                source=func.read_text('utf-8').strip()
                if mask_comments(source).strip():helpers.append(source)
        return replacements,additions,helpers
