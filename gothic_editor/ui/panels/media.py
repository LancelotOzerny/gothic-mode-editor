"""Media hierarchy and inspector following the editor's existing three-column layout."""
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from gothic_editor.core.game_media import CATEGORIES, GameMedia
from gothic_editor.core.textures import read_texture
from gothic_editor.ui.widgets import PANEL, BG, TXT, MUTED, label
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea, attach_scrollbar


class MediaPanel(Panel):
    def __init__(self, parent, on_select, on_load):
        super().__init__(parent)
        self.on_select, self.on_load = on_select, on_load
        label(self, 'Медиа', font=('Arial',10,'bold')).pack(fill='x', padx=12, pady=12)
        self.search=tk.StringVar(self)
        entry=tk.Entry(self,textvariable=self.search,bg=BG,fg=TXT,insertbackground=TXT)
        entry.pack(fill='x',padx=10,pady=(0,10))
        self.tree=ttk.Treeview(self,show='tree',selectmode='browse')
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
            ppm=f'P6\\n{width} {height}\\n255\\n'.encode('ascii')+rgb
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
