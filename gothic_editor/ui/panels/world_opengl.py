"""Optional hardware-accelerated preview of Gothic world polygons.

The OpenGL context is owned by pyopengltk's Tk frame. This module is loaded
only when the optional dependencies are available. No engine/game files change.
"""
from __future__ import annotations

from math import degrees
from collections import OrderedDict

from OpenGL.GL import (
    glBegin, glClear, glClearColor, glColor3f, glDisable, glEnable, glEnd,
    glLoadIdentity, glMatrixMode, glMultMatrixf, glOrtho, glPolygonMode,
    glRotatef, glScalef, glTranslatef, glVertex3f, glViewport, glGetIntegerv,
    glCallList, glDeleteLists, glEndList, glGenLists, glNewList,
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST, GL_DEPTH_BITS,
    GL_FILL, GL_FRONT_AND_BACK, GL_LEQUAL, GL_LINE, GL_MODELVIEW,
    GL_PROJECTION, GL_TRIANGLES, glDepthFunc, GL_COMPILE,
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
        self.animate = True
        self._failed = False
        self.world = None
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
        except Exception as exc:
            self._failed_context(exc)

    def redraw(self):
        if self._failed:
            return
        try:
            self._redraw_scene()
        except Exception as exc:
            self._failed_context(exc)

    def _redraw_scene(self):
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
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

        self._draw_chunks()

    def _delete_lists(self):
        for list_id, _count in self._lists.values():
            glDeleteLists(list_id, 1)
        self._lists.clear()
        self._cached_triangles = 0

    def _compile_chunk(self, key):
        if key in self._lists:
            self._lists.move_to_end(key)
            return
        faces = self.world.chunks[key]
        vertices = self.world.vertices
        list_id = int(glGenLists(1))
        if not list_id:
            raise RuntimeError('Не удалось создать список полигонов OpenGL.')
        glNewList(list_id, GL_COMPILE)
        try:
            glBegin(GL_TRIANGLES)
            try:
                for face in faces:
                    color = face_color(vertices, face)
                    glColor3f(*(int(color[i:i+2], 16) / 255.0
                                for i in (1, 3, 5)))
                    for index in face:
                        glVertex3f(*vertices[index])
            finally:
                glEnd()
        finally:
            glEndList()
        self._lists[key] = (list_id, len(faces))
        self._cached_triangles += len(faces)

    def _draw_chunks(self):
        if self.world is None:
            return
        if self._cached_world is not self.world:
            self._delete_lists()
            self._cached_world = self.world
            self._selected_key = None
            self._warm_key = None
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

        missing_visible = [key for key in visible if key not in self._lists]
        missing_warm = [key for key in self._warm_chunks
                        if key not in self._lists]
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
                    glCallList(cached[0])
        finally:
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)

        pinned = set(visible)
        for key in tuple(self._lists):
            if self._cached_triangles <= self._gpu_triangle_budget:
                break
            if key in pinned:
                continue
            list_id, count = self._lists.pop(key)
            glDeleteLists(list_id, 1)
            self._cached_triangles -= count
