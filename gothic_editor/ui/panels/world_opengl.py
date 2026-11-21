"""Optional hardware-accelerated preview of Gothic world polygons.

The OpenGL context is owned by pyopengltk's Tk frame. This module is loaded
only when the optional dependencies are available. No engine/game files change.
"""
from __future__ import annotations

from math import cos, sin, degrees, radians, tan

from OpenGL.GL import (
    glBegin, glClear, glClearColor, glColor3f, glDisable, glEnable, glEnd,
    glLoadIdentity, glMatrixMode, glMultMatrixf, glOrtho, glPolygonMode,
    glRotatef, glScalef, glTranslatef, glVertex3f, glViewport,
    GL_BACK, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST,
    GL_FILL, GL_FRONT_AND_BACK, GL_LEQUAL, GL_LINE, GL_MODELVIEW,
    GL_PROJECTION, GL_TRIANGLES, glDepthFunc,
)
from OpenGL.GLU import gluPerspective
from pyopengltk import OpenGLFrame

from gothic_editor.core.world_preview import face_color


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

    def initgl(self):
        glClearColor(0.098, 0.118, 0.161, 1.0)
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LEQUAL)
        # World polygons can have inconsistent winding. Double-sided for now.
        from OpenGL.GL import GL_CULL_FACE
        glDisable(GL_CULL_FACE)

    def redraw(self):
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
            cy, sy = cos(camera.yaw), sin(camera.yaw)
            cp, sp = cos(camera.pitch), sin(camera.pitch)
            view = [
                cy, -sp*sy, -cp*sy, 0.,
                0., cp, -sp, 0.,
                -sy, -sp*cy, -cp*cy, 0.,
                0., 0., 0., 1.,
            ]
            glMultMatrixf(view)
            glTranslatef(-camera.x, -camera.y, -camera.z)
        else:
            glScalef(1., 1., -1.)
            glRotatef(degrees(self.pitch), 1., 0., 0.)
            glRotatef(degrees(self.yaw), 0., 1., 0.)
            glTranslatef(-self.center[0], -self.center[1], -self.center[2])

        glPolygonMode(GL_FRONT_AND_BACK, GL_FILL if self.solid else GL_LINE)
        vertices = self.scene.vertices
        glBegin(GL_TRIANGLES)
        try:
            for face in self.scene.faces:
                color = face_color(vertices, face)
                glColor3f(*(int(color[i:i+2], 16) / 255.0 for i in (1, 3, 5)))
                for index in face:
                    glVertex3f(*vertices[index])
        finally:
            glEnd()
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
