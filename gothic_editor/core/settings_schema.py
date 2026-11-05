"""Editable settings catalog loaded from JSON configuration files."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class FieldType(str, Enum):
    BOOLEAN = "boolean"
    STRING = "string"
    NUMBER = "number"
    SIZE = "size"
    COLOR = "color"
    DIRECTORY = "directory"
    FILE = "file"
    LANGUAGE = "language"


@dataclass(frozen=True)
class SettingField:
    key: str
    label_key: str
    title_key: str
    section_code: str
    group_code: str
    field_type: FieldType
    default: Any
    storage_keys: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None
    scope: str = "application"

    @property
    def keys(self) -> tuple[str, ...]:
        return self.storage_keys or (self.key,)

    def default_for(self, index: int) -> Any:
        return self.default[index] if self.field_type is FieldType.SIZE else self.default


@dataclass(frozen=True)
class SettingGroup:
    section_code: str
    code: str
    title_key: str
    fields: tuple[SettingField, ...]


@dataclass(frozen=True)
class SettingCategory:
    key: str
    title_key: str
    groups: tuple[SettingGroup, ...]


class SettingsCatalog:
    """Accepts JSON files while preserving connection and section order."""

    def __init__(self) -> None:
        self._sections: list[tuple[str, str]] = []
        self._groups: list[SettingGroup] = []

    def connect(self, path: str | Path) -> None:
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise ValueError(f'Cannot load settings configuration {path}: {exc}') from exc
        if not isinstance(data, dict) or not isinstance(data.get('sections'), list) or not isinstance(data.get('settings'), list):
            raise ValueError('Settings configuration requires sections and settings arrays.')
        sections: list[tuple[str, str]] = []
        for raw_section in data['sections']:
            if not isinstance(raw_section, dict) or not isinstance(raw_section.get('code'), str) or not isinstance(raw_section.get('name'), str):
                raise ValueError('Each settings section requires string code and name.')
            sections.append((raw_section['code'], raw_section['name']))
        known_codes = {code for code, _ in self._sections}
        new_codes = [code for code, _ in sections]
        if len(new_codes) != len(set(new_codes)) or known_codes.intersection(new_codes):
            raise ValueError('Settings section codes must be unique.')
        groups = tuple(self._parse_group(raw_group, known_codes | set(new_codes)) for raw_group in data['settings'])
        self._sections.extend(sections)
        self._groups.extend(groups)

    @staticmethod
    def _parse_group(data: Any, section_codes: set[str]) -> SettingGroup:
        if not isinstance(data, dict) or data.get('section_code') not in section_codes or not isinstance(data.get('name'), str) or not isinstance(data.get('items'), list):
            raise ValueError('Each settings group requires a known section_code, name and items.')
        group_code = data.get('code') or data['name'].rsplit('.', 1)[-1]
        if not isinstance(group_code, str) or not group_code:
            raise ValueError('Each settings group requires a non-empty code.')
        return SettingGroup(data['section_code'], group_code, data['name'],
                            tuple(SettingsCatalog._parse_field(item, data['section_code'], group_code) for item in data['items']))

    @staticmethod
    def _parse_field(data: Any, section_code: str, group_code: str) -> SettingField:
        if not isinstance(data, dict) or not isinstance(data.get('name'), str) or not isinstance(data.get('title'), str) or not isinstance(data.get('type'), str) or 'default' not in data:
            raise ValueError('Each settings item requires name, title, type and default.')
        try:
            field_type = FieldType(data['type'])
        except ValueError as exc:
            raise ValueError(f"Unknown settings field type: {data['type']}") from exc
        storage_keys = tuple(data.get('storage_keys', ()))
        if storage_keys and not all(isinstance(key, str) and key for key in storage_keys):
            raise ValueError('storage_keys must contain non-empty strings.')
        if field_type is FieldType.SIZE and (len(storage_keys) not in (0, 2) or not isinstance(data['default'], list) or len(data['default']) != 2):
            raise ValueError('A size field requires a two-value default and optional two storage_keys.')
        minimum, maximum = data.get('minimum'), data.get('maximum')
        if (minimum is not None and not isinstance(minimum, int)) or (maximum is not None and not isinstance(maximum, int)):
            raise ValueError('Field bounds must be integers.')
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError('Field minimum cannot exceed maximum.')
        field_code = data.get('code') or data['name'].rsplit('.', 1)[-1]
        if not isinstance(field_code, str) or not field_code:
            raise ValueError('Each settings item requires a non-empty code.')
        scope = data.get('scope', 'application')
        if scope not in ('application', 'project'):
            raise ValueError('Unknown settings scope.')
        return SettingField(field_code, data['name'], data['title'], section_code, group_code,
                            field_type, data['default'], storage_keys, minimum, maximum, scope)

    def categories(self) -> tuple[SettingCategory, ...]:
        return tuple(SettingCategory(code, name, tuple(group for group in self._groups if group.section_code == code))
                     for code, name in self._sections)

    def fields(self) -> tuple[SettingField, ...]:
        return tuple(field for category in self.categories() for group in category.groups for field in group.fields)


def _default_settings_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    external = Path(sys.executable).resolve().parent / 'assets' / 'settings.json'
    return external if external.is_file() else root / 'assets' / 'settings.json'


catalog = SettingsCatalog()


def connect(path: str | Path) -> None:
    """Connect another settings description, for example supplied by a module."""
    catalog.connect(path)


def categories() -> tuple[SettingCategory, ...]:
    return catalog.categories()


def all_fields() -> tuple[SettingField, ...]:
    return catalog.fields()


connect(_default_settings_path())
