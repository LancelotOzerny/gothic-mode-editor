"""Property descriptions independent of widgets and item persistence."""
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys


def property_key(key):
    return re.sub(r'\s+', '', key).casefold()


@dataclass(frozen=True)
class PropertyField:
    key: str
    label: str
    source: str = 'property'
    description: str = ''
    placeholder: str = ''
    required: bool = False
    export: bool = True
    field_type: str = 'string'
    widget: str = 'input'
    options: tuple[tuple[str, str], ...] = ()
    default: str | None = None
    prefix: str = ''
    max_rows: int = 0
    start_index: int = 0
    columns: tuple['PropertyField', ...] = ()
    reserved: tuple[tuple[str, str], ...] = ()
    options_source: str = ''


@dataclass(frozen=True)
class PropertySection:
    key: str
    title: str
    fields: tuple[PropertyField, ...]
    description: str = ''


@dataclass(frozen=True)
class PropertiesSchema:
    sections: tuple[PropertySection, ...]
    unknown_section: str | None = None
    show_missing: bool = True
    generated_defaults: dict[str, str] = field(default_factory=dict)
    instance_prefix: str = ''
    instance_pattern: str = 'Potion{n}'
    numbering_start: int = 1

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text('utf-8-sig'))
        if data.get('schema_version') not in (1, 2, 3) or not isinstance(data.get('sections'), list):
            raise ValueError(f'{path}: unsupported properties schema')
        option_lists = data.get('option_lists', {})
        if not isinstance(option_lists, dict):
            raise ValueError(f'{path}: option_lists must be an object')
        for name, options in option_lists.items():
            if (not isinstance(options, list) or any(not isinstance(option, dict)
                    or not isinstance(option.get('name'), str) or not isinstance(option.get('value'), str)
                    for option in options)):
                raise ValueError(f'{path}: invalid option list {name}')
            if len({option['name'] for option in options}) != len(options):
                raise ValueError(f'{path}: ambiguous option names in {name}')
        sections, section_keys, keys = [], set(), set()
        for section in data['sections']:
            section_key = section['id']
            if section_key in section_keys:
                raise ValueError(f'{path}: duplicate section {section_key}')
            section_keys.add(section_key)
            fields = []
            for raw in section['fields']:
                key = raw['key']
                canonical = property_key(key)
                source = raw.get('source', 'property')
                if (canonical in keys or raw.get('type') not in ('string', 'expression', 'identifier', 'enum', 'flags', 'resource', 'key_value_list')
                        or raw.get('widget', 'input') not in ('input', 'combobox')
                        or source not in ('property', 'instance_id', 'editor_metadata')):
                    raise ValueError(f'{path}: invalid or duplicate field {key}')
                reference = raw.get('options_ref')
                if reference is not None and reference not in option_lists:
                    raise ValueError(f'{path}: unknown option list {reference}')
                default = raw.get('default')
                if default is not None and not isinstance(default, str):
                    raise ValueError(f'{path}: default must be a Daedalus expression: {key}')
                keys.add(canonical)
                columns = raw.get('columns', [])
                maximum, start = raw.get('max_rows', 0), raw.get('start_index', 0)
                reserved = raw.get('reserved', {})
                if raw['type'] == 'key_value_list':
                    if (type(maximum) is not int or maximum < 1 or type(start) is not int or start < 0
                            or not isinstance(columns, list) or len(columns) != 2
                            or any(not isinstance(column, dict) or column.get('type') not in ('string', 'expression')
                            or not isinstance(column.get('label'), str)
                            or not re.fullmatch(r'[A-Za-z_]\w*', column.get('variable', ''), re.ASCII)
                            for column in columns)
                            or len({column['variable'].casefold() for column in columns}) != 2
                            or not isinstance(reserved, dict)
                            or any(key not in [column['variable'] for column in columns] or not isinstance(value, str)
                                   for key, value in reserved.items())):
                        raise ValueError(f'{path}: invalid key_value_list {key}')
                fields.append(PropertyField(key, raw['label'], source, raw.get('description', ''),
                                            raw.get('placeholder', ''), raw.get('required', False),
                                            raw.get('export', True),raw['type'],raw.get('widget','input'),
                                            tuple((option['name'],option['value']) for option in option_lists.get(reference,[])),
                                            default, raw.get('prefix', ''), maximum, start,
                                            tuple(PropertyField(c['variable'], c['label'], field_type=c['type']) for c in columns),
                                            tuple(reserved.items()), raw.get('options_source', '')))
            sections.append(PropertySection(section_key, section['title'], tuple(fields),
                                            section.get('description', '')))
        unknown = data.get('unknown_properties', {}).get('show_in_section')
        if unknown and unknown not in section_keys:
            raise ValueError(f'{path}: unknown section {unknown}')
        defaults = data.get('generated_defaults', {})
        if not isinstance(defaults, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                                for key, value in defaults.items()):
            raise ValueError(f'{path}: generated_defaults must contain Daedalus expressions')
        instance = data.get('instance', {})
        prefix = instance.get('prefix', '')
        pattern = instance.get('suffix_default_pattern', 'Potion{n}')
        start = instance.get('numbering_start', 1)
        if (not isinstance(prefix, str) or not isinstance(pattern, str) or pattern.count('{n}') != 1
                or type(start) is not int or start < 1
                or not re.fullmatch(r'[A-Za-z_]\w*', prefix + pattern.replace('{n}', str(start)), re.ASCII)):
            raise ValueError(f'{path}: invalid instance numbering')
        return cls(tuple(sections), unknown, data.get('missing_properties', {}).get('show_empty', True),
                   defaults, prefix, pattern, start)


def schema_for(category):
    # Additional item types can be registered here when their forms are ready.
    files = {'potions': 'potion.json'}
    filename = files.get(category)
    if filename is None:
        return None
    roots = (Path(sys.executable).resolve().parent,Path(__file__).resolve().parents[2])
    paths = [root / relative for root in roots for relative in
             (Path('assets/schemas')/(category+'.json'),Path('assets/properties')/filename)]
    path = next((path for path in paths if path.is_file()),paths[-1])
    return PropertiesSchema.load(path)
