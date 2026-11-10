"""Compose a category's ordered property blocks into one flat form description."""
import json
from pathlib import Path


def load_property_data(path, dependencies=None):
    path = Path(path)
    if dependencies is not None:dependencies.append(path)
    data = json.loads(path.read_text('utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError(f'{path}: properties must be an object')
    if 'blocks' not in data:
        return data  # Existing standalone schemas remain readable.
    if set(data) != {'blocks'} or not isinstance(data['blocks'], list) or not data['blocks']:
        raise ValueError(f'{path}: category must contain only a nonempty blocks list')
    root = (path.parent.parent / 'blocks').resolve()
    result = {'schema_version': 3, 'sections': [], 'option_lists': {}, 'generated_defaults': {}}
    overrides, visited = {}, set()
    for reference in data['blocks']:
        if not isinstance(reference, str) or not reference:
            raise ValueError(f'{path}: invalid block reference')
        block_path = (root / reference).resolve()
        if root not in block_path.parents or block_path.suffix.lower() != '.json':
            raise ValueError(f'{path}: block path outside blocks directory: {reference}')
        if block_path in visited:
            raise ValueError(f'{path}: duplicate block {reference}')
        visited.add(block_path)
        if dependencies is not None:dependencies.append(block_path)
        block = json.loads(block_path.read_text('utf-8-sig'))
        if not isinstance(block, dict) or 'blocks' in block or 'schema_version' in block:
            raise ValueError(f'{block_path}: invalid property block')
        sections = block.pop('sections', [])
        if not isinstance(sections, list):
            raise ValueError(f'{block_path}: sections must be a list')
        result['sections'].extend(sections)
        for key in ('option_lists', 'generated_defaults', 'field_overrides'):
            entries = block.pop(key, {})
            if not isinstance(entries, dict):
                raise ValueError(f'{block_path}: {key} must be an object')
            target = overrides if key == 'field_overrides' else result[key]
            for name, value in entries.items():
                if name in target:
                    raise ValueError(f'{block_path}: duplicate {key} entry {name}')
                target[name] = value
        for key, value in block.items():
            if key in result:
                raise ValueError(f'{block_path}: duplicate schema setting {key}')
            result[key] = value
    fields = {raw['key']: raw for section in result['sections'] for raw in section['fields']}
    for name, changes in overrides.items():
        if name not in fields or not isinstance(changes, dict) or 'key' in changes:
            raise ValueError(f'{path}: invalid field override {name}')
        fields[name].update(changes)
    return result
