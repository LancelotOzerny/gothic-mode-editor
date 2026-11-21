"""Read-only static VOB placement and mesh preparation for world preview.

BIN_SAFE and ASCII VOB properties are decoded by the existing ZEN inspector.
Unannotated BINARY VOBs require a separate positional decoder and are not
guessed. Unsupported visuals (animated, particles, decals) are skipped.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite
from pathlib import Path
import re
import struct

from .mesh import read_3ds_bytes, read_mrm
from .zen_world import inspect_zen

_IDENTITY = (1., 0., 0., 0., 1., 0., 0., 0., 1.)
_NUMBER = re.compile(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?')
_MAX_VOBS = 50000
_MAX_MODELS = 256
_MAX_MODEL_TRIANGLES = 250000


@dataclass(frozen=True)
class StaticVob:
    visual: str
    position: tuple[float, float, float]
    rotation: tuple[float, ...]
    name: str
    chunk: tuple[int, int]


@dataclass(frozen=True)
class StaticMesh:
    vertices: tuple[tuple[float, float, float], ...]
    faces: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class VobScene:
    objects: tuple[StaticVob, ...]
    models: dict[str, StaticMesh]
    chunks: dict[tuple[int, int], tuple[int, ...]]
    status: str
    skipped: int = 0


def _numbers(value: str, count: int):
    values = tuple(float(x) for x in _NUMBER.findall(value))
    if len(values) != count or not all(isfinite(x) and abs(x) < 1e8 for x in values):
        raise ValueError('Некорректные координаты VOB.')
    return values


def _rotation(value: str):
    if not value:
        return _IDENTITY
    stripped = value.strip()
    if len(stripped) == 72 and all(c in '0123456789abcdefABCDEF' for c in stripped):
        raw = struct.unpack('<9f', bytes.fromhex(stripped))
        if all(isfinite(x) and abs(x) <= 2 for x in raw):
            return raw
        raise ValueError('Некорректный поворот VOB.')
    return _numbers(stripped, 9)


def static_vobs(info, chunk_size: int):
    """Extract static model references and world-space transforms."""
    if not info.details_available:
        return (), 'BINARY: декодирование VOB ещё не поддерживается', 0
    objects = []
    skipped = 0
    for entry in info.objects:
        props = entry.properties
        visual = props.get('visual', '').replace('\\', '/').rsplit('/', 1)[-1]
        if Path(visual).suffix.lower() not in ('.3ds', '.mrm'):
            continue
        if props.get('showVisual', '1').strip().lower() in ('0', 'false'):
            continue
        if len(objects) >= _MAX_VOBS:
            skipped += 1
            continue
        try:
            position = _numbers(props.get('trafoOSToWSPos', ''), 3)
            rotation = _rotation(props.get('trafoOSToWSRot', ''))
        except ValueError:
            skipped += 1
            continue
        name = props.get('vobName', entry.name)
        key = (floor(position[0] / chunk_size), floor(position[2] / chunk_size))
        objects.append(StaticVob(visual.lower(), position, rotation, name, key))
    return tuple(objects), 'OK', skipped


def _load_mesh(source):
    if source.size > 64*1024*1024 if hasattr(source, 'size') else source.stat().st_size > 64*1024*1024:
        raise ValueError('Слишком большая модель.')
    name = source.name.lower()
    data = source.read_bytes()
    if name.endswith('.mrm'):
        vertices, faces = read_mrm(data)
    elif name.endswith('.3ds'):
        vertices, faces = read_3ds_bytes(data)
        # ZenGin's uncompiled 3DS files are Z-up, while compiled meshes are Y-up.
        vertices = [(x, z, y) for x, y, z in vertices]
    else:
        raise ValueError('Неподдерживаемая модель.')
    if len(faces) > _MAX_MODEL_TRIANGLES:
        raise ValueError('Слишком много полигонов в одной модели.')
    if not all(all(isfinite(x) and abs(x) < 1e8 for x in v) for v in vertices):
        raise ValueError('Некорректные координаты модели.')
    return StaticMesh(tuple(vertices), tuple(faces))


def load_vob_scene(path, sources, chunk_size):
    """Read VOB placements and unique model meshes on a worker thread.

    sources maps lowercase model basenames to Path or VdfEntry.
    """
    info = inspect_zen(path, include_objects=True)
    objects, status, skipped = static_vobs(info, chunk_size)
    if not objects:
        return VobScene((), {}, {}, status, skipped)
    models = {}
    missing = set()
    for name in dict.fromkeys(v.visual for v in objects):
        if len(models) >= _MAX_MODELS:
            break
        source = sources.get(name)
        if source is None and name.endswith('.3ds'):
            source = sources.get(name[:-4] + '.mrm')
        if source is None:
            missing.add(name)
            continue
        try:
            models[name] = _load_mesh(source)
        except (OSError, ValueError, struct.error):
            missing.add(name)
    kept = tuple(v for v in objects if v.visual in models)
    groups = {}
    for i, v in enumerate(kept):
        groups.setdefault(v.chunk, []).append(i)
    return VobScene(kept, models,
                    {k: tuple(v) for k, v in groups.items()},
                    status, skipped + len(objects) - len(kept))
