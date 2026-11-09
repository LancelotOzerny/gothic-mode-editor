"""Schema-driven property form with per-field project autosave."""
import tkinter as tk
import re
from gothic_editor.core.categories import classify, EDITABLE_CATEGORIES
from gothic_editor.core.localization import tr
from gothic_editor.core.properties_schema import PropertyField, property_key, schema_for
from gothic_editor.ui.widgets import PANEL, MUTED, BORDER, label
from gothic_editor.ui.widgets.choice_field import ExpressionChoiceField
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea
from gothic_editor.ui.widgets.form import create_field
from gothic_editor.ui.widgets.key_value_list import KeyValueList
from gothic_editor.ui.widgets.placeholders import add_placeholder
from gothic_editor.ui.widgets.field_label import FieldLabel

from gothic_editor.ui.controllers.property_editor import PropertyEditor

class PropertiesPanel(Panel):
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
        self.scroll_area=ScrollableArea(self)
        self.scroll_area.pack(fill='both',expand=True)
        self.canvas,self.inner,self.window=self.scroll_area.canvas,self.scroll_area.content,self.scroll_area.window
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
                frame=self.add_group(section.title,self.collapsed.get(section.key,False),
                    lambda closed,key=section.key:self.collapsed.__setitem__(key,closed),parent=self.inner)
                self.sections[section.key]=frame
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
        if self.on_appearance is not None and classify(item) in EDITABLE_CATEGORIES and 'appearance' in self.sections:
            self.on_appearance(self.sections['appearance'].body,item)
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
        if field.field_type in ('string','resource') and re.fullmatch(r'"(?:\\.|[^"\\])*"',value):
            value=re.sub(r'\\([\\"])',r'\1',value[1:-1])
        FieldLabel(parent,field.label,field.tooltip).pack(fill='x',padx=8,pady=(6,2))
        variable=tk.StringVar(self,value=value)
        if field.widget=='combobox':
            options=list(field.options)
            if field.options_source and self.options_provider:
                provided=list(self.options_provider(field.options_source))
                if field.options_source=='item_schemes':options=provided
                else:
                    for option in provided:
                        if option[1] not in {value for _,value in options}:options.append(option)
            entry=create_field(parent,'choice',options=options,value=value,enabled=self.editable,caption=field.label)
            variable=entry.variable
        else:
            entry=create_field(parent,variable=variable,readonly=not self.editable)
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
