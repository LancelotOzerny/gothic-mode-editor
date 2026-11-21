"""Lightweight world wireframe preparation and orthographic camera projection.

The full ZEN mesh stays off the Tk drawing thread; only bounded, deterministic
triangle samples are passed to the interactive preview. No extra dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, sin, isfinite, floor
from pathlib import Path
from tempfile import TemporaryDirectory
from .vdf import VdfArchive, VdfEntry, VdfFormatError

from .zen_world import load_zen_geometry, ZenWorldError


MAX_PREVIEW_TRIANGLES = 3500
# OpenGL can draw whole chunks. Avoid arbitrary triangle sampling, which makes
# terrain and castle walls look like scattered pieces.
MAX_OPENGL_TRIANGLES = 200_000

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
    discarded_triangles: int = 0


def prepare_wireframe(geometry, limit=MAX_PREVIEW_TRIANGLES):
    """Decimate by sampling face indices and remap only referenced vertices."""
    if not 1 <= limit <= MAX_PREVIEW_TRIANGLES:
        raise ValueError('Некорректный предел треугольников для предпросмотра.')
    # A malformed or non-finite vertex must not poison the bounding box or
    # stop rendering every other triangle in a large world.
    vertices = geometry.vertices
    safe_vertices = tuple(
        len(vertex) == 3 and all(isfinite(value) and abs(value) <= 1e8
                                 for value in vertex)
        for vertex in vertices)
    faces = geometry.triangles

    def valid(face):
        return (len(face) == 3 and
                all(isinstance(index, int) and 0 <= index < len(vertices)
                    and safe_vertices[index] for index in face))

    valid_count = sum(valid(face) for face in faces)
    discarded = len(faces) - valid_count
    if valid_count == 0:
        return WireframeScene((), (), geometry.vertex_count,
                              geometry.triangle_count, discarded)
    # Two streaming passes keep the sample size fixed even for very large worlds.
    sample_size = min(limit, valid_count)
    targets = iter(index * valid_count // sample_size for index in range(sample_size))
    next_target = next(targets, None)
    selected = []
    number = 0
    for face in faces:
        if not valid(face):
            continue
        if number == next_target:
            selected.append(face)
            next_target = next(targets, None)
            if next_target is None:
                break
        number += 1
    used = sorted({vertex for face in selected for vertex in face})
    indices = {old: new for new, old in enumerate(used)}
    compact = tuple(vertices[index] for index in used)
    remapped = tuple(tuple(indices[index] for index in face) for face in selected)
    return WireframeScene(compact, remapped, geometry.vertex_count,
                          geometry.triangle_count, discarded)

@dataclass(frozen=True)
class ChunkedWorld:
    """Spatial index of valid triangles, grouped by X/Z centroid."""
    vertices: tuple
    chunks: dict[tuple[int, int], tuple[tuple[int, int, int], ...]]
    chunk_size: int
    total_vertices: int
    total_triangles: int
    discarded_triangles: int
    origin: tuple[int, int]

    def visible_triangle_count(self, focus=None, radius=1):
        focus = self.origin if focus is None else focus
        return sum(len(faces) for (x, z), faces in self.chunks.items()
                   if abs(x-focus[0]) <= radius and abs(z-focus[1]) <= radius)

    def visible_chunk_keys(self, focus=None, radius=1,
                           triangle_limit=MAX_OPENGL_TRIANGLES):
        """Select entire nearby chunks within one triangle budget.

        This lightweight index operation is shared by the GPU renderer and
        status reporting: it never copies or remaps vertices or faces.
        """
        if not 0 <= radius <= 5 or not 1 <= triangle_limit <= MAX_OPENGL_TRIANGLES:
            raise ValueError('Некорректные настройки полной геометрии.')
        focus = self.origin if focus is None else focus
        nearby = [
            key for key in self.chunks
            if abs(key[0]-focus[0]) <= radius and abs(key[1]-focus[1]) <= radius
        ]
        nearby.sort(key=lambda key: (
            (key[0]-focus[0])**2 + (key[1]-focus[1])**2, key))
        selected = []
        remaining = triangle_limit
        for key in nearby:
            size = len(self.chunks[key])
            if size <= remaining:
                selected.append(key)
                remaining -= size
        return tuple(selected)

    def view_complete(self, focus=None, radius=1,
                      triangle_limit=MAX_OPENGL_TRIANGLES):
        """Select complete nearby chunks, never random faces within a chunk.

        If a chunk exceeds the budget it is omitted entirely. This is safer
        than leaving random holes in the terrain. Return a regular render
        scene; the caller can compare its face count with visible_triangle_count.
        """
        keys = self.visible_chunk_keys(focus, radius, triangle_limit)
        selected = [face for key in keys for face in self.chunks[key]]
        if not selected:
            return WireframeScene((), (), self.total_vertices,
                                  self.total_triangles, self.discarded_triangles)
        used = sorted({index for face in selected for index in face})
        mapping = {source: index for index, source in enumerate(used)}
        return WireframeScene(
            tuple(self.vertices[index] for index in used),
            tuple(tuple(mapping[index] for index in face) for face in selected),
            self.total_vertices, self.total_triangles, self.discarded_triangles)

    def view(self, focus=None, radius=1, triangle_limit=3500):
        if radius < 0 or radius > 5 or not 1 <= triangle_limit <= 10000:
            raise ValueError('Некорректные настройки отображения чанков.')
        focus = self.origin if focus is None else focus
        visible = [key for key in self.chunks
                   if abs(key[0] - focus[0]) <= radius and
                      abs(key[1] - focus[1]) <= radius]
        visible.sort(key=lambda key: ((key[0]-focus[0])**2 + (key[1]-focus[1])**2, key))
        if not visible:
            return WireframeScene((), (), self.total_vertices,
                                  self.total_triangles, self.discarded_triangles)
        # Distribute the global draw budget across nearby chunks. The budget
        # is never exceeded, and each selected triangle is complete.
        remaining = triangle_limit
        selected = []
        for i, key in enumerate(visible):
            if remaining <= 0:
                break
            pool = self.chunks[key]
            quota = min(len(pool), max(1, remaining // (len(visible) - i)))
            selected.extend(pool[k * len(pool) // quota] for k in range(quota))
            remaining -= quota
        used = sorted({vertex for face in selected for vertex in face})
        mapping = {old: new for new, old in enumerate(used)}
        return WireframeScene(
            tuple(self.vertices[i] for i in used),
            tuple(tuple(mapping[i] for i in face) for face in selected),
            self.total_vertices, self.total_triangles, self.discarded_triangles)


def build_world_chunks(geometry, chunk_size=6000):
    """Group triangles by their X/Z centroid, preserving complete faces."""
    if type(chunk_size) is not int or not 500 <= chunk_size <= 100000:
        raise ValueError('Размер чанка должен быть от 500 до 100000 см.')
    vertices = geometry.vertices
    safe = tuple(len(v) == 3 and all(isfinite(x) and abs(x) <= 1e8 for x in v)
                 for v in vertices)
    groups = {}
    discarded = 0
    for face in geometry.triangles:
        if (len(face) != 3 or not all(
                isinstance(i, int) and 0 <= i < len(vertices) and safe[i] for i in face)):
            discarded += 1
            continue
        x = sum(vertices[i][0] for i in face) / 3
        z = sum(vertices[i][2] for i in face) / 3
        key = (floor(x / chunk_size), floor(z / chunk_size))
        groups.setdefault(key, []).append(tuple(face))
    if groups:
        lo_x, hi_x = min(x for x, _ in groups), max(x for x, _ in groups)
        lo_z, hi_z = min(z for _, z in groups), max(z for _, z in groups)
        middle = ((lo_x + hi_x) / 2, (lo_z + hi_z) / 2)
        center = min(groups, key=lambda k: ((k[0]-middle[0])**2 + (k[1]-middle[1])**2, k))
    else:
        center = (0, 0)
    return ChunkedWorld(tuple(vertices),
                        {key: tuple(faces) for key, faces in groups.items()},
                        chunk_size, geometry.vertex_count, geometry.triangle_count,
                        discarded, center)


def load_world_wireframe(path: str | Path | VdfEntry, chunk_size=6000):
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
    return build_world_chunks(geometry, chunk_size)


def load_world_with_vobs(path, chunk_size=6000, sources=None):
    """Load terrain and VOB models together without touching Tk widgets.

    Archived ZEN is extracted only once and only to a temporary directory.
    """
    from .world_vobs import load_vob_scene
    if not is_location_zen(path):
        raise ZenWorldError('Выберите игровую локацию .ZEN.')
    if isinstance(path, VdfEntry):
        with TemporaryDirectory(prefix='gothic-zen-') as temporary:
            destination = Path(temporary) / Path(path.name).name
            with path.archive.open('rb') as src, destination.open('wb') as target:
                src.seek(path.offset)
                remaining = path.size
                while remaining:
                    block = src.read(min(1024*1024, remaining))
                    if not block:
                        raise ZenWorldError('Неожиданный конец архива VDF.')
                    target.write(block)
                    remaining -= len(block)
            return (load_world_wireframe(destination, chunk_size),
                    load_vob_scene(destination, sources or {}, chunk_size))
    return (load_world_wireframe(path, chunk_size),
            load_vob_scene(path, sources or {}, chunk_size))


def project_wireframe(scene, width, height, yaw, pitch, zoom, pan_x=0.0, pan_y=0.0, *, center=None, span=None):
    """Project 3D world coordinates to screen; return vertex screen positions."""
    if not scene.vertices:
        return ()
    vertices = scene.vertices
    lo = tuple(min(v[axis] for v in vertices) for axis in range(3))
    hi = tuple(max(v[axis] for v in vertices) for axis in range(3))
    center = tuple((low + high) / 2 for low, high in zip(lo, hi)) if center is None else center
    # Tiny but non-zero world bounds can cause division to overflow to inf.
    # Badly decoded geometry frequently consists of subnormal float values.
    radius = max(high - low for low, high in zip(lo, hi)) if span is None else span
    if not isfinite(radius) or radius < 1e-6:
        radius = 1.0
    scale = min(width, height) * 0.85 * zoom / radius
    cos_yaw, sin_yaw = cos(yaw), sin(yaw)
    cos_pitch, sin_pitch = cos(pitch), sin(pitch)
    result = []
    for vx, vy, vz in vertices:
        x, y, z = vx-center[0], vy-center[1], vz-center[2]
        rx, rz = x*cos_yaw+z*sin_yaw, -x*sin_yaw+z*cos_yaw
        ry = y*cos_pitch-rz*sin_pitch
        depth = y*sin_pitch+rz*cos_pitch
        sx = width/2 + rx*scale + pan_x
        screen_y = height/2 - ry*scale + pan_y
        if not all(isfinite(v) for v in (sx, screen_y, depth)):
            raise ValueError(
                'Некорректные координаты модели ZEN: '
                f'вершина=({vx!r}, {vy!r}, {vz!r}), '
                f'границы={tuple(zip(lo, hi))!r}, '
                f'масштаб={scale!r}, камера=({yaw!r}, {pitch!r}, {zoom!r}), '
                f'экран=({width}, {height})')
        result.append((sx, screen_y, depth))
    return tuple(result)


def face_color(vertices, face):
    """Muted directional shading from world-space triangle normal."""
    from math import sqrt
    a, b, c = (vertices[i] for i in face)
    u = tuple(b[i] - a[i] for i in range(3))
    v = tuple(c[i] - a[i] for i in range(3))
    nx = u[1]*v[2]-u[2]*v[1]
    ny = u[2]*v[0]-u[0]*v[2]
    nz = u[0]*v[1]-u[1]*v[0]
    length = sqrt(nx*nx + ny*ny + nz*nz)
    if length < 1e-9:
        return '#344151'
    # Double-sided, since winding may vary in world meshes.
    strength = 0.36 + 0.64*abs((nx*0.28 + ny*0.84 + nz*0.46)/length)
    channels = tuple(int(base*strength) for base in (139, 161, 177))
    return '#%02x%02x%02x' % channels


def camera_chunk(center, chunk_size):
    """Current X/Z chunk from world-space camera center (negative safe)."""
    return floor(center[0] / chunk_size), floor(center[2] / chunk_size)


def move_camera(center, forward, right, yaw, distance):
    """Move along horizontal camera-aligned forward/right axes."""
    dx = (right*cos(yaw) - forward*sin(yaw)) * distance
    dz = (right*sin(yaw) + forward*cos(yaw)) * distance
    return center[0]+dx, center[1], center[2]+dz


def drag_camera(center, dx_pixels, dy_pixels, width, height, yaw, pitch,
                zoom, span):
    """Translate the camera by a screen-space drag, preserving the world anchor."""
    scale = min(width, height) * 0.85 * zoom / max(span, 1e-6)
    # Horizontal plane is edge-on at pitch=0: clamp that singularity.
    sp = sin(pitch)
    if abs(sp) < 0.15:
        sp = -0.15 if sp <= 0 else 0.15
    u = -dx_pixels / scale
    v = -dy_pixels / (sp * scale)
    dx = u*cos(yaw) - v*sin(yaw)
    dz = u*sin(yaw) + v*cos(yaw)
    return center[0]+dx, center[1], center[2]+dz
