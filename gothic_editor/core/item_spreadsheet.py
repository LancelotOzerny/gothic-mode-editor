"""Project item tables; match IDs, validate a complete batch, and preserve existing scripts."""
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from .categories import classify,EDITABLE_CATEGORIES,get_category
from .properties_schema import schema_for,property_key
from .property_lists import validate_expression
from .scripts import Item,mask_comments
from .xlsx import read_table,write_table

MODES={'replace':'С заменой','missing':'Только недостающее','update':'Обновление'}
CODE='Код'
CATEGORY='Категория'
METADATA='@metadata'
FIELD=re.compile(r'[A-Za-z_]\w*(?:\[\d+\])?\Z',re.ASCII)
STRING=re.compile(r'"(?:\\.|[^"\\])*"\Z')


@dataclass
class ImportResult:
    created:int=0
    updated:int=0
    skipped:int=0
    readonly:int=0
    backup:Path|None=None


def export_items(items,destination,on_progress=lambda *_:None):
    items=list(items)
    preferred=['name','description','mainflag','flags','value','visual','material','effect','scemename']
    keys={key for item in items for key in item.fields}
    fields=[key for key in preferred if key in keys]+sorted(keys-set(preferred))
    headers=[CODE,CATEGORY]+fields+[METADATA]
    rows=[headers]
    for item in items:
        rows.append([item.instance,classify(item)]+[item.fields.get(key,'') for key in fields]+
                    [json.dumps(item.editor_metadata,ensure_ascii=False) if item.editor_metadata else ''])
    write_table(destination,rows,on_progress)
    return len(items)


def _expression(value,row,key):
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]',value):raise ValueError(f'Строка {row}, {key}: управляющий символ')
    if STRING.fullmatch(value):pass
    else:
        code=mask_comments(value)
        code=re.sub(r'"(?:\\.|[^"\\])*"','0',code)
        code=code.replace('[','(').replace(']',')')
        if not validate_expression(code):raise ValueError(f'Строка {row}, {key}: нужно выражение Daedalus; текст укажите в кавычках')
    value.encode('cp1251')
    return value


