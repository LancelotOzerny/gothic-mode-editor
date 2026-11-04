"""Schema-driven settings values; project values stay in project.json."""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path

from .localization import localization, tr
from .settings_schema import FieldType, all_fields


def field_key(field) -> str:
    return f'{field.section_code}.{field.group_code}.{field.key}'


def validate_value(field, value):
    kind = field.field_type
    valid = True
    if kind is FieldType.BOOLEAN:
        valid = type(value) is bool
    elif kind in (FieldType.NUMBER, FieldType.SIZE):
        numbers = value if kind is FieldType.SIZE and isinstance(value, list) else [value]
        valid = (kind is not FieldType.SIZE or len(numbers) == 2) and all(
            type(number) is int
            and (field.minimum is None or number >= field.minimum)
            and (field.maximum is None or number <= field.maximum)
            for number in numbers)
    else:
        valid = isinstance(value, str)
        if valid and kind is FieldType.COLOR:
            valid = re.fullmatch(r'#[0-9a-fA-F]{6}|#[0-9a-fA-F]{3}', value) is not None
        if valid and kind is FieldType.LANGUAGE:
            valid = value in localization.available_languages()
    if not valid:
        raise ValueError(tr('settings.invalid', name=tr(field.label_key)))
    return value


class EditorSettings:
    def __init__(self, values=None):
        if values is not None and not isinstance(values, dict):
            raise ValueError('Settings values must be an object.')
        self.values = deepcopy(values or {})

    def get(self, field):
        return deepcopy(self.values.get(field_key(field), field.default))

    def get_value(self, key):
        field = next(field for field in all_fields() if field_key(field) == key)
        return self.get(field)


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else (
            Path(os.environ.get('APPDATA') or Path.home() / '.config')
            / 'GothicEditor' / 'settings.json')

    def load(self):
        try:
            settings = EditorSettings(json.loads(self.path.read_text(encoding='utf-8')))
        except (OSError, ValueError, TypeError):
            return EditorSettings()
        for field in all_fields():
            try:
                validate_value(field, settings.get(field))
            except ValueError:
                settings.values.pop(field_key(field), None)
        return settings

    def save(self, settings):
        values = {field_key(field): validate_value(field, settings.get(field))
                  for field in all_fields() if field.scope == 'application'}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.path)
