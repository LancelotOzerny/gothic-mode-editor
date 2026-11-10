"""Selectable file tile using the shared button colors and optional asset icon."""
import tkinter as tk
from .theme import PANEL, INPUT, HOVER_BG, TXT, MUTED, ACCENT, BORDER, rounded_box
from .icons import IconImages
from .tooltip import Tooltip


class FileTile(tk.Canvas):
    def __init__(self,parent,path,caption,on_select,on_open,on_context):
        super().__init__(parent,width=112,height=110,bg=PANEL,bd=0,highlightthickness=0,
                         cursor='hand2',takefocus=True)
        self.path,self.caption=path,caption
        self.selected=self.hovered=False
        self.icons=IconImages.shared(self)
        self.image=None
        self.bind('<Enter>',lambda _:self.hover(True))
        self.bind('<Leave>',lambda _:self.hover(False))
        self.bind('<Button-1>',lambda _:(self.focus_set(),on_select(path)))
        self.bind('<Double-Button-1>',lambda _:(on_select(path),on_open()))
        self.bind('<Return>',lambda _:(on_select(path),on_open()))
        self.bind('<Button-3>',lambda event:(self.focus_set(),on_select(path),on_context(event)))
        self.bind('<Configure>',lambda _:self.paint())
        Tooltip(self,caption)
        self.paint()

    def hover(self,value):
        self.hovered=value
        self.paint()

    def set_selected(self,value):
        self.selected=value
        self.paint()

    def paint(self):
        self.delete('all')
        width=max(112,self.winfo_width())
        fill='#304a65' if self.selected else HOVER_BG if self.hovered else INPUT
        rounded_box(self,width,110,fill,ACCENT if self.selected else BORDER)
        self.image=None
        directory=self.path.is_dir()
        icon='folder.png' if directory else 'file.png'
        if (self.icons.directory/icon).is_file():
            try:self.image=self.icons.frames(icon,54,MUTED,fill)[0]
            except (OSError,tk.TclError):pass
        if self.image:self.create_image(width/2,36,image=self.image)
        if directory and self.image is None:
            self.create_polygon(width/2-25,20,width/2-7,20,width/2-2,26,width/2+25,26,
                                width/2+25,55,width/2-25,55,fill=MUTED,outline='')
        suffix='' if directory else self.path.suffix.lstrip('.')
        self.create_text(width/2,38,text='D' if suffix.lower()=='d' else suffix.lower(),
                         font=('Arial',16,'bold'),fill=TXT)
        self.create_text(width/2,87,text=self.caption,width=width-10,font=('Arial',9),fill=TXT)
