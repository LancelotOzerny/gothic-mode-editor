"""Build item callbacks calling ordinary Daedalus functions with arguments."""
import hashlib
from pathlib import Path
import re

from .daedalus_merge import ScriptTree,definitions,target_path
from .item_actions import ActionCatalog,assignments,argument_literal,read_functions
from .item_layout import project_scripts
from .scripts import load_text


def prepare_actions(store,content,tree,helpers,script_items=()):
    catalog=ActionCatalog(store.layout.project,content)
    scheduled=[]
    records=[(file,store._read(file),None) for file in store.files()]
    records.extend((item.path,{'instance':item.instance,'editor_metadata':item.editor_metadata},item.fields)
                   for item in script_items)
    for file,data,fields in records:
        try:rows=assignments(data.get('editor_metadata',{}).get('item_actions',''))
        except ValueError as exc:raise ValueError(f'{file}: {exc}') from exc
        calls=[]
        for row in rows:
            if not row['id']:continue
            try:
                function=catalog.resolve(row['id'])
                unknown=set(row['values'])-{parameter.name for parameter in function.parameters}
                if unknown:raise ValueError('Неизвестные параметры: '+', '.join(sorted(unknown)))
                arguments=[]
                for parameter in function.parameters:
                    value = row['values'].get(parameter.name,parameter.default)
                    if parameter.options and value not in {option for _, option in parameter.options}:
                        raise ValueError(f'{parameter.label}: выберите значение из списка.')
                    arguments.append(argument_literal(parameter,value))
                calls.append((function,arguments))
            except (OSError,ValueError) as exc:raise ValueError(f'{file}: {exc}') from exc
        if calls:scheduled.append((file,data,calls,fields))
    if not scheduled:return {},[],set(),tree
    affected=set()
    copied={}
    helper_source='\n'.join(helpers)
    helper_names={name.casefold() for definition in definitions(helper_source,'item helpers') for name in definition.names}
    for file,data,calls,fields in scheduled:
        for function,_ in calls:
            location=tree.unique(function.name,'func')
            outside=(function.identifier.startswith('project:') and
                     (project_scripts(store.layout.project)/'Content') not in function.path.resolve().parents)
            if outside and function.path not in copied:
                if location is not None:
                    raise ValueError(f'{function.path}: конфликт функции {function.name} с {location[0]}. '
                                     'Для изменения игровой функции используйте копию в Scripts/Content.')
                source,_=load_text(function.path)
                for definition in definitions(source,function.path):
                    for name in definition.names:
                        if tree.symbols.get(name.casefold()) or name.casefold() in helper_names:
                            raise ValueError(f'{function.path}: конфликт идентификатора {name}')
                token=hashlib.sha256(function.path.relative_to(store.layout.project).as_posix().encode()).hexdigest()[:12]
                relative=Path('GE_ActionScripts')/(token+'.d')
                destination=target_path(content,relative)
                if destination.exists():raise ValueError(f'Занят путь сгенерированного скрипта: {destination}')
                destination.parent.mkdir(parents=True,exist_ok=True)
                destination.write_bytes(source.encode('cp1251'))
                copied[function.path]=destination
                affected.add(relative)
                tree=ScriptTree(content)
                location=tree.unique(function.name,'func')
            if location is None:raise ValueError(f'{file}: функция {function.name} отсутствует в исходниках сборки.')
            path,definition=location
            actual=next((value for value in read_functions(path,'staged',tree.documents[path].text)
                         if value.name.casefold()==function.name.casefold()),None)
            signature=lambda value:tuple((parameter.name.casefold(),parameter.kind) for parameter in value.parameters)
            if actual is None or signature(actual)!=signature(function):
                raise ValueError(f'{file}: сигнатура {function.name} изменилась; выберите действие заново.')
            affected.add(path.relative_to(content))
    handlers={}
    sources=[]
    for file,data,calls,fields in scheduled:
        fields=store.read_item(file).fields if fields is None else fields
        previous=fields.get('on_state[0]','').strip()
        handler='GE_ItemActions_'+data['instance']
        body=[]
        if previous and previous!='0':
            if not re.fullmatch(r'[A-Za-z_]\w*',previous,re.ASCII):
                raise ValueError(f'{file}: невозможно сохранить выражение on_state[0]: {previous}')
            location=tree.unique(previous,'func')
            source=tree.documents[location[0]].text if location else helper_source
            original=next((value for value in read_functions(Path(str(file)+' helpers'),'manual',source)
                           if value.name.casefold()==previous.casefold()),None)
            if original is None or original.parameters or previous.casefold()==handler.casefold():
                raise ValueError(f'{file}: on_state[0] должен ссылаться на существующую void-функцию без параметров: {previous}')
            body.append(previous+'();')
        body.extend(function.name+'('+', '.join(arguments)+');' for function,arguments in calls)
        sources.append('func void '+handler+'()\n{\n    '+'\n    '.join(body)+'\n};')
        handlers[data['instance'].casefold()]=handler
    return handlers,sources,affected,tree
