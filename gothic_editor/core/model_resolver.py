"""Resolve custom model names without overwriting the item's fallback visual."""
from pathlib import Path


class ModelResolver:
    @staticmethod
    def custom_model(folder):
        return Path(folder) / 'assets' / 'model.3ds'

    @staticmethod
    def generated_name(instance):
        return f'model_{instance}.3ds'

    @classmethod
    def visual(cls, data, folder):
        if cls.custom_model(folder).is_file():
            return '"' + cls.generated_name(data['instance']) + '"'
        return data.get('fields', {}).get('visual')

    @classmethod
    def index(cls, store):
        result = {}
        for file in store.files():
            model = cls.custom_model(file.parent)
            if model.is_file():
                data = store._read(file)
                result[cls.generated_name(data['instance']).casefold()] = model
        return result
