"""NPC appearance overrides; source Daedalus stays read-only until build staging."""
from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
from uuid import uuid4

from .asset_files import AssetFiles
from .daedalus_merge import _tokens, ScriptTree
from .item_layout import project_scripts
from .scripts import load_text, mask_comments, block_end, unquote


DECL = re.compile(r'\b(instance|prototype)\s+(\w+)\s*\(\s*(\w+)\s*\)\s*\{', re.I)


def calls(source):
    tokens = list(_tokens(source, 'NPC'))
    result = []
    for i, token in enumerate(tokens[:-1]):
        if token.kind != 'name':continue
        if tokens[i+1].value != '(':continue
        depth, start, args = 1, tokens[i+1].end, []
        for next_token in tokens[i+2:]:
            if next_token.kind == 'symbol':
                if next_token.value == '(':depth += 1
                elif next_token.value == ')':depth -= 1
                if (next_token.value == ',' and depth == 1) or depth == 0:
                    args.append(source[start:next_token.start].strip())
                    start = next_token.end
                if depth == 0:break
        if args==['']:args=[]
        if depth == 0 and (not args or args[0].casefold() == 'self'):result.append((token.value.casefold(),args))
    return result


@dataclass(frozen=True)
class Npc:
    instance: str
    title: str
    path: Path
    visual: str = ''
    body_args: tuple = ()
    overridden: bool = False

    @property
    def body(self):return unquote(self.body_args[0]) if self.body_args else ''
    @property
    def head(self):return unquote(self.body_args[3]) if self.body_args else ''
    @property
    def armor(self):return self.body_args[6] if self.body_args else '-1'


def quote(value):
    return '"' + value.replace('\\','\\\\').replace('"','\\"') + '"'


class NpcStore:
    FIELDS = {'name','visual','body','head','armor'}

    def __init__(self, project):
        self.project = Path(project).resolve()
        self.files = AssetFiles(self.project)
        self.path = self.project/'Assets/NPC/overrides.json'

    def read(self):
        self.files.checked(self.path)
        if not self.path.exists():return {}
        data = json.loads(self.path.read_text('utf-8'))
        if not isinstance(data,dict) or data.get('version') != 1 or not isinstance(data.get('npcs'),dict):
            raise ValueError(f'{self.path}: неверный список NPC.')
        for name, values in data['npcs'].items():
            if not re.fullmatch(r'[A-Za-z_]\w*',name,re.ASCII):raise ValueError(f'{self.path}: неверный NPC {name}')
            self.validate(values)
        return data['npcs']

    def validate(self, values):
        if not isinstance(values,dict) or set(values)-self.FIELDS:raise ValueError(f'{self.path}: неизвестные свойства NPC.')
        for key,value in values.items():
            if not isinstance(value,str):raise ValueError(f'{self.path}: {key} должен быть строкой.')
            value.encode('cp1251')
            if key == 'name':
                if not value.strip() or any(ord(c)<32 for c in value):raise ValueError('Укажите имя NPC без переносов строк.')
            elif key == 'armor':
                if value != '-1' and not re.fullmatch(r'[A-Za-z_]\w*',value,re.ASCII):raise ValueError('Укажите ID брони или «Нет».')
            elif value:
                AssetFiles.name(value)
                if not re.fullmatch(r'[\w .-]+',value):raise ValueError('Некорректное имя модели NPC: '+value)
            elif key != 'head':raise ValueError('Модель не может быть пустой.')

    def save(self, instance, values):
        self.validate(values)
        data = self.read()
        if values:data[instance.casefold()] = values
        else:data.pop(instance.casefold(),None)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary = self.path.with_name('.npc-'+uuid4().hex+'.tmp')
        try:
            temporary.write_text(json.dumps({'version':1,'npcs':data},ensure_ascii=False,indent=2),encoding='utf-8')
            temporary.replace(self.path)
        finally:temporary.unlink(missing_ok=True)

    def apply(self, npc, values):
        args = list(npc.body_args)
        if args:
            for key,index in (('body',0),('head',3),('armor',6)):
                if key in values:args[index] = values[key] if key=='armor' else quote(values[key])
        return replace(npc,title=values.get('name',npc.title),visual=values.get('visual',npc.visual),
                       body_args=tuple(args),overridden=bool(values))


