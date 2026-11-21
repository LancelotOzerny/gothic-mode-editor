"""Lightweight world wireframe preparation and orthographic camera projection.

The full ZEN mesh stays off the Tk drawing thread; only bounded, deterministic
triangle samples are passed to the interactive preview. No extra dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, sin, isfinite
from pathlib import Path
from tempfile import TemporaryDirectory
from .vdf import VdfArchive, VdfEntry, VdfFormatError

from .zen_world import load_zen_geometry, ZenWorldError


MAX_PREVIEW_TRIANGLES = 3500

# These ZenGin archives store shared presets, not playable level meshes.
PRESET_ARCHIVES = frozenset(('lensflare.zen', 'dialogcams.zen', 'lightpresets.zen'))


def is_location_zen(path: str | Path) -> bool:
    """Keep known engine preset archives out of the playable location list."""
    name = Path(path.name).name if isinstance(path, VdfEntry) else Path(path).name
    return Path(name).suffix.casefold() == '.zen' and name.casefold() not in PRESET_ARCHIVES


def available_locations(game: str | Path):
    """Find loose and archived worlds; retain loose files ahead of VDF entries."""
    from .zen_world import discover_zen
    game = Path(game)
    choices = {}
    for path in discover_zen(game):
        if is_location_zen(path):
            choices.setdefault(path.name.casefold(), path)
    data = game / 'Data'
    if data.is_dir():
        archives = sorted(
            (path for path in data.iterdir()
             if path.is_file() and path.suffix.casefold() in ('.vdf', '.mod')),
            key=lambda path: path.name.casefold())
        for archive_path in archives:
            try:
                archive = VdfArchive(archive_path, include_worlds=True)
            except (OSError, VdfFormatError):
                continue
            for entry in archive.entries.values():
                if is_location_zen(entry.name):
                    choices.setdefault(Path(entry.name).name.casefold(), entry)
    return sorted(choices.values(), key=lambda location: location.name.casefold())


@dataclass(frozen=True)
class WireframeScene:
    vertices: tuple[tuple[float, float, float], ...]
    faces: tuple[tuple[int, int, int], ...]
    total_vertices: int
    total_triangles: int


def prepare_wireframe(geometry, limit=MAX_PREVIEW_TRIANGLES):
    """Decimate by sampling face indices and remap only referenced vertices."""
    if not 1 <= limit <= MAX_PREVIEW_TRIANGLES:
        raise ValueError('Некорректный предел треугольников для предпросмотра.')
    faces = geometry.triangles
    count = len(faces)
    if not count:
        return WireframeScene((), (), geometry.vertex_count, geometry.triangle_count)
    sampled = [faces[index * count // min(count, limit)]
               for index in range(min(count, limit))]
    used = sorted({vertex for face in sampled for vertex in face})
    indices = {old: new for new, old in enumerate(used)}
    vertices = tuple(geometry.vertices[index] for index in used)
    remapped = tuple(tuple(indices[index] for index in face) for face in sampled)
    return WireframeScene(vertices, remapped, geometry.vertex_count, geometry.triangle_count)


def load_world_wireframe(path: str | Path | VdfEntry):
    """Worker-thread entry point: never touches Tk widgets."""
    if not is_location_zen(path):
        raise ZenWorldError('Это служебный архив Gothic с пресетами, а не игровая локация.')
    if isinstance(path, VdfEntry):
        # Extract only one requested archive member, in bounded chunks.
        # The original VDF and project files remain unchanged.
        with TemporaryDirectory(prefix='gothic-zen-') as temporary:
            destination = Path(temporary) / Path(path.name).name
            with path.archive.open('rb') as source, destination.open('wb') as output:
                source.seek(path.offset)
                remaining = path.size
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    if not block:
                        raise ZenWorldError('Неожиданный конец архива VDF.')
                    output.write(block)
                    remaining -= len(block)
            geometry = load_zen_geometry(destination, include_triangles=True)
    else:
        geometry = load_zen_geometry(path, include_triangles=True)
    return prepare_wireframe(geometry)


def project_wireframe(scene, width, height, yaw, pitch, zoom, pan_x=0.0, pan_y=0.0):
    """Project 3D world coordinates to screen; return vertex screen positions."""
    if not scene.vertices:
        return ()
    vertices = scene.vertices
    lo = tuple(min(v[axis] for v in vertices) for axis in range(3))
    hi = tuple(max(v[axis] for v in vertices) for axis in range(3))
    center = tuple((low + high) / 2 for low, high in zip(lo, hi))
    radius = max((high - low) for low, high in zip(lo, hi)) or 1
    scale = min(width, height) * 0.85 * zoom / radius
    cy, sy = cos(yaw), sin(yaw)
    cp, sp = cos(pitch), sin(pitch)
    result = []
    for vx, vy, vz in vertices:
        x, y, z = vx-center[0], vy-center[1], vz-center[2]
        rx, rz = x*cy+z*sy, -x*sy+z*cy
        ry = y*cp-rz*sp
        depth = y*sp+rz*cp
        sx = width/2 + rx*scale + pan_x
        sy = height/2 - ry*scale + pan_y
        if not all(isfinite(v) for v in (sx, sy, depth)):
            raise ValueError('Некорректные координаты модели ZEN.')
        result.append((sx, sy, depth))
    return tuple(result)
