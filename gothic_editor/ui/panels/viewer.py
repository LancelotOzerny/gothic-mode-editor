import tkinter as tk
from gothic_editor.core.localization import tr
from gothic_editor.core.mesh import PreviewMesh
from gothic_editor.core.preview_render import render_mesh
from gothic_editor.ui.widgets.buttons import PropertyButton

class ModelViewer(tk.Canvas):
    def __init__(self, master, **kwargs):
        super().__init__(master, bg='#191e29', highlightthickness=0, **kwargs)
        self.vertices, self.faces = [], []
        self.angle_x, self.angle_y = -0.38, 0.45
        self.zoom = 1.0
        self.last = None
        self.caption = tr('viewer.select_item')
        self.mesh = PreviewMesh([], [])
        self.textures = {}
        self.missing = []
        self.textured = True
        self.image = None
        self._draw_after = None
        self._quality_after = None
        self._preview_requested = False
        self.toolbar = tk.Frame(self, bg='#191e29')
        self.texture_button = PropertyButton(self.toolbar, lambda:self.set_textured(True),
            text='Т', filename='viewer_textured.png', caption=tr('viewer.textured'))
        self.solid_button = PropertyButton(self.toolbar, lambda:self.set_textured(False),
            text='М', filename='viewer_solid.png', caption=tr('viewer.solid'))
        for button in (self.texture_button, self.solid_button):
            button.configure(bg='#191e29')
            button.pack(side='left', padx=3)
        self.texture_button.set_selected(True)
        self.bind('<Configure>', lambda _: self.request_draw())
        self.bind('<ButtonPress-1>', self.start_drag)
        self.bind('<B1-Motion>', self.drag)
        self.bind('<ButtonRelease-1>', lambda _: self.request_draw())
        self.bind('<Destroy>', self._cancel_draws, add='+')
        self.bind('<MouseWheel>', self.wheel)
        self.bind('<Button-4>', lambda _: self.change_zoom(1.12))
        self.bind('<Button-5>', lambda _: self.change_zoom(1/1.12))

    def set_mesh(self, vertices=None, faces=None, caption=''):
        self.vertices = vertices or []
        self.faces = faces or []
        self.mesh = PreviewMesh(self.vertices, self.faces)
        self.textures, self.missing = {}, []
        self.caption = caption
        self.angle_x, self.angle_y, self.zoom = -0.38, 0.45, 1.0
        self.draw()

    def set_preview(self, preview, caption=''):
        self.mesh = preview.mesh
        self.vertices, self.faces = self.mesh.vertices, self.mesh.faces
        self.textures, self.missing = preview.textures, preview.missing
        self.caption = caption
        self.angle_x, self.angle_y, self.zoom = -0.38, 0.45, 1.0
        self.draw()

    def set_textured(self, enabled):
        self.textured = enabled
        self.texture_button.set_selected(enabled)
        self.solid_button.set_selected(not enabled)
        self.draw()

    def start_drag(self, ev): self.last = ev.x, ev.y

    def drag(self, ev):
        if not self.last or not self.vertices: return
        dx, dy = ev.x - self.last[0], ev.y - self.last[1]
        self.angle_y += dx * 0.012
        self.angle_x += dy * 0.012
        self.last = ev.x, ev.y
        self.request_draw(preview=True)

    def wheel(self, ev): self.change_zoom(1.12 if ev.delta > 0 else 1/1.12)

    def change_zoom(self, factor):
        if not self.vertices: return
        self.zoom = min(15, max(0.12, self.zoom * factor))
        self.request_draw(preview=True)
        if self._quality_after is not None:self.after_cancel(self._quality_after)
        self._quality_after = self.after(120, self.request_draw)

    def request_draw(self, preview=False):
        self._preview_requested = preview
        if not preview and self._quality_after is not None:
            self.after_cancel(self._quality_after)
            self._quality_after = None
        if self._draw_after is None:
            self._draw_after = self.after_idle(self._draw_requested)

    def _draw_requested(self):
        self._draw_after = None
        self.draw(preview=self._preview_requested)

    def _cancel_draws(self, event=None):
        if event is not None and event.widget is not self:return
        for attribute in ('_draw_after', '_quality_after'):
            callback = getattr(self, attribute)
            if callback is not None:self.after_cancel(callback)
            setattr(self, attribute, None)

    def draw(self, preview=False):
        if self._draw_after is not None:
            self.after_cancel(self._draw_after)
            self._draw_after = None
        self.delete('all')
        self.image = None
        w, h = max(self.winfo_width(), 100), max(self.winfo_height(), 100)
        self.create_text(12, 25, anchor='w', text=tr('viewer.title'), fill='#909bab', font=('Arial', 10, 'bold'))
        self.create_window(w-9, 7, anchor='ne', window=self.toolbar)
        if not self.vertices:
            self.create_text(w/2, h/2, text=self.caption or tr('viewer.not_found'), fill='#bdc6d5',
                             font=('Arial', 11), width=max(w-30, 80), justify='center')
            return
        # Huge models are not the target of the potion viewer.
        if len(self.faces) > 15000:
            self.create_text(w/2,h/2,text=tr('viewer.too_complex'),fill='white')
            return
        width, height = max(1,w-20), max(1,h-110)
        # Keep rotation responsive; render at native resolution once dragging ends.
        factor = max(1, (max(width,height)+479)//480) if preview else 1
        rw, rh = max(1,width//factor), max(1,height//factor)
        pixels = render_mesh(self.mesh,self.textures,rw,rh,self.angle_x,self.angle_y,self.zoom,self.textured)
        ppm = f'P6\n{rw} {rh}\n255\n'.encode('ascii') + pixels
        self.image = tk.PhotoImage(master=self, data=ppm, format='PPM')
        if factor > 1:self.image = self.image.zoom(factor)
        self.create_image(w/2, 55+height/2, image=self.image)
        if self.textured and self.missing:
            self.create_text(w/2,h-44,text=tr('viewer.missing_textures',count=len(self.missing)),
                             fill='#909bab',font=('Arial',9))
        self.create_text(w/2, h-20, text=tr('viewer.controls'), fill='#94a3b8', font=('Arial', 9))


