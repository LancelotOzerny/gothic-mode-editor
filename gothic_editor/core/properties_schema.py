"""Property descriptions independent of widgets and item persistence."""
from dataclasses import dataclass
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

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text('utf-8-sig'))
        if data.get('schema_version') != 1 or not isinstance(data.get('sections'), list):
            raise ValueError(f'{path}: unsupported properties schema')
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
                if (canonical in keys or raw.get('type') != 'string'
                        or raw.get('widget', 'input') != 'input'
                        or source not in ('property', 'instance_id', 'editor_metadata')):
                    raise ValueError(f'{path}: invalid or duplicate field {key}')
                keys.add(canonical)
                fields.append(PropertyField(key, raw['label'], source, raw.get('description', ''),
                                            raw.get('placeholder', ''), raw.get('required', False),
                                            raw.get('export', True)))
            sections.append(PropertySection(section_key, section['title'], tuple(fields),
                                            section.get('description', '')))
        unknown = data.get('unknown_properties', {}).get('show_in_section')
        if unknown and unknown not in section_keys:
            raise ValueError(f'{path}: unknown section {unknown}')
        return cls(tuple(sections), unknown, data.get('missing_properties', {}).get('show_empty', True))


def schema_for(category):
    # Additional item types can be registered here when their forms are ready.
    files = {'potions': 'potion.json'}
    filename = files.get(category)
    if filename is None:
        return None
    external = Path(sys.executable).resolve().parent / 'assets/properties' / filename
    path = external if external.is_file() else Path(__file__).resolve().parents[2] / 'assets/properties' / filename
    return PropertiesSchema.load(path)