class NpcCatalog:
    def __init__(self, project, game=None, content=None):
        self.project, self.game = Path(project), Path(game) if game else None
        self.content = content
        self.constants = {}
        self.records = {}
        self.helpers = {}

    def load(self):
        roots = [Path(self.content)] if self.content else ([self.game/'_work/Data/Scripts/Content'] if self.game else []) + [project_scripts(self.project)/'Content']
        for root in roots:
            for path in sorted(root.rglob('*')):
                if not path.is_file() or path.suffix.lower()!='.d':continue
                text,_=load_text(path)
                masked=mask_comments(text)
                for match in re.finditer(r'\bfunc\s+void\s+(\w+)\s*\(\s*\)\s*\{',masked,re.I):
                    end=block_end(masked,match.end()-1)
                    if end>0:self.helpers[match[1].casefold()]=text[match.end():end-1]
                for match in re.finditer(r'\bconst\s+(int|string)\s+(\w+)\s*=\s*([^;]+);',masked,re.I):
                    self.constants[match[2].casefold()]=match[3].strip()
                for match in DECL.finditer(masked):
                    end=block_end(masked,match.end()-1)
                    if end<0:continue
                    self.records[match[2].casefold()]=(match[2],match[1].casefold(),match[3].casefold(),
                                                     text[match.start():end],path)
        store=NpcStore(self.project)
        overrides=store.read()
        self.base={}
        for key,record in self.records.items():
            if record[1]!='instance':continue
            chain, parent, seen = [], key, set()
            while parent in self.records and parent not in seen:
                seen.add(parent)
                item=self.records[parent]
                chain.append(item)
                parent=item[2]
            if parent!='c_npc':continue
            title, visual, args = record[0], '', ()
            for item in reversed(chain):
                masked=mask_comments(item[3])
                names=list(re.finditer(r'\bname\s*(?:\[\s*0\s*\])?\s*=\s*("(?:\\.|[^"\\])*"|[^;]+);',masked,re.I))
                if names:title=unquote(self.resolve(names[-1][1]))
                for kind,params in self.appearance_calls(item[3]):
                    if kind=='mdl_setvisual' and len(params)==2:visual=unquote(self.resolve(params[1]))
                    elif kind=='mdl_setvisualbody' and len(params)==8:args=tuple(params[1:])
                    elif kind=='b_setnpcvisual' and len(params)==6:
                        female=self.resolve(params[1]).upper() in ('FEMALE','1')
                        body_tex=params[4]
                        if female:
                            number=self.integer(body_tex)
                            if number is not None and 0<=number<=3:body_tex=str(number+4)
                        visual='HUMANS.MDS'
                        args=(quote('Hum_Body_Babe0' if female else 'Hum_Body_Naked0'),body_tex,'0',params[2],params[3],'0',params[5])
            npc=Npc(record[0],title,record[4],visual,args)
            self.base[key]=npc
        return sorted((store.apply(npc,overrides.get(key,{})) for key,npc in self.base.items()),
                      key=lambda npc:(npc.title.casefold(),npc.instance.casefold()))

    def resolve(self, value, seen=()):
        value=value.strip()
        key=value.casefold()
        if key in self.constants and key not in seen:return self.resolve(self.constants[key],seen+(key,))
        return value

    def appearance_calls(self, source, seen=()):
        for kind,params in calls(source):
            if kind in ('b_setnpcvisual','mdl_setvisual','mdl_setvisualbody'):yield kind,params
            elif not params and kind in self.helpers and kind not in seen:
                yield from self.appearance_calls(self.helpers[kind],seen+(kind,))

    def integer(self, value):
        value=self.resolve(value)
        return int(value) if re.fullmatch(r'[+-]?\d+',value) else None


def apply_npc_overrides(project, content):
    store=NpcStore(project)
    overrides=store.read()
    if not overrides:return []
    catalog=NpcCatalog(project,content=content)
    catalog.load()
    tree=ScriptTree(content)
    changes={}
    for key,values in overrides.items():
        npc=catalog.base.get(key)
        if npc is None:raise ValueError(f'{store.path}: NPC {key} не найден в исходниках.')
        location=tree.unique(npc.instance,'instance')
        path,definition=location
        source=tree.documents[path].text[definition.start:definition.end]
        body=[]
        if 'name' in values:body.append('name[0] = '+quote(values['name'])+';')
        if 'visual' in values:body.append('Mdl_SetVisual(self, '+quote(values['visual'])+');')
        if set(values)&{'visual','body','head','armor'}:
            if not npc.body_args:raise ValueError(f'{npc.path}: внешность {npc.instance} задаётся неподдерживаемым скриптом.')
            updated=store.apply(npc,values)
            body.append('Mdl_SetVisualBody(self, '+', '.join(updated.body_args)+');')
        closing=mask_comments(source).rfind('}')
        updated=source[:closing]+'\n    // Gothic Editor: NPC appearance\n    '+'\n    '.join(body)+'\n'+source[closing:]
        changes.setdefault(path,[]).append((definition.start,definition.end,updated))
    tree.apply(changes)
    return [path.relative_to(content) for path in changes]
