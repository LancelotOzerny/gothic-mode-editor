"""Optional hardware-accelerated preview of Gothic world polygons.

The OpenGL context is owned by pyopengltk's Tk frame. This module is loaded
only when the optional dependencies are available. No engine/game files change.
"""
from __future__ import annotations

from math import degrees
from time import perf_counter
from collections import OrderedDict

from OpenGL.GL import (
    glBegin, glClear, glClearColor, glColor3f, glDisable, glEnable, glEnd,
    glLoadIdentity, glMatrixMode, glMultMatrixf, glOrtho, glPolygonMode,
    glRotatef, glScalef, glTranslatef, glVertex3f, glViewport, glGetIntegerv,
    glCallList, glDeleteLists, glEndList, glGenLists, glNewList,
    glPushMatrix, glPopMatrix, glGetString, GL_RENDERER,
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST, GL_DEPTH_BITS,
    GL_FILL, GL_FRONT_AND_BACK, GL_LEQUAL, GL_LINE, GL_MODELVIEW,
    GL_PROJECTION, GL_TRIANGLES, glDepthFunc, GL_COMPILE,
    glBindTexture, glGenTextures, glDeleteTextures, glTexImage2D,
    glTexParameteri, glTexCoord2f, glTexEnvi, glPixelStorei,
    GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_LINEAR, GL_LINEAR_MIPMAP_LINEAR, GL_REPEAT,
    GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE, GL_RGBA,
    GL_UNSIGNED_BYTE, GL_UNPACK_ALIGNMENT,
    glAlphaFunc, GL_ALPHA_TEST, GL_GREATER,
)
from OpenGL.GLU import gluPerspective
from pyopengltk import OpenGLFrame

from gothic_editor.core.world_preview import face_color
from gothic_editor.core.fly_camera import gl_view_rotation


