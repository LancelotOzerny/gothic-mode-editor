"""Function selections and argument controls in the existing Parameters group."""
import json
import tkinter as tk
from .choice_list import ChoiceList
from .inputs import PropertyEntry
from .field_label import FieldLabel
from .theme import PANEL, ERROR, label
from gothic_editor.core.item_actions import assignments,argument_literal


class FunctionActionList(ChoiceList):
    # Retain the former five-row format; only adding new rows uses max_rows.
    allow_existing_overflow=True
    def __init__(self,parent,field,value,provider,catalog_provider,editable=True):
        self.catalog_provider=catalog_provider
        self.arguments={}
        self._pending=[]
        self._previous={}
        self.parameter_holder=None
        self._parameter_key=None
        self._updating=False
        super().__init__(parent,field,value,provider,editable)

    def set_expression(self,value):
        rows=assignments(value) if value else [{'id':'','values':{}}]
        for row in rows:
            if row['id'] and '#' not in row['id']:
                try:row['id']=self.catalog_provider().resolve(row['id']).identifier
                except (OSError,ValueError):pass
        self._pending=[row['values'] for row in rows]
        self.arguments={}
        self._previous={}
        self._parameter_key=None
        super().set_expression(json.dumps([row['id'] for row in rows]))

    def _append(self,value):
        super()._append(value)
        frame,entry=self.rows[-1]
        self.arguments[frame]=self._pending.pop(0) if self._pending else {}
        self._previous[frame]=value

    def attach_parameters(self,parent):
        if self.parameter_holder is None:
            self.parameter_holder=tk.Frame(parent,bg=PANEL)
            self.parameter_holder.pack(fill='x')
        self._parameter_key=None
        self._sync()

    def _sync(self):
        if self._updating:return
        self._updating=True
        try:
            for frame,entry in self.rows:
                if self._previous.get(frame)!=entry.get():self.arguments[frame]={}
                self._previous[frame]=entry.get()
            self._render_parameters()
            self.value_variable.set(json.dumps([{'id':entry.get(),'values':dict(self.arguments.get(frame,{}))}
                                                for frame,entry in self.rows],ensure_ascii=False))
            self.add_button.config(state='normal' if self.editable and len(self.rows)<self.field.max_rows else 'disabled')
        finally:self._updating=False

    def _render_parameters(self):
        if self.parameter_holder is None:return
        key=tuple((str(frame),entry.get()) for frame,entry in self.rows)
        if key==self._parameter_key:return
        self._parameter_key=key
        for child in self.parameter_holder.winfo_children():child.destroy()
        for frame,entry in self.rows:
            if not entry.get():continue
            try:function=self.catalog_provider().resolve(entry.get())
            except (OSError,ValueError) as exc:
                label(self.parameter_holder,str(exc),fg=ERROR,wraplength=260,justify='left').pack(fill='x')
                continue
            values=self.arguments.setdefault(frame,{})
            for parameter in function.parameters:
                values.setdefault(parameter.name,parameter.default)
                FieldLabel(self.parameter_holder,f'[{function.label}] {parameter.label}').pack(fill='x',padx=8,pady=(6,2))
                variable=tk.StringVar(self,value=values[parameter.name])
                field=PropertyEntry(self.parameter_holder,textvariable=variable,state='normal' if self.editable else 'readonly')
                field.pack(fill='x',padx=8,pady=(0,4))
                def change(*_,v=variable,values=values,name=parameter.name):
                    values[name]=v.get()
                    self._sync()
                trace=variable.trace_add('write',change)
                field.bind('<Destroy>',lambda _,v=variable,t=trace:v.trace_remove('write',t),add='+')

    def validate(self):
        for index,(frame,entry) in enumerate(self.rows,1):
            if not entry.get():continue
            function=self.catalog_provider().resolve(entry.get())
            for parameter in function.parameters:
                try:argument_literal(parameter,self.arguments.get(frame,{}).get(parameter.name,parameter.default))
                except ValueError as exc:raise ValueError(f'Действие {index}, [{function.label}] {parameter.label}: {exc}') from exc

    def remove_row(self,frame):
        if not self.editable:return
        super().remove_row(frame)
        self.arguments.pop(frame,None)
        self._previous.pop(frame,None)
