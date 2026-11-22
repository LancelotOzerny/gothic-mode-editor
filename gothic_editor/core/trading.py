"""Project-local merchant configurations. Original Gothic files are never written."""
import json
import re
from pathlib import Path
from uuid import uuid4

from .asset_files import AssetFiles

IDENT = re.compile(r'[A-Za-z_][A-Za-z_0-9]*\Z', re.ASCII)

class TradingStore:
    def __init__(self, project):
        self.project = Path(project).resolve()
        self.path = self.project / 'Assets' / 'NPC' / 'trading.json'
        self.files = AssetFiles(self.project)

    @staticmethod
    def validate(config):
        if not isinstance(config, dict) or set(config) - {'enabled','dialog','min_chapter','refresh_hours','stock'}:
            raise ValueError('Некорректные свойства торговца.')
        if type(config.get('enabled', True)) is not bool or type(config.get('dialog', True)) is not bool:
            raise ValueError('Флаги торговца должны быть логическими.')
        chapter = config.get('min_chapter', 1)
        hours = config.get('refresh_hours', 0)
        if type(chapter) is not int or not 1 <= chapter <= 6:
            raise ValueError('Глава торговли должна быть от 1 до 6.')
        if type(hours) is not int or not 0 <= hours <= 100000:
            raise ValueError('Период обновления должен быть от 0 до 100000 игровых часов.')
        stock = config.get('stock', [])
        if not isinstance(stock, list) or len(stock) > 512:
            raise ValueError('Ассортимент торговца: максимум 512 позиций.')
        keys = set()
        for row in stock:
            if not isinstance(row, dict) or set(row) != {'item','quantity','chapter'}:
                raise ValueError('Строка ассортимента должна содержать item, quantity, chapter.')
            item, quantity, chapter = row['item'], row['quantity'], row['chapter']
            if not isinstance(item, str) or not IDENT.fullmatch(item):
                raise ValueError('Недопустимый идентификатор предмета: ' + str(item))
            if type(quantity) is not int or not 1 <= quantity <= 100000:
                raise ValueError('Количество предметов должно быть от 1 до 100000.')
            if type(chapter) is not int or not 1 <= chapter <= 6:
                raise ValueError('Глава предмета должна быть от 1 до 6.')
            key = (item.casefold(), chapter)
            if key in keys:
                raise ValueError('Предмет уже добавлен в эту главу: ' + item)
            keys.add(key)
        return config

    def read(self):
        self.files.checked(self.path)
        if not self.path.is_file():
            return {}
        data = json.loads(self.path.read_text('utf-8'))
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('traders'), dict):
            raise ValueError(f'{self.path}: неверный формат торговцев.')
        result = {}
        for npc, config in data['traders'].items():
            if not IDENT.fullmatch(npc):
                raise ValueError(f'{self.path}: неверный NPC: {npc}')
            self.validate(config)
            key = npc.casefold()
            if key in result:
                raise ValueError(f'{self.path}: повторный NPC: {npc}')
            result[key] = config
        return result

    def save(self, npc, config):
        if not isinstance(npc, str) or not IDENT.fullmatch(npc):
            raise ValueError('Некорректный идентификатор NPC.')
        if config is not None:
            self.validate(config)
        rows = self.read()
        if config is None or not config.get('enabled', True):
            rows.pop(npc.casefold(), None)
        else:
            rows[npc.casefold()] = config
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name('.trading-' + uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps({'version': 1, 'traders': rows}, ensure_ascii=False, indent=2) + '\n', 'utf-8')
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
