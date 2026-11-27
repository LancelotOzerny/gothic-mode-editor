"""Versioned, bounded, non-executable disk cache for world preview resources."""
from __future__ import annotations

from array import array
from collections import OrderedDict
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter
import json
import zlib
import os
import struct
import sys

from .world_preview import face_color

CACHE_VERSION = 1
HEADER = struct.Struct('<III')
MAX_ENTRY = 128 * 1024 * 1024


def source_stamp(source):
    path = Path(source.archive if hasattr(source, 'archive') else source)
    stat = path.stat()
    return (str(path.resolve()), stat.st_size, stat.st_mtime_ns,
            getattr(source, 'offset', 0), getattr(source, 'size', stat.st_size))


class WorldDiskCache:
    def __init__(self, root=None, budget=2048 * 1024 * 1024):
        self.root = Path(root) if root is not None else (
            Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.cache')
            / 'GothicEditor' / 'world-preview-v1')
        self.budget = budget

    def key(self, kind, stamp):
        return sha256(repr((CACHE_VERSION, kind, stamp)).encode('utf-8')).hexdigest()

    def read(self, key):
        path = self.root / key
        try:
            if path.stat().st_size > MAX_ENTRY:
                return None
            data = path.read_bytes()
            try:
                os.utime(path, None)
            except OSError:
                pass
            return data
        except OSError:
            return None

    def write(self, key, data):
        if len(data) > min(MAX_ENTRY, self.budget):
            return
        temp = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=self.root, prefix='.cache-', delete=False) as stream:
                temp = Path(stream.name)
                stream.write(data)
            temp.replace(self.root / key)
            self.prune()
        except OSError:
            pass
        finally:
            if temp is not None:
                try:
                    temp.unlink(missing_ok=True)
                except OSError:
                    pass

    def prune(self):
        entries = []
        for path in self.root.iterdir():
            if len(path.name) != 64 or any(c not in '0123456789abcdef' for c in path.name):
                continue
            try:
                stat = path.stat()
                entries.append((stat.st_mtime_ns, stat.st_size, path))
            except OSError:
                pass
        total = sum(size for _, size, _ in entries)
        for _, size, path in sorted(entries):
            if total <= self.budget:
                break
            try:
                path.unlink()
                total -= size
            except OSError:
                pass


def _pack_arrays(vertices, indices):
    if sys.byteorder != 'little':
        vertices.byteswap()
        indices.byteswap()
    return vertices.tobytes(), indices.tobytes()


def build_batches(vertices, faces, uvs, names):
    """Interleaved XYZ/RGB/UV float32 and uint32 indices, grouped by material.
    Split large materials so GPU transfer can be spread across frames.
    """
    grouped = OrderedDict()
    for i, face in enumerate(faces):
        uv = uvs[i] if i < len(uvs) else None
        name = names[i] if i < len(names) and uv else ''
        grouped.setdefault(name.casefold(), []).append((face, uv))
    result = []
    for name, entries in grouped.items():
        for start in range(0, len(entries), 4096):
            data, indices, lookup = array('f'), array('I'), {}
            for face, uv in entries[start:start + 4096]:
                color = face_color(vertices, face)
                rgb = tuple(int(color[j:j+2], 16) / 255.0 for j in (1, 3, 5))
                for corner, index in enumerate(face):
                    point = (*vertices[index], *rgb, *(uv[corner] if uv is not None else (0., 0.)))
                    idx = lookup.get(point)
                    if idx is None:
                        idx = len(data) // 8
                        lookup[point] = idx
                        data.extend(point)
                    indices.append(idx)
            result.append((name, *_pack_arrays(data, indices)))
    return tuple(result)


def encode_batches(batches):
    parts = []
    for name, vertices, indices in batches:
        name = name.encode('utf-8')
        parts.extend((HEADER.pack(len(name), len(vertices), len(indices)), name, vertices, indices))
    return b''.join(parts)


