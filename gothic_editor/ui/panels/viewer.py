import tkinter as tk
from collections import OrderedDict
from gothic_editor.core.localization import tr
from gothic_editor.core.mesh import PreviewMesh
from gothic_editor.ui.controllers.preview_renderer import PreviewRenderer
from gothic_editor.ui.widgets.buttons import PropertyButton
from gothic_editor.core.inventory_preview import inventory_mesh

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
        self.textured = False
        self.on_texture_mode = None
        self.inventory_rotation = None
        self.inventory_locked = False
        self._free_camera = None
        self._inventory_mesh = None
        self.inventory_error = ''
        self.image = None
        self._scene_revision = 0
        self._frames = OrderedDict()
        self._wanted_key = None
        self.renderer = PreviewRenderer(self,self._frame_ready,self._frame_error)
        self._draw_after = None
        self._quality_after = None
        self._preview_requested = False
        self.toolbar = tk.Frame(self, bg='#191e29')
        self.texture_button = PropertyButton(self.toolbar, lambda:self.set_textured(not self.textured),
            text='Т', filename='viewer_textured.png', caption=tr('viewer.textured'))
        self.inventory_button = PropertyButton(self.toolbar, lambda:self.set_inventory(not self.inventory_locked),
            text='И', filename='viewer_inventory.png', caption='Ракурс инвентаря')
        self.inventory_button.config(state='disabled')
        for button in (self.texture_button, self.inventory_button):
            button.configure(bg='#191e29')
            button.pack(side='left', padx=3)
        self.bind('<Configure>', lambda _: self.request_draw())
        self.bind('<ButtonPress-1>', self.start_drag)
        self.bind('<B1-Motion>', self.drag)
        self.bind('<ButtonRelease-1>', lambda _: self.request_draw())
        self.bind('<Destroy>', self._cancel_draws, add='+')
        self.bind('<MouseWheel>', self.wheel)
        self.bind('<Button-4>', lambda _: self.change_zoom(1.12))
        self.bind('<Button-5>', lambda _: self.change_zoom(1/1.12))

    def set_mesh(self, vertices=None, faces=None, caption=''):
        self._invalidate_scene()
        self.vertices = vertices or []
        self.faces = faces or []
        self.mesh = PreviewMesh(self.vertices, self.faces)
        self.textures, self.missing = {}, []
        self.caption = caption
        self.angle_x, self.angle_y, self.zoom = -0.38, 0.45, 1.0
        self.draw()

    def set_preview(self, preview, caption='', camera=None):
        self._invalidate_scene(preview.render_token)
        self.mesh = preview.mesh
        self.vertices, self.faces = self.mesh.vertices, self.mesh.faces
        self.textures, self.missing = preview.textures, preview.missing
        self.caption = caption
        self.angle_x, self.angle_y, self.zoom = camera or (-0.38, 0.45, 1.0)
        if self.inventory_locked:self.update_inventory()
        self.draw()

    def set_textured(self, enabled):
        self.textured = enabled
        self.texture_button.set_selected(enabled)
        if self.on_texture_mode is not None:self.on_texture_mode()
        self.draw()

    def set_inventory_source(self,resolver):
        self.inventory_error=''
        self.inventory_rotation=resolver
        self.inventory_button.config(state='normal' if resolver else 'disabled')
        if resolver is None:self.set_inventory(False)
        elif self.inventory_locked:self.update_inventory()

    def update_inventory(self):
        try:self._inventory_mesh=inventory_mesh(self.mesh,self.inventory_rotation())
        except ValueError as exc:
            self.set_inventory(False)
            self.inventory_error=str(exc)
            return
        self._invalidate_scene()
        self.angle_x,self.angle_y,self.zoom=0.,0.,1.
        self.request_draw()

    def set_inventory(self,enabled):
        if enabled and self.inventory_rotation is None:return
        if enabled==self.inventory_locked:return
        self.inventory_locked=enabled
        self.inventory_button.set_selected(enabled)
        if enabled:
            self._free_camera=(self.angle_x,self.angle_y,self.zoom)
            self.update_inventory()
        else:
            if self._free_camera:self.angle_x,self.angle_y,self.zoom=self._free_camera
            self._invalidate_scene()
            self.request_draw()

    def _invalidate_scene(self,token=None):
        self._scene_revision = token if token is not None else object()
        self._wanted_key = None
        self.image = None
        self.delete('model')
        self.renderer.discard_requested()

    def start_drag(self, ev): self.last = ev.x, ev.y

    def drag(self, ev):
        if self.inventory_locked or not self.last or not self.vertices: return
        dx, dy = ev.x - self.last[0], ev.y - self.last[1]
        self.angle_y += dx * 0.012
        self.angle_x += dy * 0.012
        self.last = ev.x, ev.y
        self.request_draw(preview=True)

    def wheel(self, ev): self.change_zoom(1.12 if ev.delta > 0 else 1/1.12)

    def change_zoom(self, factor):
        if self.inventory_locked or not self.vertices: return
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
        self.renderer.close()

    def draw(self, preview=False):
        if self._draw_after is not None:
            self.after_cancel(self._draw_after)
            self._draw_after = None
        self.delete('chrome')
        w, h = max(self.winfo_width(), 100), max(self.winfo_height(), 100)
        self.create_text(12, 25, anchor='w', text=tr('viewer.title'), fill='#909bab', font=('Arial', 10, 'bold'),tags='chrome')
        self.create_window(w-9, 7, anchor='ne', window=self.toolbar,tags='chrome')
        if not self.vertices:
            self.create_text(w/2, h/2, text=self.caption or tr('viewer.not_found'), fill='#bdc6d5',
                             font=('Arial', 11), width=max(w-30, 80), justify='center',tags='chrome')
            return
        # Huge models are not the target of the potion viewer.
        if len(self.faces) > 15000:
            self.create_text(w/2,h/2,text=tr('viewer.too_complex'),fill='white',tags='chrome')
            return
        width, height = max(1,w-20), max(1,h-110)
        # Keep rotation responsive; render at native resolution once dragging ends.
        factor = max(2, (max(width,height)+319)//320) if preview else 1
        rw, rh = max(1,width//factor), max(1,height//factor)
        key=(self._scene_revision,w,h,self.angle_x,self.angle_y,self.zoom,self.textured,factor)
        self._wanted_key=key
        if key in self._frames:
            self.renderer.discard_requested()
            self._present(key)
        else:
            self.renderer.request(key,self._inventory_mesh if self.inventory_locked else self.mesh,self.textures,
                                  (rw,rh,self.angle_x,self.angle_y,self.zoom,self.textured))
        if self.textured and self.missing:
            self.create_text(w/2,h-44,text=tr('viewer.missing_textures',count=len(self.missing)),
                             fill='#909bab',font=('Arial',9),tags='chrome')
        if self.inventory_error:
            self.create_text(w/2,h-65,text=self.inventory_error,fill='#ef9a9a',width=w-30,tags='chrome')
        self.create_text(w/2, h-20, text='Ракурс инвентаря · вращение зафиксировано' if self.inventory_locked else tr('viewer.controls'), fill='#94a3b8', font=('Arial', 9),tags='chrome')

    def _frame_ready(self,key,ppm):
        wanted=self._wanted_key
        if wanted is None or key[0]!=self._scene_revision:return
        # Skip obsolete frames: decoding and upscaling them blocks Tk on the UI thread.
        if key!=wanted:return
        picture=tk.PhotoImage(master=self,data=ppm,format='PPM')
        self._frames[key]=picture.zoom(key[7]) if key[7]>1 else picture
        self._frames.move_to_end(key)
        while len(self._frames)>4:self._frames.popitem(last=False)
        if key[1:3]==wanted[1:3] and key[6]==wanted[6]:self._present(key)

    def _present(self,key):
        self.image=self._frames[key]
        self._frames.move_to_end(key)
        self.delete('model')
        self.create_image(key[1]/2,key[2]/2,image=self.image,tags='model')
        self.tag_lower('model')

    def _frame_error(self,key,error):
        if self._wanted_key is not None and key[0]==self._scene_revision:
            self.create_text(self.winfo_width()/2,self.winfo_height()/2,
                text=tr('messages.mesh_error',error=str(error)),fill='#bdc6d5',width=300,tags='chrome')


