"""A schema-limited single-column list of choices, stored as editor metadata."""
import json
import tkinter as tk
from tkinter import messagebox
from .theme import COMPACT_FIELD_HEIGHT, COMPACT_FIELD_PADDING, FIELD_HEIGHT, PANEL
from .buttons import PropertyButton
from .choice_field import ExpressionChoiceField
from gothic_editor.core.localization import tr
from gothic_editor.ui.windows.grouped_choice import GroupedChoiceWindow


class GroupedChoiceField(ExpressionChoiceField):
    def __init__(self,parent,provider,**kwargs):
        self.provider=provider
        super().__init__(parent,(),**kwargs)
        self.refresh_options()

    def refresh_options(self):
        self.options_error=''
        try:self.groups=self.provider()
        except (OSError,ValueError) as exc:
            self.groups=[]
            self.options_error=str(exc)
        self.options=((tr('item_actions.none'),''),)+tuple((title+' / '+name,value)
                     for title,options in self.groups for name,value in options)

    def open_choices(self,event=None):
        if self.cget('state')=='disabled':return 'break'
        if self.selection_window is not None:
            self.selection_window.lift()
            return 'break'
        value=self.get()
        self.refresh_options()
        if self.options_error:
            messagebox.showerror(self.caption,self.options_error,parent=self.owner)
            return 'break'
        self.set_expression(value)
        def accept(value):
            self.set_expression(value)
            self.close_choices()
        self.selection_window=GroupedChoiceWindow(self.owner,self.groups,value,self.caption,accept,self.close_choices)
        self.selection_window.bind('<Destroy>',self.dialog_destroyed,add='+')
        self.selection_window.show()
        return 'break'


class ChoiceList(tk.Frame):
    allow_existing_overflow=False
    def __init__(self,parent,field,value,provider,editable=True,*,height=FIELD_HEIGHT):
        super().__init__(parent,bg=PANEL)
        self.field,self.provider,self.editable=field,provider,editable
        self.rows=[]
        self.height=height
        self.value_variable=tk.StringVar(self)
        footer=tk.Frame(self,bg=PANEL)
        footer.pack(side='bottom',fill='x',pady=1 if height == COMPACT_FIELD_HEIGHT else 5)
        self.add_button=PropertyButton(footer,self.add_row,text='+',filename='create.png',
                                       caption=tr('item_actions.add'),height=height)
        self.add_button.pack(side='right')
        self.set_expression(value)

    def set_expression(self,value):
        rows=json.loads(value) if value else ['']
        if (not isinstance(rows,list) or (len(rows)>self.field.max_rows and not self.allow_existing_overflow)
                or any(not isinstance(row,str) for row in rows)):
            raise ValueError(tr('item_actions.invalid'))
        for frame,_ in self.rows:frame.destroy()
        self.rows=[]
        for row in rows:self._append(row)
        self._sync()

    def _append(self,value):
        frame=tk.Frame(self,bg=PANEL)
        frame.pack(fill='x',pady=COMPACT_FIELD_PADDING if self.height == COMPACT_FIELD_HEIGHT else 2)
        frame.columnconfigure(0,weight=1)
        entry=GroupedChoiceField(frame,self.provider,state='readonly' if self.editable else 'disabled',
                                 caption=self.field.label,height=None if self.height == COMPACT_FIELD_HEIGHT else self.height)
        entry.set_expression(value)
        entry.grid(row=0,column=0,sticky='ew')
        remove=PropertyButton(frame,lambda:self.remove_row(frame),text='×',filename='remove_recent.png',
                              caption=tr('resources.delete'),height=self.height)
        remove.grid(row=0,column=1,padx=(4,0))
        if not self.editable:remove.config(state='disabled')
        self.rows.append((frame,entry))
        trace=entry.variable.trace_add('write',lambda *_:self._sync())
        entry.bind('<Destroy>',lambda _,v=entry.variable,t=trace:v.trace_remove('write',t),add='+')

    def _sync(self):
        self.value_variable.set(json.dumps([entry.get() for _,entry in self.rows],ensure_ascii=False))
        self.add_button.config(state='normal' if self.editable and len(self.rows)<self.field.max_rows else 'disabled')

    def get(self):return self.value_variable.get()

    def add_row(self):
        if self.editable and len(self.rows)<self.field.max_rows:
            self._append('')
            self._sync()

    def remove_row(self,frame):
        if not self.editable:return
        self.rows=[row for row in self.rows if row[0]!=frame]
        frame.destroy()
        self._sync()