class ItemSpreadsheetService:
    def __init__(self,repo):self.repo=repo

    def _plan(self,rows,mode):
        if mode not in MODES:raise ValueError('Неизвестный режим импорта')
        if not rows:raise ValueError('Первый лист XLSX пуст')
        headers=[]
        for raw in rows[0]:
            key=raw.strip()
            if key.casefold() in ('код','instance'):key=CODE
            elif key.casefold() in ('категория','category'):key=CATEGORY
            elif key!=METADATA:
                key=property_key(key)
                if not FIELD.fullmatch(key):raise ValueError(f'Неизвестная колонка: {raw}')
            if key in headers:raise ValueError(f'Повторяющаяся колонка: {raw}')
            headers.append(key)
        if CODE not in headers:raise ValueError('В первой строке нужна колонка «Код»')
        existing={item.instance.casefold():item for item in self.repo.items}
        seen=set()
        plan=[]
        result=ImportResult()
        for number,row in enumerate(rows[1:],2):
            if not any(value.strip() for value in row):continue
            if len(row)>len(headers) and any(row[len(headers):]):raise ValueError(f'Строка {number}: данные за пределами заголовков')
            cells=dict(zip(headers,row))
            instance=cells.get(CODE,'').strip()
            try:self.repo.components._safe_id(instance)
            except ValueError as exc:raise ValueError(f'Строка {number}: {exc}') from exc
            identifier=instance.casefold()
            if identifier in seen:raise ValueError(f'Строка {number}: повторяющийся код {instance}')
            seen.add(identifier)
            current=existing.get(identifier)
            if current is not None:instance=current.instance
            fields={key:value.strip() for key,value in cells.items()
                    if key not in (CODE,CATEGORY,METADATA) and value.strip()}
            category=cells.get(CATEGORY,'').strip().casefold() or (classify(current) if current else
                classify(Item(instance,Path(instance+'.d'),'project','',fields,0,0)))
            if category not in EDITABLE_CATEGORIES or (current and classify(current) not in EDITABLE_CATEGORIES):
                result.skipped+=1;result.readonly+=1
                continue
            if (mode=='missing' and current is not None) or (mode=='update' and current is None):
                result.skipped+=1
                continue
            if current is not None and category!=classify(current):raise ValueError(f'Строка {number}: нельзя менять категорию существующего предмета')
            metadata=None
            if cells.get(METADATA,'').strip():
                try:metadata=json.loads(cells[METADATA])
                except ValueError as exc:raise ValueError(f'Строка {number}: некорректный JSON в @metadata') from exc
                if not isinstance(metadata,dict) or any(not isinstance(key,str) or not isinstance(value,str) for key,value in metadata.items()):
                    raise ValueError(f'Строка {number}: @metadata должен быть объектом со строковыми значениями')
            for key,value in fields.items():
                if current is None or current.fields.get(key)!=value:_expression(value,number,key)
            if current is None:
                schema=schema_for(category)
                defaults={field.key:field.default for section in schema.sections for field in section.fields
                          if field.source=='property' and field.export and field.default not in (None,'')}
                defaults.update(schema.generated_defaults)
                defaults={property_key(key):value for key,value in defaults.items()}
                fields={**defaults,**fields}
                fields.setdefault('mainflag',get_category(category).mainflag)
                fields.setdefault('name','"Новый предмет"')
                fields.setdefault('description',fields['name'])
                metadata={**{field.key:field.default for section in schema.sections for field in section.fields
                             if field.source=='editor_metadata' and field.default is not None},**(metadata or {})}
            merged={**(current.fields if current else {}),**fields}
            candidate=Item(instance,Path(instance+'.d'),'project','',merged,0,0)
            if classify(candidate)!=category:raise ValueError(f'Строка {number}: код и mainflag не соответствуют категории {category}')
            fields={key:value for key,value in fields.items() if current is None or current.fields.get(key)!=value}
            plan.append((instance,category,fields,metadata,current))
        return plan,result

    def import_file(self,source,mode,on_progress=lambda *_:None):
        rows=read_table(source,on_progress)
        on_progress(0,1,'Проверка таблицы')
        plan,result=self._plan(rows,mode)
        if not plan:return result
        # Snapshot only paths that these operations can change, including shared .d files.
        targets={}
        for instance,category,_,_,current in plan:
            if current and self.repo.components.owns(current.path):path=current.path
            elif category=='potions':path=self.repo.components.folder(instance)
            elif current:path=self.repo._destination_for(current)
            else:path=self.repo._project_content()/'Items/GE_Generated'/(instance+'.d')
            self.repo.components.layout.checked(path)
            folder=category=='potions' and path.name!='item.json'
            if folder and path.exists():raise ValueError(f'Папка предмета уже существует: {path}')
            if current is None and path.exists():raise ValueError(f'Файл предмета уже существует: {path}')
            targets[path]=(folder,path.exists())
        backup=self.repo.root/'backups'/('xlsx-import-'+uuid4().hex)
        backup.mkdir(parents=True)
        for path,(_,exists) in targets.items():
            if exists:
                destination=backup/path.relative_to(self.repo.root)
                destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(path,destination)
        result.backup=backup
        try:
            for index,(instance,category,fields,metadata,original) in enumerate(plan,1):
                current=next((item for item in self.repo.items if item.instance.casefold()==instance.casefold()),None)
                if original is None:
                    self.repo.create_item_from_fields(instance,fields,metadata)
                    result.created+=1
                else:
                    if fields or metadata is not None:self.repo.edit(current,fields,metadata=metadata)
                    result.updated+=1
                on_progress(index,len(plan),f'Импорт: {instance}')
        except Exception:
            for path,(folder,exists) in targets.items():
                self.repo.components.layout.checked(path)
                if exists:shutil.copy2(backup/path.relative_to(self.repo.root),path)
                elif folder:
                    if path.exists():shutil.rmtree(path)
                else:path.unlink(missing_ok=True)
            self.repo.refresh()
            raise
        return result
