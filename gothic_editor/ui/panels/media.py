"""Media hierarchy and inspector following the editor's existing three-column layout."""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from gothic_editor.core.game_media import CATEGORIES, GameMedia
from gothic_editor.core.textures import read_texture
from gothic_editor.ui.widgets import PANEL, BG, TXT, MUTED, label, make_entry
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea, attach_scrollbar


class MediaPanel(Panel):
    def __init__(self, parent, on_select, on_load):
        super().__init__(parent)
        self.on_select, self.on_load = on_select, on_load
        label(self, 'Медиа', font=('Arial',10,'bold')).pack(fill='x', padx=12, pady=12)
        self.search=tk.StringVar(self)
        make_entry(self,textvariable=self.search).pack(fill='x',padx=10,pady=(0,10),ipady=6)
        style=ttk.Style(self)
        style.configure('Media.Treeview',background=PANEL,fieldbackground=PANEL,
                        foreground=TXT,rowheight=27,borderwidth=0)
        style.map('Media.Treeview',background=[('selected','#36516c')],
                  foreground=[('selected',TXT)])
        self.tree=ttk.Treeview(self,show='tree',selectmode='browse',style='Media.Treeview')
        attach_scrollbar(self,self.tree)
        self.tree.pack(fill='both',expand=True)
        self.nodes={}
        self.resources={}
        for code,title in CATEGORIES.items():
            self.tree.insert('', 'end', iid=code,text=title,open=False)
        self.tree.bind('<<TreeviewSelect>>',self.selected)
        self.tree.bind('<Button-3>',self.context)
        self.search.trace_add('write',lambda *_:self.filter())

    def set_resources(self, resources, loaded):
        self.resources={row.kind+':'+row.name.casefold():row for row in resources
                        if row.category in loaded or row.overridden}
        self.filter()

    def filter(self):
        query=self.search.get().strip().casefold()
        selection=self.tree.selection()
        for code in CATEGORIES:
            for node in self.tree.get_children(code):self.tree.delete(node)
        self.nodes={}
        for key,row in self.resources.items():
            if query and query not in row.name.casefold():continue
            self.tree.insert(row.category,'end',iid=key,text=row.name+('  • Проект' if row.overridden else ''))
            self.nodes[key]=row
        if selection and self.tree.exists(selection[0]):self.tree.selection_set(selection[0])

    def expand(self,category):
        if self.tree.exists(category):
            self.tree.item(category,open=True)

    def selected(self,_event=None):
        selected=self.tree.selection()
        if selected and selected[0] in self.nodes:self.on_select(self.nodes[selected[0]])

    def context(self,event):
        node=self.tree.identify_row(event.y)
        if not node:return
        menu=tk.Menu(self,tearoff=False)
        category=node if node in CATEGORIES else self.tree.parent(node)
        if category in CATEGORIES:
            menu.add_command(label='Загрузить все файлы медиа',
                             command=lambda:self.on_load(category))
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()


