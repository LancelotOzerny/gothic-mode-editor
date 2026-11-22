"""Daedalus function descriptions, argument values and editor action assignments."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re

from .daedalus_merge import definitions
from .item_layout import project_scripts
from .scripts import load_text, mask_comments


@dataclass(frozen=True)
class ActionParameter:
    name: str
    kind: str
    label: str
    options: tuple[tuple[str, str], ...] = ()

    @property
    def default(self):return '' if self.kind=='string' else '0'


@dataclass(frozen=True)
class ActionFunction:
    identifier: str
    name: str
    label: str
    parameters: tuple
    path: Path


def annotation_values(text):
    return {match[1].upper():match[2].strip().strip('"') for match in
            re.finditer(r'\b([A-Za-z_]+)\s*=\s*("[^"\r\n]*"|.*?)(?=\s+[A-Za-z_]+\s*=|$)',text)}


def read_functions(path, prefix, source=None):
    source=load_text(path)[0] if source is None else source
    masked=mask_comments(source)
    result=[]
    for definition in definitions(source,path):
        if definition.kind!='func':continue
        header=re.match(r'func\s+void\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*\{',
                        masked[definition.start:definition.end],re.I|re.ASCII)
        if header is None:continue
        comments=[]
        for line in reversed(source[:definition.start].splitlines()):
            if line.strip().startswith('//'):comments.append(line.strip()[2:].strip())
            elif line.strip():break
        info={}; labels={}
        for line in reversed(comments):
            if line.upper().startswith('@INFO '):info.update(annotation_values(line[6:]))
            if line.upper().startswith('@PARAM '):
                values=annotation_values(line[7:])
                if 'VALUE' in values and 'NAME' in values:
                    key=values['VALUE'].casefold()
                    caption=values['NAME']
                elif len(values)==1:
                    key,caption=next(iter(values.items()))
                    key=key.casefold()
                else:
                    raise ValueError(f'{path}: {header[1]}: ожидается @PARAM VALUE=аргумент NAME="Подпись"')
                if not key or not caption:raise ValueError(f'{path}: пустое имя или подпись @PARAM')
                if key in labels:raise ValueError(f'{path}: повторный @PARAM {key}')
                labels[key]=caption
        parameters=[]
        supported=True
        for raw in header[2].split(',') if header[2].strip() else []:
            parameter=re.fullmatch(r'\s*(?:var\s+)?(int|float|string)\s+([A-Za-z_]\w*)\s*',raw,re.I|re.ASCII)
            if parameter is None:supported=False;break
            parameters.append(ActionParameter(parameter[2],parameter[1].lower(),labels.get(parameter[2].casefold(),parameter[2])))
        if not supported:continue
        unknown=set(labels)-{parameter.name.casefold() for parameter in parameters}
        if unknown:raise ValueError(f'{path}: {header[1]}: @PARAM не соответствует аргументу: {", ".join(sorted(unknown))}')
        result.append(ActionFunction(prefix+'#'+header[1],header[1],info.get('NAME') or header[1],tuple(parameters),Path(path)))
    return result


def assignments(raw):
    rows=json.loads(raw) if raw else []
    if not isinstance(rows,list) or len(rows)>5:raise ValueError('Допустимо не более пяти действий.')
    result=[]
    for row in rows:
        if isinstance(row,str):row={'id':row,'values':{}}
        if (not isinstance(row,dict) or set(row)-{'id','values'} or not isinstance(row.get('id'),str)
                or not isinstance(row.get('values',{}),dict)
                or any(not isinstance(k,str) or not isinstance(v,str) for k,v in row.get('values',{}).items())):
            raise ValueError('Некорректные данные назначенного действия.')
        result.append({'id':row['id'],'values':dict(row.get('values',{}))})
    return result


def argument_literal(parameter,value):
    if parameter.kind=='string':
        if any(ord(char)<32 for char in value):raise ValueError('Строка содержит управляющие символы.')
        value.encode('cp1251')
        return '"'+value.replace('\\','\\\\').replace('"','\\"')+'"'
    value=value.strip()
    if parameter.kind=='int':
        if not re.fullmatch(r'[+-]?\d+',value,re.ASCII):raise ValueError('Введите целое число.')
        number=int(value)
        if not -2147483648<=number<=2147483647:raise ValueError('Целое число выходит за диапазон Daedalus.')
        return str(number)
    try:number=float(value)
    except ValueError:raise ValueError('Введите число.') from None
    if not math.isfinite(number) or abs(number)>3.402823466e38:raise ValueError('Число выходит за диапазон float.')
    return repr(number)


class ActionCatalog:
    def __init__(self,project,game_content=None):
        self.project=Path(project).resolve()
        self.game_content=Path(game_content).resolve() if game_content else None
        self.functions={}
        self._files={}
        self._group_options=None

    def _read(self,path,prefix):
        key=str(path)
        if key not in self._files:
            values=read_functions(path,prefix)
            self._files[key]=values
            self.functions.update((value.identifier.casefold(),value) for value in values)
        return self._files[key]

    def _recipe_action(self):
        from .recipe_learning import ACTION_ID, recipe_options
        options = recipe_options(self.project)
        if not options:
            return None
        return ActionFunction(
            ACTION_ID, 'GE_LearnRecipe', 'Изучить рецепт',
            (ActionParameter('recipe', 'int', 'Рецепт', options),),
            self.project / 'GE_Recipes' / 'Learning.d')

    def groups(self):
        from .localization import tr
        if self._group_options is not None:
            return self._group_options
        groups=[]
        roots=[(tr('item_actions.project'),project_scripts(self.project),'project:',self.project),
               (tr('item_actions.standard'),self.game_content,'game:Content/',self.game_content)]
        for title,root,prefix,relative in roots:
            options=[]
            if root is not None and root.is_dir():
                for path in sorted(root.rglob('*')):
                    if not path.is_file() or path.suffix.lower()!='.d' or root.resolve() not in path.resolve().parents:continue
                    key=prefix+path.relative_to(relative).as_posix()
                    for function in self._read(path,key):
                        options.append((f'{function.label} — {function.name} ({path.relative_to(root).as_posix()})',function.identifier))
            groups.append((title,sorted(options,key=lambda pair:pair[0].casefold())))
        recipe_action = self._recipe_action()
        if recipe_action:
            groups.insert(0, ('Алхимия', [('Изучить рецепт — GE_LearnRecipe', recipe_action.identifier)]))
            self.functions[recipe_action.identifier.casefold()] = recipe_action
        self._group_options=groups
        return groups

    def resolve(self,identifier):
        from .recipe_learning import ACTION_ID
        if identifier.casefold() == ACTION_ID.casefold():
            action = self._recipe_action()
            if action is None:
                raise ValueError('Нет рецептов, доступных для изучения.')
            return action
        cached=self.functions.get(identifier.casefold())
        if cached is not None:return cached
        file,separator,name=identifier.partition('#')
        if file.startswith('project:'):
            root=self.project
            path=root/file[len('project:'):]
        elif file.startswith('game:Content/') and self.game_content is not None:
            root=self.game_content
            path=root/file[len('game:Content/'):]
        else:raise ValueError('Выберите функцию заново: '+identifier)
        if root not in path.resolve().parents or path.suffix.lower()!='.d':raise ValueError('Недопустимый путь действия: '+identifier)
        values=self._read(path,file)
        if not separator:
            if len(values)==1:return values[0]
            raise ValueError(f'{path}: вместо файла выберите конкретную функцию.')
        matches=[value for value in values if value.name.casefold()==name.casefold()]
        if len(matches)!=1:raise ValueError(f'{path}: функция {name} не найдена или неоднозначна.')
        return matches[0]
