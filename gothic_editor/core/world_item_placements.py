"""Project-local item placements; no Gothic ZEN files are modified."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class ItemPlacement:
    id: str
    world: str
    item: str
    position: tuple[float, float, float]
    rotation: tuple[float, float, float]


def _identifier(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError(f'{label}: требуется непустое имя длиной до 128 символов.')
    value = value.strip()
    if any(ord(char) < 32 for char in value):
        raise ValueError(f'{label}: недопустимый управляющий символ.')
    return value


def _vector(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f'{label}: необходимы три координаты.')
    if any(isinstance(number, bool) or not isinstance(number, (int, float))
           or not math.isfinite(number) for number in value):
        raise ValueError(f'{label}: координаты должны быть конечными числами.')
    return tuple(float(number) for number in value)


class WorldItemPlacements:
    """Store placement intent separately from game assets and compiled archives."""

    def __init__(self, project):
        self.root = Path(project).resolve()
        self.path = self.root / 'WorldPlacements' / 'items.json'

    @staticmethod
    def _read_record(data):
        if not isinstance(data, dict):
            raise ValueError('Некорректная запись размещения.')
        return ItemPlacement(
            _identifier(data.get('id'), 'ID размещения'),
            _identifier(data.get('world'), 'Мир'),
            _identifier(data.get('item'), 'INSTANCE предмета'),
            _vector(data.get('position'), 'Позиция'),
            _vector(data.get('rotation'), 'Поворот'),
        )

    def list(self, world=None):
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('placements'), list):
            raise ValueError('Некорректный файл размещений предметов.')
        result = [self._read_record(row) for row in data['placements']]
        ids = [row.id.casefold() for row in result]
        if len(set(ids)) != len(ids):
            raise ValueError('Повторяющиеся ID размещений предметов.')
        return [row for row in result if row.world.casefold() == world.casefold()] if world is not None else result

    def _save(self, placements):
        data = {'version': 1, 'placements': [
            {'id': row.id, 'world': row.world, 'item': row.item,
             'position': list(row.position), 'rotation': list(row.rotation)}
            for row in placements
        ]}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name('.items-' + uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def add(self, world, item, position, rotation=(0, 0, 0)):
        record = ItemPlacement(uuid4().hex, _identifier(world, 'Мир'),
                               _identifier(item, 'INSTANCE предмета'),
                               _vector(position, 'Позиция'), _vector(rotation, 'Поворот'))
        rows = self.list()
        rows.append(record)
        self._save(rows)
        return record

    def update(self, placement_id, *, world=None, item=None, position=None, rotation=None):
        rows = self.list()
        updated = None
        for index, row in enumerate(rows):
            if row.id != placement_id:
                continue
            updated = ItemPlacement(row.id, _identifier(world, 'Мир') if world is not None else row.world,
                _identifier(item, 'INSTANCE предмета') if item is not None else row.item,
                _vector(position, 'Позиция') if position is not None else row.position,
                _vector(rotation, 'Поворот') if rotation is not None else row.rotation)
            rows[index] = updated
            break
        if updated is None:
            raise ValueError('Размещение предмета не найдено.')
        self._save(rows)
        return updated

    def remove(self, placement_id):
        rows = self.list()
        remaining = [row for row in rows if row.id != placement_id]
        if len(remaining) == len(rows):
            raise ValueError('Размещение предмета не найдено.')
        self._save(remaining)