class MediaPreview(Panel):
    """Reuse the editor's central viewport for the selected image."""
    def __init__(self,parent):
        super().__init__(parent,bg=BG)
        self.resource=None
        self.texture=None
        self.photo=None
        self.canvas=tk.Canvas(self,bg=BG,highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.canvas.bind('<Configure>',self.redraw)

    def show(self,resource):
        self.resource=resource
        self.texture=None
        self.photo=None
        if resource is not None and resource.kind=='images':
            try:self.texture=read_texture(resource.source.read_bytes())
            except (OSError,ValueError) as exc:
                self.caption='Ошибка чтения: '+str(exc)
            else:self.caption=''
        else:
            self.caption='Выберите изображение' if resource is None else 'Видео BIK: предпросмотр недоступен'
        self.redraw()

    def redraw(self,_event=None):
        self.canvas.delete('all')
        width=max(1,self.canvas.winfo_width())
        height=max(1,self.canvas.winfo_height())
        if self.texture is None:
            self.canvas.create_text(width//2,height//2,text=self.caption,
                                    fill=MUTED,font=('Arial',13),width=max(150,width-35))
            return
        texture=self.texture
        scale=max(1,(texture.width+width-31)//max(1,width-30),
                  (texture.height+height-31)//max(1,height-30))
        out_w=(texture.width+scale-1)//scale
        out_h=(texture.height+scale-1)//scale
        rgb=bytearray(out_w*out_h*3)
        pos=0
        for y in range(0,texture.height,scale):
            for x in range(0,texture.width,scale):
                offset=(y*texture.width+x)*4
                rgb[pos:pos+3]=texture.pixels[offset:offset+3]
                pos+=3
        ppm=f'P6\\n{out_w} {out_h}\\n255\\n'.encode('ascii')+rgb
        self.photo=tk.PhotoImage(master=self,data=ppm,format='PPM')
        self.canvas.create_image(width//2,height//2,image=self.photo)
        self.canvas.create_text(12,10,text=f'{texture.width} × {texture.height}',
                                anchor='nw',fill=MUTED,font=('Arial',10))


class MediaPropertiesPanel(Panel):
    def __init__(self,parent,app):
        super().__init__(parent)
        self.app=app
        self.current=None
        self.photo=None
        label(self,'Свойства медиа',font=('Arial',10,'bold')).pack(fill='x',padx=14,pady=(14,8))
        self.caption=label(self,'Выберите файл в иерархии',fg=MUTED,wraplength=280)
        self.caption.pack(fill='x',padx=14,pady=(0,14))
        self.area=ScrollableArea(self)
        self.area.pack(fill='both',expand=True)

    def show(self,resource):
        self.current=resource
        self.photo=None
        for child in self.area.content.winfo_children():child.destroy()
        self.caption.config(text=resource.name if resource else 'Выберите файл в иерархии')
        if resource is None:return
        group=self.add_group('Ресурс',parent=self.area.content)
        group.add_field('Название в Gothic',value=resource.name,readonly=True)
        group.add_field('Категория',value=CATEGORIES[resource.category],readonly=True)
        label(group.body,'Заменён в проекте' if resource.overridden else 'Оригинал Gothic',
              fg=MUTED).pack(fill='x',padx=8,pady=6)
        group.add_button('Заменить изображение' if resource.kind=='images' else 'Заменить видео BIK',
                         self.replace)
        if resource.overridden:group.add_button('Отменить замену',self.remove)
        if resource.kind=='videos':
            label(group.body,'Видео BIK. Предпросмотр видео пока недоступен.',
                  fg=MUTED,wraplength=280).pack(fill='x',padx=8,pady=8)
        else:
            self.preview_frame=self.add_group('Предпросмотр',parent=self.area.content)
            self.picture=label(self.preview_frame.body,'Загрузка изображения…',fg=MUTED)
            self.picture.pack(fill='x',padx=8,pady=8)
            self.after_idle(lambda current=resource:self.preview(current))

    def preview(self,resource):
        if self.current!=resource or not self.picture.winfo_exists():return
        try:
            source=resource.source
            data=source.read_bytes()
            texture=read_texture(data)
            factor=max(1,(max(texture.width,texture.height)+279)//280)
            width=(texture.width+factor-1)//factor
            height=(texture.height+factor-1)//factor
            rgb=bytearray()
            for y in range(0,texture.height,factor):
                for x in range(0,texture.width,factor):
                    offset=(y*texture.width+x)*4
                    rgb.extend(texture.pixels[offset:offset+3])
            ppm=f'P6\n{width} {height}\n255\n'.encode('ascii')+rgb
            self.photo=tk.PhotoImage(master=self,data=ppm,format='PPM')
            self.picture.configure(image=self.photo,text='')
        except (OSError,ValueError,tk.TclError) as exc:
            self.picture.configure(text='Нет предпросмотра: '+str(exc),image='')

    def replace(self):
        row=self.current
        if row is None:return
        media=GameMedia(self.app.repo.root)
        filters=[('Изображения','*.png *.jpg *.jpeg *.tga *.tex')] if row.kind=='images' else [('Видео BIK','*.bik')]
        source=filedialog.askopenfilename(parent=self,title='Выберите замену для '+row.name,filetypes=filters)
        if not source:return
        try:
            target=media.path(row.kind,row.name)
            saved=self.app.history.capture((target,))
            if row.kind=='images':media.replace_image(row.name,source)
            else:media.import_file('videos',row.name,source)
            self.app.history.record(saved)
            self.app.load_media(keep=True)
        except (OSError,ValueError) as exc:
            messagebox.showerror('Медиа',str(exc),parent=self)

    def remove(self):
        row=self.current
        if row is None:return
        media=GameMedia(self.app.repo.root)
        target=media.path(row.kind,row.name)
        try:
            saved=self.app.history.capture((target,))
            media.delete(row.kind,row.name)
            self.app.history.record(saved)
            self.app.load_media(keep=True)
        except (OSError,ValueError) as exc:
            messagebox.showerror('Медиа',str(exc),parent=self)