def decode_batches(data):
    result, offset = [], 0
    while offset < len(data):
        name_size, vertex_size, index_size = HEADER.unpack_from(data, offset)
        offset += HEADER.size
        end = offset + name_size + vertex_size + index_size
        if (end > len(data) or name_size > 4096 or not vertex_size or
                not index_size or vertex_size % 32 or index_size % 12):
            raise ValueError('Invalid world buffer cache')
        name = data[offset:offset + name_size].decode('utf-8')
        offset += name_size
        vertices = data[offset:offset + vertex_size]
        offset += vertex_size
        indices = data[offset:end]
        if any(index >= vertex_size // 32 for (index,) in struct.iter_unpack('<I', indices)):
            raise ValueError('Invalid cached index')
        result.append((name, vertices, indices))
        offset = end
    return tuple(result)


def prepare_batches(cache, stamp, vertices, faces, uvs, names):
    started = perf_counter()
    key = cache.key('geometry', stamp) if cache is not None and stamp is not None else None
    if key:
        raw = cache.read(key)
        if raw is not None:
            try:
                batches = decode_batches(raw)
                if sum(len(indices) // 12 for _, _, indices in batches) == len(faces):
                    return batches, perf_counter() - started, True
            except (ValueError, struct.error):
                pass
    batches = build_batches(vertices, faces, uvs, names)
    if key:
        cache.write(key, encode_batches(batches))
    return batches, perf_counter() - started, False


def world_stamp(source, chunk_size, sources):
    """Cache identity covers the original ZEN and model overrides."""
    try:
        archive_stamps = {}
        models = []
        for name, value in sources.items():
            if hasattr(value, 'archive'):
                path = value.archive
                if path not in archive_stamps:
                    archive_stamps[path] = source_stamp(path)
                stamp = (archive_stamps[path], value.offset, value.size)
            else:
                stamp = source_stamp(value)
            models.append((name, stamp))
        return sha256(repr((source_stamp(source), chunk_size, sorted(models))).encode('utf-8')).hexdigest()
    except (OSError, TypeError, ValueError):
        return None

def load_cached_world(cache, source, chunk_size, sources):
    """Persist parsed terrain and VOB data as bounded compressed JSON, never pickle."""
    from .world_preview import ChunkedWorld, load_world_with_vobs
    from .world_vobs import StaticMesh, StaticVob, VobScene
    stamp = world_stamp(source, chunk_size, sources)
    key = cache.key('scene', stamp) if stamp is not None else None
    if key:
        raw = cache.read(key)
        if raw is not None:
            try:
                decoder = zlib.decompressobj()
                decoded = decoder.decompress(raw, 256 * 1024 * 1024)
                if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                    raise ValueError('Invalid scene cache')
                w, v = json.loads(decoded)
                def vectors(values):
                    return tuple(tuple(value) for value in values)
                def uv_rows(values):
                    return tuple(vectors(value) if value is not None else None for value in values)
                world = ChunkedWorld(vectors(w[0]), {tuple(k): vectors(f) for k, f in w[1]},
                    w[2], w[3], w[4], w[5], tuple(w[6]),
                    {tuple(k): uv_rows(rows) for k, rows in w[7]},
                    {tuple(k): tuple(rows) for k, rows in w[8]})
                vobs = VobScene(tuple(StaticVob(name, tuple(pos), tuple(rot), title, tuple(chunk))
                    for name, pos, rot, title, chunk in v[0]),
                    {name: StaticMesh(vectors(mesh[0]), vectors(mesh[1]), uv_rows(mesh[2]), tuple(mesh[3]))
                     for name, mesh in v[1]},
                    {tuple(k): tuple(indices) for k, indices in v[2]}, v[3], v[4])
                return world, vobs, stamp
            except (ValueError, TypeError, IndexError, KeyError, zlib.error):
                pass
    world, vobs = load_world_with_vobs(source, chunk_size, sources)
    if key and vobs is not None:
        try:
            w = (world.vertices, list(world.chunks.items()), world.chunk_size, world.total_vertices,
                 world.total_triangles, world.discarded_triangles, world.origin,
                 list(world.chunk_uvs.items()), list(world.chunk_textures.items()))
            v = ([(obj.visual, obj.position, obj.rotation, obj.name, obj.chunk) for obj in vobs.objects],
                 [(name, (mesh.vertices, mesh.faces, mesh.uvs, mesh.texture_names))
                  for name, mesh in vobs.models.items()], list(vobs.chunks.items()), vobs.status, vobs.skipped)
            raw = json.dumps((w, v), separators=(',', ':')).encode('utf-8')
            if len(raw) < 256 * 1024 * 1024:
                cache.write(key, zlib.compress(raw, 1))
        except (ValueError, TypeError, OSError):
            pass
    return world, vobs, stamp
