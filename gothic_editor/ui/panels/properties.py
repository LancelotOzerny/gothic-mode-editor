"""Schema-driven property form with per-field project autosave."""
import tkinter as tk
import re
from gothic_editor.core.categories import classify, EDITABLE_CATEGORIES
from gothic_editor.core.localization import tr
from gothic_editor.core.properties_schema import PropertyField, property_key, schema_for
from gothic_editor.ui.widgets import PANEL, MUTED, BORDER, label
from gothic_editor.ui.widgets.choice_field import ExpressionChoiceField
from gothic_editor.ui.widgets.sections import PropertySectionFrame
from gothic_editor.ui.widgets.key_value_list import KeyValueList
from gothic_editor.ui.widgets.placeholders import add_placeholder
from gothic_editor.ui.widgets.inputs import PropertyEntry
from gothic_editor.ui.widgets.field_label import FieldLabel

from gothic_editor.ui.controllers.property_editor import PropertyEditor

class PropertiesPanel(tk.Frame):
    def __init__(self,parent,on_save,on_appearance=None,options_provider=None):
        super().__init__(parent,bg=PANEL)
        self.on_save=on_save;self.current=None;self.inputs={}
        self.on_appearance=on_appearance
        self.options_provider=options_provider
        self.fields={};self.initial={};self.editable=False
        self.collapsed={}
        self.sections={}
        self._generation=0
        self.editor=PropertyEditor(self)
        label(self,tr('properties.title'),font=('Arial',10,'bold')).pack(fill='x',padx=14,pady=(14,0))
        self.info=label(self,tr('properties.select_item'),fg=MUTED,anchor='center',wraplength=280,justify='center')
        self.info.pack(fill='x',padx=14,pady=(4,0))
        separator=tk.Frame(self,bg=PANEL,height=1)
        separator.pack(fill='x',pady=(10,20))
        tk.Frame(separator,bg=BORDER).place(relx=.05,relwidth=.9,relheight=1)
        self.canvas=tk.Canvas(self,bg=PANEL,highlightthickness=0)
        scroll=tk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        scroll.pack(side='right',fill='y')
        self.canvas.pack(side='top',fill='both',expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.inner=tk.Frame(self.canvas,bg=PANEL)
        self.window=self.canvas.create_window((0,0),window=self.inner,anchor='nw')
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.window,width=e.width))
        self.inner.bind('<Configure>',lambda _:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-int(e.delta/120),'units'))
        self.show(None)

    def show(self,item):
        self._generation+=1
        self.current=item
        for child in self.inner.winfo_children():child.destroy()
        self.inputs={}
        self.fields={};self.initial={};self.editable=False
        self.sections={}
        if item is None:
            self.info.config(text=tr('properties.select_in_hierarchy'))
            return
        self.editable=classify(item) in EDITABLE_CATEGORIES and item.origin=='project'
        self.info.config(text=item.instance)
        try:
            schema=schema_for(classify(item))
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.editable=False
            self.info.config(text=tr('properties.schema_error',error=str(exc)))
            return
        if schema is None:
            label(self.inner,tr('properties.readonly'),fg=MUTED,wraplength=260).pack(fill='x',padx=13,pady=8)
            for key in sorted(item.fields):self.render_field(self.inner,PropertyField(key,key),item.fields[key])
        else:
            known={property_key(field.key) for section in schema.sections for field in section.fields
                   if field.source=='property'}
            for section in schema.sections:
                frame=PropertySectionFrame(self.inner,section.title,self.collapsed.get(section.key,False),
                    lambda closed,key=section.key:self.collapsed.__setitem__(key,closed))
                self.sections[section.key]=frame
                frame.pack(fill='x',pady=(0,30))
                if section.description:
                    label(frame.body,section.description,fg=MUTED,wraplength=250,justify='left').pack(fill='x',padx=8,pady=5)
                for field in section.fields:
                    if field.source=='instance_id':
                        value=item.instance
                        if field.prefix and value.casefold().startswith(field.prefix.casefold()):
                            value=value[len(field.prefix):]
                    elif field.source=='editor_metadata':value=item.editor_metadata.get(field.key,'')
                    else:
                        key=property_key(field.key)
                        if not schema.show_missing and key not in item.fields and field.field_type!='key_value_list':continue
                        value=item.fields if field.field_type=='key_value_list' else item.fields.get(key,'')
                    self.render_field(frame.body,field,value)
                if section.key==schema.unknown_section:
                    for key in sorted(item.fields):
                        if property_key(key) not in known:
                            self.render_field(frame.body,PropertyField(key,key),item.fields[key])
        if self.on_appearance is not None and classify(item)=='potions':
            self.on_appearance(self.inner,item)
        self.canvas.yview_moveto(0)

    def render_field(self,parent,field,value):
        generation=self._generation
        commit=lambda *_:self.commit_field(field.key,generation)
        if field.field_type=='key_value_list':
            if field.tooltip:
                FieldLabel(parent,field.label,field.tooltip).pack(fill='x',padx=8,pady=(6,2))
            entry=KeyValueList(parent,field,value,self.editable,on_commit=commit)
            entry.pack(fill='x',padx=8)
            self.inputs[field.key]=entry
            self.fields[field.key]=field
            self.initial[field.key]=entry.get()
            return
        if field.field_type=='string' and re.fullmatch(r'"(?:\\.|[^"\\])*"',value):
            value=re.sub(r'\\([\\"])',r'\1',value[1:-1])
        FieldLabel(parent,field.label,field.tooltip).pack(fill='x',padx=8,pady=(6,2))
        variable=tk.StringVar(self)
        if field.widget=='combobox':
            options=list(field.options)
            if field.options_source and self.options_provider:
                provided=list(self.options_provider(field.options_source))
                if field.options_source=='item_schemes':options=provided
                else:
                    for option in provided:
                        if option[1] not in {value for _,value in options}:options.append(option)
            entry=ExpressionChoiceField(parent,options,textvariable=variable,state='readonly',caption=field.label)
            entry.set_expression(value)
            if not self.editable:entry.config(state='disabled')
        else:
            entry=PropertyEntry(parent,textvariable=variable)
            entry.insert(0,value)
            if not self.editable:entry.config(state='readonly')
        entry.pack(fill='x',padx=8,ipady=5)
        entry.value_variable=variable
        entry.bind('<FocusOut>',commit,add='+')
        add_placeholder(entry,variable,field.placeholder)
        self.inputs[field.key]=entry
        self.fields[field.key]=field
        self.initial[field.key]=value

    def commit_field(self,key,generation):
        if generation!=self._generation:return
        entry=self.inputs.get(key)
        if isinstance(entry,ExpressionChoiceField) and entry.selection_window is not None:return
        self.save(keys=(key,),automatic=True)

    def save(self,keys=None,automatic=False):
        return self.editor.save(keys,automatic)
