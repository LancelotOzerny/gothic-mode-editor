"""Searchable grouped choices using the common dialog and dark widgets."""
import tkinter as tk
from tkinter import ttk
from .dialog import EditorDialog
from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets import PANEL, INPUT, TXT, make_entry
from gothic_editor.ui.widgets.panel import attach_scrollbar


class GroupedChoiceWindow(EditorDialog):
    def __init__(self, owner, groups, value, title, on_choose, on_cancel):
        super().__init__(owner,bg=PANEL)
        self.title(title)
        self.geometry('480x320')
        self.groups,self.value=groups,value
        self.on_choose,self.on_cancel=on_choose,on_cancel
        self.query=tk.StringVar(self)
        make_entry(self,textvariable=self.query).pack(fill='x',padx=12,pady=10)
        footer=tk.Frame(self,bg=PANEL)
        footer.pack(side='bottom',fill='x',padx=12,pady=10)
        self.add_button(footer,tr('settings.cancel'),on_cancel).pack(side='right')
        self.choose_button=self.add_button(footer,tr('settings.choose'),self.apply)
        self.choose_button.pack(side='right',padx=8)
        body=tk.Frame(self,bg=PANEL)
        body.pack(fill='both',expand=True,padx=12)
        style=ttk.Style(self)
        style.configure('GroupedChoice.Treeview',background=INPUT,fieldbackground=INPUT,
                        foreground=TXT,rowheight=30,borderwidth=0)
        style.layout('GroupedChoice.Treeview',[('Treeview.treearea',{'sticky':'nswe'})])
        style.map('GroupedChoice.Treeview',background=[('selected','#304a65')],foreground=[('selected',TXT)])
        self.tree=ttk.Treeview(body,show='tree',style='GroupedChoice.Treeview',selectmode='browse')
        attach_scrollbar(body,self.tree)
        self.tree.pack(fill='both',expand=True)
        self.tree.bind('<<TreeviewSelect>>',self.selected)
        self.tree.bind('<Double-Button-1>',lambda _:self.apply())
        self.bind('<Return>',lambda _:self.apply())
        self.bind('<Escape>',lambda _:on_cancel())
        self.protocol('WM_DELETE_WINDOW',on_cancel)
        self.query.trace_add('write',lambda *_:self.populate())
        self.populate()

    def populate(self):
        self.tree.delete(*self.tree.get_children())
        self.values={}
        none=self.tree.insert('','end',text=tr('item_actions.none'))
        self.values[none]=''
        selected=none if not self.value else None
        for title,options in self.groups:
            matches=[(name,value) for name,value in options if self.query.get().casefold() in name.casefold()]
            group=self.tree.insert('','end',text=title,open=True)
            for name,value in matches:
                node=self.tree.insert(group,'end',text=name)
                self.values[node]=value
                if value==self.value:selected=node
        if selected is not None:
            self.tree.selection_set(selected)
            self.tree.see(selected)
        self.selected()

    def selected(self,_event=None):
        selected=self.tree.selection()
        valid=selected and selected[0] in self.values
        if valid:self.value=self.values[selected[0]]
        self.choose_button.config(state='normal' if valid else 'disabled')

    def apply(self):
        selected=self.tree.selection()
        if selected and selected[0] in self.values:self.on_choose(self.values[selected[0]])

    def show(self):
        self.show_centered()
