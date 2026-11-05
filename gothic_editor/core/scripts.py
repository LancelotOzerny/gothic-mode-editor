"""A conservative Daedalus item reader/writer. Source files are never overwritten by scanner."""
from __future__ import annotations
from .localization import tr
from dataclasses import dataclass
from pathlib import Path
import re

INST = re.compile(r'\bINSTANCE\s+([A-Za-z_]\w*)\s*\(\s*C_Item\s*\)\s*\{', re.I)
FIELD = re.compile(r'\b([A-Za-z_]\w*(?:\s*\[\s*\d+\s*\])?)\s*=\s*("(?:\\.|[^"\\])*"|[^;]+)\s*;', re.I)

ITEM_OVERRIDES_HEADER = '// Gothic Editor: item overrides'


def load_text(path: Path):
    raw = path.read_bytes()
    for codec in ('utf-8-sig', 'cp1251', 'cp1252'):
        try: return raw.decode(codec), codec
        except UnicodeDecodeError: pass
    return raw.decode('cp1251', errors='replace'), 'cp1251'

def mask_comments(source: str) -> str:
    """Hide comments without changing character offsets (or string literals)."""
    out = list(source); i=0; n=len(source)
    while i < n:
        if source[i] == '"':
            i+=1
            while i<n:
                if source[i]=='\\': i+=2
                elif source[i]=='"': i+=1;break
                else:i+=1
        elif source.startswith('//',i):
            e=source.find('\n',i);e=n if e<0 else e
            for k in range(i,e):out[k]=' '
            i=e
        elif source.startswith('/*',i):
            e=source.find('*/',i+2);e=n if e<0 else e+2
            for k in range(i,e):
                if source[k]!='\n':out[k]=' '
            i=e
        else:i+=1
    return ''.join(out)

def block_end(text: str, start: int) -> int:
    depth=0; quoted=False;escape=False
    for i in range(start,len(text)):
        c=text[i]
        if quoted:
            if escape:escape=False
            elif c=='\\':escape=True
            elif c=='"':quoted=False
        elif c=='"':quoted=True
        elif c=='{':depth+=1
        elif c=='}':
            depth-=1
            if depth==0:return i+1
    return -1

@dataclass
class Item:
    instance: str
    path: Path
    origin: str
    text: str
    fields: dict[str,str]
    begin: int
    end: int
    encoding: str = 'utf-8'

    @property
    def title(self):
        description=self.fields.get('description','').strip()
        name=self.fields.get('name','').strip()
        # Gothic often uses name=NAME_Trank (generic item type), while
        # description contains the actual potion name.
        if description and description.casefold()!='name' and not description.upper().startswith('NAME_'):
            return unquote(description)
        if name and not name.upper().startswith('NAME_'):
            return unquote(name)
        return unquote(description or name or self.instance)
    @property
    def visual(self):return unquote(self.fields.get('visual',''))

def unquote(value: str) -> str:
    value=value.strip()
    return value[1:-1] if len(value)>=2 and value[0]=='"' and value[-1]=='"' else value

def parse_items(path: Path, origin: str):
    source,encoding=load_text(path)
    masked=mask_comments(source)
    found=[]
    for hit in INST.finditer(masked):
        end=block_end(masked,hit.end()-1)
        if end<0:continue
        block=masked[hit.end():end-1]
        fields={re.sub(r'\s+','',m.group(1)).lower():m.group(2).strip() for m in FIELD.finditer(block)}
        found.append(Item(hit.group(1),path,origin,source[hit.start():end],fields,hit.start(),end,encoding))
    return found

def replace_field(block: str, key: str, value: str) -> str:
    masked=mask_comments(block)
    key_pat=re.escape(key).replace(r'\[',r'\s*\[\s*').replace(r'\]',r'\s*\]')
    rex=re.compile(r'\b'+key_pat+r'\s*=\s*(?:"(?:\\.|[^"\\])*"|[^;]+)\s*;',re.I)
    m=rex.search(masked)
    if m:
        raw=block[m.start():m.end()]
        eq=raw.index('=')
        return block[:m.start()]+raw[:eq+1]+' '+value+';'+block[m.end():]
    closing=block.rfind('}')
    if closing<0:raise ValueError(tr('scripts.incomplete'))
    return block[:closing]+'    '+key+' = '+value+';\n'+block[closing:]

def replace_instance(block: str, old: str, new: str) -> str:
    return re.sub(r'(\bINSTANCE\s+)'+re.escape(old)+r'(\s*\()',lambda m:m.group(1)+new+m.group(2),block,count=1,flags=re.I)

def write_modified_item(item:Item, destination:Path, updates:dict[str,str]):
    """Always write a project file; preserve all other item definitions verbatim."""
    source,codec=load_text(destination if destination.exists() else item.path)
    items=parse_items(destination if destination.exists() else item.path,'project')
    target=next((x for x in items if x.instance.lower()==item.instance.lower()),None)
    if not target:raise ValueError(tr('scripts.item_missing'))
    part=source[target.begin:target.end]
    for k,v in updates.items():part=replace_field(part,k,v)
    source=source[:target.begin]+part+source[target.end:]
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Source scripts from Gothic are commonly ANSI/CP1251; retain the encoding.
    # Avoid writing corrupt strings to a code page that cannot represent them.
    destination.write_bytes(source.encode(codec))

def merge_item_overrides(destination:Path, overrides:Path):
    """Replace selected INSTANCE blocks while retaining other items and helpers."""
    source,codec=load_text(destination)
    originals={item.instance.casefold():item for item in parse_items(destination,'game')}
    replacements=[]
    additions=[]
    for item in parse_items(overrides,'project'):
        original=originals.get(item.instance.casefold())
        if original is None:
            additions.append(item.text+';\n')
        else:
            replacements.append((original.begin,original.end,item.text))
    for start,end,text in sorted(replacements,reverse=True):
        source=source[:start]+text+source[end:]
    if additions:source=source.rstrip()+'\n\n'+'\n'.join(additions)
    destination.write_bytes(source.encode(codec))


def clean_id(label: str) -> str:
    name=re.sub('[^A-Za-z0-9_]','_',label).strip('_')
    return name or 'Item'
