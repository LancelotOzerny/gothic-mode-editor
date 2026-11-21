"""Optional hardware-accelerated preview of Gothic world polygons.

The OpenGL context is owned by pyopengltk's Tk frame. This module is loaded
only when the optional dependencies are available. No engine/game files change.
"""
from __future__ import annotations

from math import degrees

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
        self._cached_scene = None
        self._display_list = None

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
        if self.scene is None or not self.scene.faces:
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

        if self._cached_scene is not self.scene:
            if self._display_list is not None:
                glDeleteLists(self._display_list, 1)
                self._display_list = None
            vertices = self.scene.vertices
            list_id = int(glGenLists(1))
            if not list_id:
                raise RuntimeError('Не удалось создать список полигонов OpenGL.')
            self._display_list = list_id
            glNewList(list_id, GL_COMPILE)
            try:
                glBegin(GL_TRIANGLES)
                try:
                    for face in self.scene.faces:
                        color = face_color(vertices, face)
                        glColor3f(*(int(color[i:i+2], 16) / 255.0
                                    for i in (1, 3, 5)))
                        for index in face:
                            glVertex3f(*vertices[index])
                finally:
                    glEnd()
            finally:
                glEndList()
            self._cached_scene = self.scene
        glPolygonMode(GL_FRONT_AND_BACK, GL_FILL if self.solid else GL_LINE)
        try:
            glCallList(self._display_list)
        finally:
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
