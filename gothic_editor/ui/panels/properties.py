"""Schema-driven property form with per-field project autosave."""
import tkinter as tk
import re
from gothic_editor.core.categories import classify, EDITABLE_CATEGORIES
from gothic_editor.core.localization import tr
from gothic_editor.core.properties_schema import PropertyField, property_key, schema_for
from gothic_editor.ui.widgets import PANEL, MUTED, BORDER, label
from gothic_editor.ui.widgets.theme import ERROR
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea
from gothic_editor.ui.widgets.form import create_field
from gothic_editor.ui.widgets.key_value_list import KeyValueList
from gothic_editor.ui.widgets.choice_list import ChoiceList
from gothic_editor.ui.widgets.function_actions import FunctionActionList
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
        self._schema=None
        self._loading=False
        self.appearance_holder=None
        self.error_labels={}
        self.editor=PropertyEditor(self)
        self.bind('<Destroy>',lambda event:self.editor.reset() if event.widget is self else None,add='+')
        label(self,tr('properties.title'),font=('Arial',10,'bold')).pack(fill='x',padx=14,pady=(14,0))
        self.info=label(self,tr('properties.select_item'),fg=MUTED,anchor='center',wraplength=280,justify='center')
        self.info.pack(fill='x',padx=14,pady=(4,0))
        self.save_status=label(self,'',fg=MUTED,wraplength=280,justify='left')
        self.save_status.pack(fill='x',padx=14,pady=(2,0))
        separator=tk.Frame(self,bg=PANEL,height=1)
        separator.pack(fill='x',pady=(10,20))
        tk.Frame(separator,bg=BORDER).place(relx=.05,relwidth=.9,relheight=1)
        self.scroll_area=ScrollableArea(self)
        self.scroll_area.pack(fill='both',expand=True)
        self.canvas,self.inner,self.window=self.scroll_area.canvas,self.scroll_area.content,self.scroll_area.window
        self.show(None)

    def show(self,item):
        if item is not None and self.current is not None:
            try:schema=schema_for(classify(item))
            except (OSError,ValueError,KeyError,TypeError):schema=None
            if (schema is not None and schema is self._schema and schema.show_missing and
                    not schema.unknown_section and self.editable==(classify(item) in EDITABLE_CATEGORIES and item.origin=='project')):
                self._reuse(item)
                return
        self.editor.reset()
        self.error_labels={}
        self.save_status.config(text='')
        self.current=item
        for child in self.inner.winfo_children():child.destroy()
        self.inputs={}
        self.fields={};self.initial={};self.editable=False
        self.sections={}
        self._schema=None
        self.appearance_holder=None
        if item is None:
            self.info.config(text=tr('properties.select_in_hierarchy'))
            return
        self.editable=classify(item) in EDITABLE_CATEGORIES and item.origin=='project'
        if self.editable:self.set_save_status('properties.saved')
        self.info.config(text=item.instance)
        try:
            schema=schema_for(classify(item))
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.editable=False
            self.save_status.config(text='')
            self.info.config(text=tr('properties.schema_error',error=str(exc)))
            return
        if schema is None:
            label(self.inner,tr('properties.readonly'),fg=MUTED,wraplength=260).pack(fill='x',padx=13,pady=8)
            for key in sorted(item.fields):self.render_field(self.inner,PropertyField(key,key),item.fields[key])
        else:
            self._schema=schema
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
        self._attach_action_parameters()
        if self.on_appearance is not None and classify(item) in EDITABLE_CATEGORIES and 'appearance' in self.sections:
            self.appearance_holder=tk.Frame(self.sections['appearance'].body,bg=PANEL)
            self.appearance_holder.pack(fill='x')
            self.on_appearance(self.appearance_holder,item)
        self.canvas.yview_moveto(0)

    def _reuse(self,item):
        self.editor.reset()
        self._loading=True
        try:
            self.current=item
            self.info.config(text=item.instance)
            for key,entry in self.inputs.items():
                self.clear_field_error(key)
                field=self.fields[key]
                if field.field_type=='key_value_list':
                    from gothic_editor.core.property_lists import PropertyList
                    entry.model=PropertyList(field,item.fields)
                    entry.set_expression(entry.model.rows)
                    self.initial[key]=entry.get()
                    continue
                if field.source=='instance_id':
                    value=item.instance
                    if field.prefix and value.casefold().startswith(field.prefix.casefold()):value=value[len(field.prefix):]
                elif field.source=='editor_metadata':value=item.editor_metadata.get(key,'')
                else:value=item.fields.get(property_key(key),'')
                if field.field_type in ('choice_list','action_list'):
                    entry.set_expression(value)
                    self.initial[key]=entry.get()
                    self.editor.watch(key,entry.value_variable)
                    continue
                if field.field_type in ('string','resource') and re.fullmatch(r'"(?:\\.|[^"\\])*"',value):
                    value=re.sub(r'\\([\\"])',r'\1',value[1:-1])
                if field.widget=='combobox':
                    entry.close_choices(restore_focus=False)
                    if field.options_source and self.options_provider:
                        provided=list(self.options_provider(field.options_source))
                        entry.options=tuple(provided if field.options_source=='item_schemes' else
                            list(field.options)+[option for option in provided if option[1] not in dict(field.options).values()])
                    entry.set_expression(value)
                else:entry.value_variable.set(value)
                self.initial[key]=value
                self.editor.watch(key,entry.value_variable)
            self._attach_action_parameters()
            if self.appearance_holder is not None:
                for child in self.appearance_holder.winfo_children():child.destroy()
                self.on_appearance(self.appearance_holder,item)
            if self.editable:self.set_save_status('properties.saved')
            else:self.save_status.config(text='')
        finally:self._loading=False

    def _attach_action_parameters(self):
        if 'parameters' in self.sections:
            loading=self._loading
            self._loading=True
            try:
                for key,entry in self.inputs.items():
                    if isinstance(entry,FunctionActionList):
                        entry.attach_parameters(self.sections['parameters'].body)
                        self.initial[key]=entry.get()
            finally:self._loading=loading

    def render_field(self,parent,field,value):
        if field.field_type in ('choice_list','action_list'):
            if field.tooltip:
                FieldLabel(parent,field.label,field.tooltip).pack(fill='x',padx=8,pady=(6,2))
            provider=lambda:self.options_provider(field.options_source) if self.options_provider else []
            if field.field_type=='action_list':
                entry=FunctionActionList(parent,field,value,provider,
                         lambda:self.options_provider('item_action_catalog'),self.editable)
            else:entry=ChoiceList(parent,field,value,provider,self.editable)
            entry.pack(fill='x',padx=8)
            self.inputs[field.key]=entry
            self.fields[field.key]=field
            self.initial[field.key]=entry.get()
            self.editor.watch(field.key,entry.value_variable)
            return
        if field.field_type=='key_value_list':
            if field.tooltip:
                FieldLabel(parent,field.label,field.tooltip).pack(fill='x',padx=8,pady=(6,2))
            entry=KeyValueList(parent,field,value,self.editable,
                               on_change=lambda:self.editor.changed(field.key))
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
        add_placeholder(entry,variable,field.placeholder)
        self.inputs[field.key]=entry
        self.fields[field.key]=field
        self.initial[field.key]=value
        self.editor.watch(field.key,variable)

    def set_save_status(self,key,error=False,**values):
        self.save_status.config(text=tr(key,**values),fg=ERROR if error else MUTED)

    def clear_field_error(self,key):
        if key in self.error_labels:self.error_labels[key].pack_forget()

    def show_field_error(self,key,message):
        entry=self.inputs[key]
        surface=getattr(entry,'surface',entry)
        if key not in self.error_labels:
            self.error_labels[key]=label(surface.master,'',fg=ERROR,wraplength=270,justify='left')
        error=self.error_labels[key]
        error.config(text=message)
        error.pack(after=surface,fill='x',padx=8,pady=(3,5))

    def save(self,keys=None,automatic=False):
        return self.editor.save(keys,automatic)
