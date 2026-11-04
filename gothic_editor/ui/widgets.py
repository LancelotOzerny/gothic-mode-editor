"""Shared theme and input interaction."""
import tkinter as tk
from ..core.localization import tr
from tkinter import ttk
BG='#202735';PANEL='#2b3545';INPUT='#1d2532';TXT='#e8edf6';MUTED='#98a7bd';ACCENT='#80b4f9';BORDER='#3b4758'

def label(parent,text='',**kw):
    return tk.Label(parent,text=text,bg=kw.pop('bg',PANEL),fg=kw.pop('fg',TXT),**kw)

def entry_menu(widget):
    menu=tk.Menu(widget,tearoff=False)
    for title,sequence in [(tr('widgets.cut'),'<<Cut>>'),(tr('widgets.copy'),'<<Copy>>'),(tr('widgets.paste'),'<<Paste>>'),(tr('widgets.select_all'),None)]:
        if sequence:menu.add_command(label=title,command=lambda s=sequence:widget.event_generate(s))
        else:menu.add_command(label=title,command=lambda:widget.select_range(0,'end') if isinstance(widget,tk.Entry) else widget.selection_range(0,'end'))
    def show(e):widget.focus_set();menu.tk_popup(e.x_root,e.y_root)
    widget.bind('<Button-3>',show,add='+')
    widget.bind('<Control-a>',lambda e:(widget.select_range(0,'end'),widget.icursor('end'),'break')[-1],add='+')
    return widget

def make_entry(parent,**kw):
    e=tk.Entry(parent,bg=INPUT,fg=TXT,insertbackground=TXT,relief='flat',highlightthickness=1,highlightbackground=BORDER,highlightcolor=ACCENT,**kw)
    entry_menu(e)
    return e
