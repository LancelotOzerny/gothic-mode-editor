"""Build options from the existing project.json settings, with legacy defaults."""
from dataclasses import dataclass
import json
from pathlib import Path
import re

from .settings import validate_value, field_key
from .settings_schema import all_fields


@dataclass(frozen=True)
class ModConfiguration:
    title: str
    filename: str
    starter_path: str = ''
    packer_path: str = ''
    keep_dat: bool = False

    @property
    def ini_name(self):
        return str(Path(self.filename).with_suffix('.ini'))

    @classmethod
    def load(cls, project):
        config = project / 'project.json'
        data = json.loads(config.read_text('utf-8')) if config.is_file() else {}
        if not isinstance(data,dict):raise ValueError('Некорректный project.json')
        values = data.get('settings', {})
        if not isinstance(values,dict):raise ValueError('Настройки проекта должны быть JSON-объектом')
        for field in all_fields():
            if field.scope == 'project':validate_value(field, values.get(field_key(field), field.default))
        title = values.get('project.mod.name', '').strip() or data.get('name', project.name)
        stem = re.sub(r'[^A-Za-z0-9_-]+', '-', title).strip('-') or 'GothicMod'
        filename = values.get('project.mod.output_name', '').strip() or stem + '.mod'
        if (not re.fullmatch(r'[A-Za-z0-9_-]+\.mod', filename, re.I)
                or filename.casefold() in ('gothicgame.mod', 'gothic.mod')):
            raise ValueError('Имя MOD должно содержать только латинские буквы, цифры, дефис и подчёркивание; GothicGame.mod и Gothic.mod зарезервированы.')
        if not title or any(char in title for char in '\r\n\0'):
            raise ValueError('Некорректное имя модификации')
        title.encode('cp1251')
        return cls(title, filename, values.get('project.mod.starter_path', ''),
                   values.get('project.mod.packer_path', ''), values.get('project.mod.keep_dat', False))