class WorldOpenGLFrame(OpenGLFrame):
    """Draw triangles with a true hardware depth buffer (no painter sorting)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.scene = None
        self.fly = False
        self.camera = None
        self.center = (0.0, 0.0, 0.0)
        self.yaw = 0.0
        self.pitch = 0.0
        self.zoom = 1.0
        self.span = 6000.0
        self.solid = True
        self.render_mode = 'textures'
        self.textures = None
        self._cached_textures = None
        self._gpu_textures = OrderedDict()
        self._texture_alpha = {}
        self._canonical_cache = {}
        self._canonical_cache_sources = None
        self._bound_texture = None
        self._alpha_enabled = False
        self._draw_calls = 0
        self._texture_switches = 0
        self._gpu_texture_bytes = 0
        self._invalid_gpu = set()
        self._gpu_texture_budget = 256 * 1024 * 1024
        self._visible_gpu = set()
        self._visible_gpu_key = None
        self._visible_vob_names = ()
        self.animate = True
        self._failed = False
        self.world = None
        self.vobs = None
        self._cached_vobs = None
        self._vob_lists = {}
        self.focus = None
        self.radius = 1
        self.triangle_limit = 200_000
        self._cached_world = None
        self._lists = OrderedDict()
        self._cached_triangles = 0
        self._gpu_triangle_budget = 450_000
        self._selected_key = None
        self._selected_chunks = ()
        self._warm_key = None
        self._warm_chunks = ()
        self._chunk_names = {}
        self._vob_names = {}
        self._warm_texture_names = ()
        self._warm_texture_cursor = 0
        self._can_warm_gpu = False
        self._vob_upload_cursor = 0
        self._profile_started = perf_counter()
        self._profile_frames = 0
        self._profile_times = {'prepare': 0., 'terrain': 0., 'vobs': 0., 'warm': 0., 'upload': 0.}
        self._profile_uploads = 0
        self._profile_draw_calls = 0
        self._profile_texture_switches = 0
        self._profile_slowest_upload = ('', 0.)
        self._profile_peak = 0.

    def _failed_context(self, exc):
        if self._failed:
            return
        self._failed = True
        self.animate = False
        # Return to the Tk renderer on the event loop.
        self.after_idle(lambda: self.master._disable_opengl(str(exc)))

    def initgl(self):
        try:
            glClearColor(0.098, 0.118, 0.161, 1.0)
            if int(glGetIntegerv(GL_DEPTH_BITS)) < 16:
                raise RuntimeError('OpenGL-контекст не поддерживает буфер глубины.')
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(GL_LEQUAL)
            # World polygons can have inconsistent winding. Double-sided.
            from OpenGL.GL import GL_CULL_FACE
            glDisable(GL_CULL_FACE)
            glDisable(GL_ALPHA_TEST)
            glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE)
            gpu_name = glGetString(GL_RENDERER)
            if gpu_name:
                label = gpu_name.decode('utf-8', errors='replace') if isinstance(gpu_name, bytes) else str(gpu_name)
                self.after_idle(lambda text=label: self.master._log_message('[OpenGL] Видеоустройство: ' + text))
        except Exception as exc:
            self._failed_context(exc)

    def redraw(self):
        if self._failed:
            return
        started = perf_counter()
        try:
            self._redraw_scene()
        except Exception as exc:
            self._failed_context(exc)
        finally:
            if self.world is not None:
                duration = perf_counter() - started
                self._profile_frames += 1
                self._profile_draw_calls += self._draw_calls
                self._profile_texture_switches += self._texture_switches
                self._profile_peak = max(self._profile_peak, duration)
                window = perf_counter() - self._profile_started
                if window >= 5.0:
                    frames = max(1, self._profile_frames)
                    stages = ', '.join(f'{name}={1000*value/frames:.0f}мс'
                                       for name, value in self._profile_times.items())
                    message = (f'[OpenGL] {self.render_mode}: {frames/window:.1f} FPS, '
                               f'макс. кадр {self._profile_peak*1000:.0f}мс, '
                               f'{stages}, GPU-текстур: {len(self._gpu_textures)}, '
                               f'загрузок: {self._profile_uploads}, '
                               f'вызовов GL/кадр: {self._profile_draw_calls/frames:.0f}, '
                               f'переключений/кадр: {self._profile_texture_switches/frames:.0f}, '
                               f'макс. upload: {self._profile_slowest_upload[1]*1000:.0f}мс '
                               f'({self._profile_slowest_upload[0]})')
                    self.after_idle(lambda msg=message: self.master._log_message(msg))
                    self._profile_started = perf_counter()
                    self._profile_frames = 0
                    self._profile_peak = 0.
                    self._profile_times = dict.fromkeys(self._profile_times, 0.)
                    self._profile_uploads = 0
                    self._profile_draw_calls = 0
                    self._profile_texture_switches = 0
                    self._profile_slowest_upload = ('', 0.)

    def _redraw_scene(self):
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        self._uploads_this_frame = 0
        self._draw_calls = 0
        self._texture_switches = 0
        self._bound_texture = None
        self._alpha_enabled = False
        self._frame_start = perf_counter()
        glViewport(0, 0, width, height)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if self.world is None:
            return
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        if self.fly and self.camera is not None:
            gluPerspective(70.0, width / height, 10.0, 600000.0)
        else:
            scale = min(width, height) * 0.85 * self.zoom / max(self.span, 1.0)
            half_w, half_h = width / (2.0 * scale), height / (2.0 * scale)
            glOrtho(-half_w, half_w, -half_h, half_h, -1000000., 1000000.)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        if self.fly and self.camera is not None:
            # Match the existing +Z-forward ZenGin camera projection.
            camera = self.camera
            glMultMatrixf(gl_view_rotation(camera))
            glTranslatef(-camera.x, -camera.y, -camera.z)
        else:
            glScalef(1., 1., -1.)
            glRotatef(degrees(self.pitch), 1., 0., 0.)
            glRotatef(degrees(self.yaw), 0., 1., 0.)
            glTranslatef(-self.center[0], -self.center[1], -self.center[2])

        if self.textures is not self._cached_textures:
            self._delete_textures()
            self._cached_textures = self.textures
        timestamp = perf_counter()
        self._pin_visible_textures()
        self._prepare_visible_vobs()
        self._profile_times['prepare'] += perf_counter() - timestamp
        timestamp = perf_counter()
        self._draw_chunks()
        self._profile_times['terrain'] += perf_counter() - timestamp
        timestamp = perf_counter()
        self._draw_vobs()
        self._profile_times['vobs'] += perf_counter() - timestamp
        timestamp = perf_counter()
        # Avoid speculative GPU uploads while visible surfaces are rendering.
        # In dense worlds these evicted needed textures and triggered stalls.
        self._profile_times['warm'] += perf_counter() - timestamp
        glDisable(GL_TEXTURE_2D)
        glDisable(GL_ALPHA_TEST)

    def _delete_textures(self):
        if self._gpu_textures:
            glDeleteTextures([entry[0] for entry in self._gpu_textures.values()])
        self._gpu_textures.clear()
        self._texture_alpha.clear()
        self._canonical_cache.clear()
        self._canonical_cache_sources = None
        self._bound_texture = None
        self._alpha_enabled = False
        self._gpu_texture_bytes = 0
        self._invalid_gpu.clear()
        self._visible_gpu_key = None

    def _canonical_texture(self, name):
        # Each visible material group calls this every frame. Cache filename
        # normalization; pathlib and 4x lookup cost add up across thousands
        # of individual OpenGL display lists.
        source_key = (id(self.textures), len(self.textures.sources))
        if source_key != self._canonical_cache_sources:
            self._canonical_cache.clear()
            self._canonical_cache_sources = source_key
        cached = self._canonical_cache.get(name)
        if cached is not None:
            return cached
        from gothic_editor.core.texture_names import texture_candidates
        identifier = next((candidate for candidate in texture_candidates(name)
                           if candidate in self.textures.sources), name.casefold())
        self._canonical_cache[name] = identifier
        return identifier

    def _pin_visible_textures(self):
        """Avoid evicting textures still needed by this frame's world/VOBs."""
        if self.textures is None or self.render_mode != 'textures' or self.focus is None:
            self._visible_gpu.clear()
            self._visible_vob_names = ()
            self._visible_gpu_key = None
            return
        key = (id(self.world), id(self.vobs), id(self.textures),
               self.focus, self.radius, self.triangle_limit, len(self.textures.sources))
        if key == self._visible_gpu_key:
            return
        self._visible_gpu_key = key
        self._visible_gpu.clear()
        if self.world is not self._cached_world:
            self._chunk_names.clear()
        keys = self.world.visible_chunk_keys(self.focus, self.radius, self.triangle_limit)
        for key in keys:
            unique = self._chunk_names.get(key)
            if unique is None:
                unique = tuple(dict.fromkeys(
                    name for uv, name in zip(
                        self.world.chunk_uvs.get(key, ()),
                        self.world.chunk_textures.get(key, ()))
                    if uv is not None and name))
                self._chunk_names[key] = unique
            self._visible_gpu.update(self._canonical_texture(name) for name in unique)
        vob_names = []
        if self.vobs is not None:
            if self.vobs is not self._cached_vobs:
                self._vob_names.clear()
            for key, indices in self.vobs.chunks.items():
                if abs(key[0] - self.focus[0]) > self.radius or abs(key[1] - self.focus[1]) > self.radius:
                    continue
                for index in indices:
                    visual = self.vobs.objects[index].visual
                    names = self._vob_names.get(visual)
                    if names is None:
                        mesh = self.vobs.models[visual]
                        names = tuple(dict.fromkeys(
                            name for uv, name in zip(mesh.uvs, mesh.texture_names)
                            if uv is not None and name))
                        self._vob_names[visual] = names
                    self._visible_gpu.update(self._canonical_texture(name) for name in names)
                    vob_names.extend(names)
        self._visible_vob_names = tuple(dict.fromkeys(vob_names))

    def _prepare_visible_vobs(self):
        if self.textures is None or self.render_mode != 'textures':
            return
        # Start VOB decoding before terrain/neighbor prefetch fills the queue.
        self.textures.prefetch(
            name for name in self._visible_vob_names if self._needs_decode(name))
        # Probe only a small rotating set each frame. Scanning every VOB
        # material synchronously was expensive in densely decorated worlds.
        count = len(self._visible_vob_names)
        for _ in range(min(count, 8)):
            name = self._visible_vob_names[self._vob_upload_cursor % count]
            self._vob_upload_cursor = (self._vob_upload_cursor + 1) % count
            if self._needs_decode(name) and self._texture_id(name):
                break

    def _texture_id(self, name):
        if self.render_mode != 'textures' or self.textures is None or not name:
            return 0
        identifier = self._canonical_texture(name)
        if identifier in self._invalid_gpu:
            return 0
        if identifier in self._gpu_textures:
            self._gpu_textures.move_to_end(identifier)
            return self._gpu_textures[identifier][0]
        if (self._uploads_this_frame >= 2 or
                (self._uploads_this_frame and perf_counter() - self._frame_start > 0.006)):
            return 0
        texture = self.textures.request(name)
        if texture is None:
            return 0
        # Current preview uses one GPU level; count only actual allocated bytes.
        size = len(texture.pixels)
        if size > self._gpu_texture_budget:
            return 0
        if self._gpu_texture_bytes + size > self._gpu_texture_budget:
            reclaimable = sum(old_size for key, (_id, old_size) in self._gpu_textures.items()
                              if key not in self._visible_gpu)
            if self._gpu_texture_bytes + size - reclaimable > self._gpu_texture_budget:
                # Insufficient free space without evicting a visible material.
                return 0
        tex_id = 0
        upload_start = perf_counter()
        try:
            tex_id = int(glGenTextures(1))
            if not tex_id:
                return 0
            glBindTexture(GL_TEXTURE_2D, tex_id)
            glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, texture.width, texture.height,
                         0, GL_RGBA, GL_UNSIGNED_BYTE, texture.pixels)
            # No glGenerateMipmap during the draw: some software/legacy GL
            # drivers stall for hundreds of milliseconds per new texture.
            # Restore mipmaps only after the upload bottleneck is resolved.
        except Exception as exc:
            if tex_id:
                glDeleteTextures([tex_id])
            self._invalid_gpu.add(identifier)
            self.textures.report_error(name, exc)
            return 0
        elapsed = perf_counter() - upload_start
        self._profile_times['upload'] += elapsed
        self._profile_uploads += 1
        if elapsed > self._profile_slowest_upload[1]:
            self._profile_slowest_upload = (identifier, elapsed)
        while self._gpu_texture_bytes + size > self._gpu_texture_budget and self._gpu_textures:
            victim = next((key for key in self._gpu_textures
                           if key not in self._visible_gpu), None)
            if victim is None:
                glDeleteTextures([tex_id])
                return 0
            old_id, old_size = self._gpu_textures.pop(victim)
            self._texture_alpha.pop(old_id, None)
            glDeleteTextures([old_id])
            self._gpu_texture_bytes -= old_size
        # glTexImage2D changes the actual GL binding behind the state cache.
        self._bound_texture = None
        self._gpu_textures[identifier] = (tex_id, size)
        self._texture_alpha[tex_id] = self.textures.has_alpha(name)
        self._gpu_texture_bytes += size
        self._uploads_this_frame += 1
        return tex_id

    def _needs_decode(self, name):
        if not name:
            return False
        candidate = self._canonical_texture(name)
        return candidate not in self._gpu_textures and candidate not in self._invalid_gpu

    def _warm_gpu_textures(self):
        """Upload at most one neighbor texture on otherwise idle frames."""
        if (self.render_mode != 'textures' or self.textures is None
                or not self._can_warm_gpu or self._uploads_this_frame):
            return
        count = len(self._warm_texture_names)
        for _ in range(min(32, count)):
            name = self._warm_texture_names[self._warm_texture_cursor % count]
            self._warm_texture_cursor = (self._warm_texture_cursor + 1) % count
            if not self._needs_decode(name):
                continue
            if self._texture_id(name):
                break

    def _bind_texture(self, tex_id):
        if tex_id != self._bound_texture:
            if tex_id:
                if not self._bound_texture:
                    glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, tex_id)
            elif self._bound_texture:
                glDisable(GL_TEXTURE_2D)
            self._bound_texture = tex_id
            self._texture_switches += 1
        wants_alpha = bool(tex_id and self._texture_alpha.get(tex_id, False))
        if wants_alpha != self._alpha_enabled:
            if wants_alpha:
                glEnable(GL_ALPHA_TEST)
                glAlphaFunc(GL_GREATER, 0.1)
            else:
                glDisable(GL_ALPHA_TEST)
            self._alpha_enabled = wants_alpha

    def _draw_group(self, name, list_id):
        self._bind_texture(self._texture_id(name))
        glCallList(list_id)
        self._draw_calls += 1

    def _delete_lists(self):
        for groups, _count in self._lists.values():
            for _name, list_id in groups:
                glDeleteLists(list_id, 1)
        self._lists.clear()
        self._cached_triangles = 0

    def _compile_chunk(self, key):
        if key in self._lists:
            self._lists.move_to_end(key)
            return
        faces = self.world.chunks[key]
        vertices = self.world.vertices
        uvs = self.world.chunk_uvs.get(key, ())
        names = self.world.chunk_textures.get(key, ())
        batches = OrderedDict()
        for i, face in enumerate(faces):
            uv = uvs[i] if i < len(uvs) else None
            name = names[i] if i < len(names) and uv else ''
            batches.setdefault(name.casefold(), []).append((face, uv))
        lists = []
        try:
            for name, entries in batches.items():
                list_id = int(glGenLists(1))
                if not list_id:
                    raise RuntimeError('Не удалось создать список полигонов OpenGL.')
                lists.append((name, list_id))
                glNewList(list_id, GL_COMPILE)
                try:
                    glBegin(GL_TRIANGLES)
                    try:
                        for face, uv in entries:
                            color = face_color(vertices, face)
                            glColor3f(*(int(color[j:j+2], 16) / 255.0
                                        for j in (1, 3, 5)))
                            for corner, index in enumerate(face):
                                if uv is not None:
                                    glTexCoord2f(*uv[corner])
                                glVertex3f(*vertices[index])
                    finally:
                        glEnd()
                finally:
                    glEndList()
        except Exception:
            for _name, list_id in lists:
                glDeleteLists(list_id, 1)
            raise
        self._lists[key] = (tuple(lists), len(faces))
        self._cached_triangles += len(faces)

    def _draw_vobs(self):
        scene = self.vobs
        if scene is not self._cached_vobs:
            for lists in self._vob_lists.values():
                for _name, list_id in lists:
                    glDeleteLists(list_id, 1)
            self._vob_lists.clear()
            self._vob_names.clear()
            self._cached_vobs = scene
        if scene is None or not scene.objects or self.focus is None:
            return

        nearby = [
            key for key in scene.chunks
            if abs(key[0] - self.focus[0]) <= self.radius and
               abs(key[1] - self.focus[1]) <= self.radius
        ]
        nearby.sort()
        # Precompile one unique visual per frame, just like the terrain chunks.
        for key in nearby:
            for index in scene.chunks[key]:
                visual = scene.objects[index].visual
                if visual not in self._vob_lists:
                    self._compile_vob(visual, scene.models[visual])
                    break
            else:
                continue
            break

        # Group by material instead of binding the same texture per instance.
        # GL_ALPHA_TEST + depth testing makes these cutouts order-independent.
        grouped = OrderedDict()
        for key in nearby:
            for index in scene.chunks[key]:
                vob = scene.objects[index]
                lists = self._vob_lists.get(vob.visual)
                if lists is None:
                    continue
                rot = vob.rotation
                px, py, pz = vob.position
                matrix = (rot[0], rot[3], rot[6], 0.,
                          rot[1], rot[4], rot[7], 0.,
                          rot[2], rot[5], rot[8], 0.,
                          px, py, pz, 1.)
                for texture, list_id in lists:
                    grouped.setdefault(texture, []).append((list_id, matrix))
        glPolygonMode(GL_FRONT_AND_BACK, GL_LINE if self.render_mode == 'wire' else GL_FILL)
        try:
            for texture, instances in grouped.items():
                tex_id = self._texture_id(texture)
                self._bind_texture(tex_id)
                for list_id, matrix in instances:
                    glPushMatrix()
                    try:
                        glMultMatrixf(matrix)
                        glCallList(list_id)
                        self._draw_calls += 1
                    finally:
                        glPopMatrix()
        finally:
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)

    def _compile_vob(self, name, mesh):
        batches = OrderedDict()
        for i, face in enumerate(mesh.faces):
            uv = mesh.uvs[i] if i < len(mesh.uvs) else None
            texture = mesh.texture_names[i] if i < len(mesh.texture_names) and uv else ''
            batches.setdefault(texture.casefold(), []).append((face, uv))
        lists = []
        try:
            for texture, entries in batches.items():
                list_id = int(glGenLists(1))
                if not list_id:
                    raise RuntimeError('Не удалось выделить OpenGL-список для VOB.')
                lists.append((texture, list_id))
                glNewList(list_id, GL_COMPILE)
                try:
                    glBegin(GL_TRIANGLES)
                    try:
                        for face, uv in entries:
                            color = face_color(mesh.vertices, face)
                            glColor3f(*(int(color[j:j+2], 16)/255.0 for j in (1, 3, 5)))
                            for corner, index in enumerate(face):
                                if uv is not None:
                                    glTexCoord2f(*uv[corner])
                                glVertex3f(*mesh.vertices[index])
                    finally:
                        glEnd()
                finally:
                    glEndList()
        except Exception:
            for _texture, list_id in lists:
                glDeleteLists(list_id, 1)
            raise
        self._vob_lists[name] = tuple(lists)

    def _draw_chunks(self):
        self._can_warm_gpu = False
        if self.world is None:
            return
        if self._cached_world is not self.world:
            self._delete_lists()
            self._chunk_names.clear()
            self._cached_world = self.world
            self._selected_key = None
            self._warm_key = None
            self._warm_texture_names = ()
            self._warm_texture_cursor = 0
        if self.focus is None:
            return

        selection_key = (self.focus, self.radius, self.triangle_limit)
        if selection_key != self._selected_key:
            self._selected_chunks = self.world.visible_chunk_keys(
                self.focus, self.radius, self.triangle_limit)
            self._selected_key = selection_key
        visible = self._selected_chunks
        warm_radius = min(5, self.radius + 1)
        warm_key = (self.focus, self.radius, self.triangle_limit)
        if warm_key != self._warm_key:
            # Use an independent prefetch budget. Reusing the visible
            # 200k budget prevented dense worlds from warming any neighbor.
            extra = []
            remaining = max(0, self._gpu_triangle_budget -
                            sum(len(self.world.chunks[k]) for k in visible))
            candidates = [
                k for k in self.world.chunks
                if k not in visible and
                   abs(k[0]-self.focus[0]) <= warm_radius and
                   abs(k[1]-self.focus[1]) <= warm_radius
            ]
            candidates.sort(key=lambda k: (
                (k[0]-self.focus[0])**2 + (k[1]-self.focus[1])**2, k))
            for key in candidates:
                count = len(self.world.chunks[key])
                if count <= remaining:
                    extra.append(key)
                    remaining -= count
            self._warm_chunks = tuple(extra)
            self._warm_key = warm_key
            self._warm_texture_names = ()
            self._warm_texture_cursor = 0

        if self.render_mode == 'textures' and self.textures is not None:
            # Decode visible materials before warm neighbors; one chunk may
            # reference a texture hundreds of times, so cache unique names.
            names = []
            for key in (*visible, *self._warm_chunks):
                unique = self._chunk_names.get(key)
                if unique is None:
                    unique = tuple(dict.fromkeys(
                        name for uv, name in zip(
                            self.world.chunk_uvs.get(key, ()),
                            self.world.chunk_textures.get(key, ()))
                        if uv is not None and name))
                    self._chunk_names[key] = unique
                names.extend(unique)
            self.textures.prefetch(name for name in names if self._needs_decode(name))
            if not self._warm_texture_names and self._warm_chunks:
                self._warm_texture_names = tuple(dict.fromkeys(
                    name for key in self._warm_chunks for name in self._chunk_names[key]))

        missing_visible = [key for key in visible if key not in self._lists]
        missing_warm = [key for key in self._warm_chunks
                        if key not in self._lists]
        self._can_warm_gpu = not missing_visible and not missing_warm
        # Limit compilation to one chunk per frame; the camera never rebuilds
        # a combined mesh when crossing a chunk boundary.
        for key in (missing_visible or missing_warm)[:1]:
            self._compile_chunk(key)

        glPolygonMode(GL_FRONT_AND_BACK, GL_FILL if self.solid else GL_LINE)
        try:
            for key in visible:
                cached = self._lists.get(key)
                if cached is not None:
                    self._lists.move_to_end(key)
                    for name, list_id in cached[0]:
                        self._draw_group(name, list_id)
        finally:
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)

        pinned = set(visible)
        for key in tuple(self._lists):
            if self._cached_triangles <= self._gpu_triangle_budget:
                break
            if key in pinned:
                continue
            lists, count = self._lists.pop(key)
            for _name, list_id in lists:
                glDeleteLists(list_id, 1)
            self._cached_triangles -= count
