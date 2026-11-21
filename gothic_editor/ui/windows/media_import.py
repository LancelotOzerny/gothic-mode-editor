"""Searchable Gothic media picker with preview before adding to project."""
import tkinter as tk
from tkinter import ttk
from gothic_editor.core.textures import read_texture
from gothic_editor.ui.windows.dialog import EditorDialog
from gothic_editor.ui.widgets.theme import BG,PANEL,TXT,MUTED
from gothic_editor.ui.widgets import make_entry,label


class MediaImportWindow(EditorDialog):
    def __init__(self,parent,resources,on_choose):
        super().__init__(parent)
        self.title('Импорт медиа из Gothic')
        self.geometry('850x530')
        self.resources=list(resources)
        self.on_choose=on_choose
        self.query=tk.StringVar(self)
        self.query.trace_add('write',lambda *_:self.filter())
        label(self,'Поиск по названию оригинального ресурса',bg=BG).pack(
            fill='x',padx=16,pady=(12,4))
        make_entry(self,textvariable=self.query).pack(fill='x',padx=16,pady=(0,12),ipady=6)
        body=tk.Frame(self,bg=BG)
        body.pack(fill='both',expand=True,padx=16)
        left=tk.Frame(body,bg=PANEL)
        left.pack(side='left',fill='both',expand=True)
        self.items=tk.Listbox(left,bg=PANEL,fg=TXT,selectbackground='#3a4d66',
                              highlightthickness=0,relief='flat',exportselection=False)
        self.items.pack(fill='both',expand=True,padx=5,pady=5)
        self.items.bind('<<ListboxSelect>>',self.preview)
        self.items.bind('<Double-1>',lambda _:self.choose())
        right=tk.Frame(body,bg=BG,width=320)
        right.pack(side='left',fill='both',expand=True,padx=(12,0))
        self.canvas=tk.Canvas(right,bg=PANEL,highlightthickness=0)
        self.canvas.pack(fill='both',expand=True)
        self.picture=None
        self.caption=label(right,'Выберите медиа для предпросмотра',bg=BG,fg=MUTED,
                           wraplength=300)
        self.caption.pack(fill='x',pady=8)
        controls=tk.Frame(self,bg=BG)
        controls.pack(fill='x',padx=16,pady=12)
        tk.Button(controls,text='Импортировать выбранное',command=self.choose).pack(side='left')
        tk.Button(controls,text='Отмена',command=self.destroy).pack(side='right')
        self.bind('<Escape>',lambda _:self.destroy())
        self.filter()

    def filter(self):
        query=self.query.get().strip().casefold()
        self.filtered=[r for r in self.resources if query in r.name.casefold()]
        self.items.delete(0,'end')
        for row in self.filtered:self.items.insert('end',row.name)
        self.canvas.delete('all')
        self.picture=None
        self.caption.config(text=f'Найдено: {len(self.filtered)}. Выберите ресурс.')

    def preview(self,_event=None):
        selected=self.items.curselection()
        if not selected:return
        row=self.filtered[selected[0]]
        self.canvas.delete('all')
        self.picture=None
        self.caption.config(text=row.name)
        if row.kind=='videos':
            self.canvas.create_text(150,170,text='Видео BIK',fill=TXT)
            return
        try:
            texture=read_texture(row.source.read_bytes())
            scale=max(1,(max(texture.width,texture.height)+299)//300)
            width=(texture.width+scale-1)//scale
            height=(texture.height+scale-1)//scale
            pixels=bytearray()
            for y in range(0,texture.height,scale):
                for x in range(0,texture.width,scale):
                    offset=(y*texture.width+x)*4
                    pixels.extend(texture.pixels[offset:offset+3])
            ppm=f'P6\\n{width} {height}\\n255\\n'.encode('ascii')+pixels
            self.picture=tk.PhotoImage(master=self,data=ppm,format='PPM')
            self.canvas.create_image(155,170,image=self.picture)
            self.caption.config(text=f'{row.name} • {texture.width} × {texture.height}')
        except (OSError,ValueError,tk.TclError) as exc:
            self.caption.config(text=str(exc))

    def choose(self):
        selected=self.items.curselection()
        if selected:self.on_choose(self.filtered[selected[0]])
