"""Field captions with optional, explicitly hovered help."""
import tkinter as tk
from tkinter import font as tkfont

from .theme import PANEL, MUTED, label
from .tooltip import Tooltip


class FieldLabel(tk.Frame):
    def __init__(self, parent, text, tooltip='', font=('Arial',9)):
        super().__init__(parent,bg=PANEL)
        self.label=label(self,text,fg=MUTED,anchor='w',font=font)
        self.label.pack(side='left')
        self.help_icon=None
        self.tooltip=None
        self.set_tooltip(tooltip)

    def set_text(self, text):
        self.label.configure(text=text)

    def set_tooltip(self, text):
        if not text.strip():
            if self.help_icon is not None:self.help_icon.destroy()
            self.help_icon=None
            self.tooltip=None
            return
        if self.tooltip is not None:
            if self.tooltip.text!=text:
                self.tooltip.hide()
                self.tooltip.text=text
            return
        font=tkfont.Font(root=self,font=self.label.cget('font'))
        size=font.metrics('linespace')
        self.help_icon=tk.Canvas(self,width=size,height=size,bg=PANEL,
                                 highlightthickness=0,bd=0,cursor='hand2')
        self.help_icon.create_oval(1,1,size-1,size-1,outline=MUTED)
        self.help_icon.create_text(size/2,size/2,text='?',fill=MUTED,font=self.label.cget('font'))
        self.help_icon.pack(side='left',padx=(5,0))
        self.tooltip=Tooltip(self.help_icon,text)
