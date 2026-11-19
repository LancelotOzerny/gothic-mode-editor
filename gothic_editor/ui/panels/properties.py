"""Schema-driven property form with per-field project autosave."""
import tkinter as tk
import re
from gothic_editor.core.categories import classify, EDITABLE_CATEGORIES
from gothic_editor.core.localization import tr
from gothic_editor.core.properties_schema import PropertyField, property_key, schema_for
from gothic_editor.ui.widgets import PANEL, MUTED, Tooltip, label
from gothic_editor.ui.widgets.theme import COMPACT_FIELD_HEIGHT, COMPACT_FIELD_PADDING, ERROR, SAVED, UNSAVED
from gothic_editor.ui.widgets.buttons import PropertyButton
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea
from gothic_editor.ui.widgets.form import create_field
from gothic_editor.ui.widgets.key_value_list import KeyValueList
from gothic_editor.ui.widgets.choice_list import ChoiceList
from gothic_editor.ui.widgets.function_actions import FunctionActionList
from gothic_editor.ui.widgets.placeholders import add_placeholder
from gothic_editor.ui.widgets.field_label import FieldLabel

from gothic_editor.ui.controllers.property_editor import PropertyEditor

ROTATION_AXES = {'inv_rotx': 'X', 'inv_roty': 'Y', 'inv_rotz': 'Z'}

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
        self.original_actions=None
        self.error_labels={}
        self.error_anchors={}
        self.editor=PropertyEditor(self)
        self.bind('<Destroy>',lambda event:self.editor.reset() if event.widget is self else None,add='+')
        heading = tk.Frame(self, bg=PANEL)
        heading.pack(fill='x', padx=14, pady=(10, 5))
        self.info = label(heading, '', anchor='w', wraplength=260, justify='left', font=('Arial', 10, 'bold'))
        self.info.pack(side='left', fill='x', expand=True)
        self.save_dot = tk.Canvas(heading, bg=PANEL, width=12, height=12, bd=0, highlightthickness=0)
        self.save_circle = self.save_dot.create_oval(1, 1, 11, 11, outline='')
        self.save_tooltip = Tooltip(self.save_dot, '')
        self.scroll_area=ScrollableArea(self)
        self.scroll_area.pack(fill='both',expand=True)
        self.canvas,self.inner,self.window=self.scroll_area.canvas,self.scroll_area.content,self.scroll_area.window
        self.show(None)

    def show(self,item):
        self.node = None
        if item is not None and self.current is not None:
            try:schema=schema_for(classify(item))
            except (OSError,ValueError,KeyError,TypeError):schema=None
            if (schema is not None and schema is self._schema and schema.show_missing and
                    not schema.unknown_section and self.editable==(classify(item) in EDITABLE_CATEGORIES and item.origin=='project')):
                self._reuse(item)
                return
        self.editor.reset()
        self.error_labels={}
        self.error_anchors={}
        self.show_save_status('')
        self.current=item
        for child in self.inner.winfo_children():child.destroy()
        self.inputs={}
        self.fields={};self.initial={};self.editable=False
        self.sections={}
        self._schema=None
        self.appearance_holder=None
        self.original_actions=None
        if item is None:
            self.info.config(text=tr('properties.select_in_hierarchy'))
            return
        self.editable=classify(item) in EDITABLE_CATEGORIES and item.origin=='project'
        self.set_save_status('properties.saved')
        self.info.config(text=item.instance)
        try:
            schema=schema_for(classify(item))
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.editable=False
            self.set_save_status('properties.schema_error', failed=True, error=str(exc))
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
                    lambda closed,key=section.key:self.collapsed.__setitem__(key,closed),parent=self.inner,compact=True)
                self.sections[section.key]=frame
                rotation = None
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
                    if section.key == 'appearance' and field.key in ROTATION_AXES:
                        if rotation is None:
                            label(frame.body, tr('properties.inventory_rotation'), anchor='w').pack(fill='x', padx=8)
                            rotation = tk.Frame(frame.body, bg=PANEL)
                            rotation.pack(fill='x', padx=4)
                        axis = ROTATION_AXES[field.key]
                        column = 'XYZ'.index(axis)
                        rotation.columnconfigure(column, weight=1, uniform='axes')
                        holder = tk.Frame(rotation, bg=PANEL)
                        holder.grid(row=0, column=column, sticky='ew')
                        self.error_anchors[field.key] = rotation
                        self.render_field(holder, field, value, axis=axis)
                    else:
                        self.render_field(frame.body,field,value)
                if section.key==schema.unknown_section:
                    for key in sorted(item.fields):
                        if property_key(key) not in known:
                            self.render_field(frame.body,PropertyField(key,key),item.fields[key])
        self._attach_action_parameters()
        self._show_original_actions(item)
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
            self._show_original_actions(item)
            if self.appearance_holder is not None:
                for child in self.appearance_holder.winfo_children():child.destroy()
                self.on_appearance(self.appearance_holder,item)
            self.set_save_status('properties.saved')
        finally:self._loading=False

    def _show_original_actions(self,item):
        """Display source callbacks without turning them into additional calls."""
        if self.original_actions is not None:self.original_actions.destroy()
        self.original_actions=None
        if classify(item) not in ('potions','documents') or 'actions' not in self.sections:return
        callbacks=[(key,value.strip()) for key,value in item.fields.items()
                   if re.fullmatch(r'on_state\[[0-3]\]',key,re.I) and value.strip() not in ('','0')
                   and key not in self.editor.removed_actions]
        if not callbacks:return
        parent=self.sections['actions'].body
        holder=tk.Frame(parent,bg=PANEL)
        self.original_actions=holder
        children=parent.winfo_children()
        if len(children)>1:holder.pack(before=children[0],fill='x',padx=8,pady=(4,8))
        else:holder.pack(fill='x',padx=8,pady=(4,8))
        label(holder,tr('properties.original_actions'),fg=MUTED,anchor='w').pack(fill='x')
        for key,value in sorted(callbacks):
            row = tk.Frame(holder, bg=PANEL)
            row.pack(fill='x', pady=COMPACT_FIELD_PADDING)
            if self.editable:
                button = PropertyButton(row, lambda key=key: self.remove_original_action(key), text='×',
                                        filename='remove_recent.png', caption=tr('resources.delete'),
                                        height=COMPACT_FIELD_HEIGHT)
                button.pack(side='right', padx=(4, 0))
            field=create_field(row,value=f'{key}: {value}',readonly=True,height=None)
            field.pack(side='left',fill='x',expand=True)

    def remove_original_action(self, key):
        self.editor.remove_action(key)
        self._show_original_actions(self.current)

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

    def render_field(self,parent,field,value,*,axis=None):
        if field.field_type in ('choice_list','action_list'):
            if field.tooltip:
                FieldLabel(parent,field.label,field.tooltip).pack(fill='x',padx=8,pady=(2,0))
            provider=lambda:self.options_provider(field.options_source) if self.options_provider else []
            if field.field_type=='action_list':
                entry=FunctionActionList(parent,field,value,provider,
                         lambda:self.options_provider('item_action_catalog'),self.editable,height=COMPACT_FIELD_HEIGHT)
            else:entry=ChoiceList(parent,field,value,provider,self.editable,height=COMPACT_FIELD_HEIGHT)
            entry.pack(fill='x',padx=8)
            self.inputs[field.key]=entry
            self.fields[field.key]=field
            self.initial[field.key]=entry.get()
            self.editor.watch(field.key,entry.value_variable)
            return
        if field.field_type=='key_value_list':
            if field.tooltip:
                FieldLabel(parent,field.label,field.tooltip).pack(fill='x',padx=8,pady=(2,0))
            entry=KeyValueList(parent,field,value,self.editable,
                               on_change=lambda:self.editor.changed(field.key),height=COMPACT_FIELD_HEIGHT)
            entry.pack(fill='x',padx=8)
            self.inputs[field.key]=entry
            self.fields[field.key]=field
            self.initial[field.key]=entry.get()
            return
        if field.field_type in ('string','resource') and re.fullmatch(r'"(?:\\.|[^"\\])*"',value):
            value=re.sub(r'\\([\\"])',r'\1',value[1:-1])
        padding = 4 if axis else 8
        FieldLabel(parent,axis or field.label,field.tooltip).pack(fill='x',padx=padding,pady=(2,0))
        variable=tk.StringVar(self,value=value)
        if field.widget=='combobox':
            options=list(field.options)
            if field.options_source and self.options_provider:
                provided=list(self.options_provider(field.options_source))
                if field.options_source=='item_schemes':options=provided
                else:
                    for option in provided:
                        if option[1] not in {value for _,value in options}:options.append(option)
            entry=create_field(parent,'choice',options=options,value=value,enabled=self.editable,
                               caption=field.label,height=None)
            variable=entry.variable
        else:
            entry=create_field(parent,variable=variable,readonly=not self.editable,height=None)
        entry.pack(fill='x',padx=padding,pady=COMPACT_FIELD_PADDING)
        entry.value_variable=variable
        add_placeholder(entry,variable,field.placeholder)
        self.inputs[field.key]=entry
        self.fields[field.key]=field
        self.initial[field.key]=value
        self.editor.watch(field.key,variable)

    def set_save_status(self,key,failed=False,**values):
        color = ERROR if failed else SAVED if key == 'properties.saved' else UNSAVED
        self.show_save_status(tr(key, **values), color)

    def show_save_status(self, message, color=None):
        self.save_tooltip.hide()
        self.save_tooltip.text = message
        if message:
            self.save_dot.itemconfigure(self.save_circle, fill=color)
            self.save_dot.pack(side='left', before=self.info, padx=(0, 6))
        else:
            self.save_dot.pack_forget()

    def clear_field_error(self,key):
        if key in self.error_labels:self.error_labels[key].pack_forget()

    def show_field_error(self,key,message):
        entry=self.inputs[key]
        surface=self.error_anchors.get(key, getattr(entry,'surface',entry))
        if key not in self.error_labels:
            self.error_labels[key]=label(surface.master,'',fg=ERROR,wraplength=270,justify='left')
        error=self.error_labels[key]
        error.config(text=message)
        error.pack(after=surface,fill='x',padx=8,pady=(3,5))

    def save(self,keys=None,automatic=False):
        if getattr(self,'node',None) is not None:
            return self.save_node()
        return self.editor.save(keys,automatic)

    def show_node(self,node,on_save):
        self.show(None)
        self.node = node
        self.node_save = on_save
        self.node_initial = node.name
        self.info.config(text='Группа' if node.kind=='group' else node.code)
        group = self.add_group('Группа' if node.kind=='group' else 'Категория',parent=self.inner,compact=True)
        name = tk.StringVar(self, value=node.name)
        self.node_name = group.add_field('Название',variable=name)
        self.set_save_status('properties.saved')
        trace = name.trace_add('write', lambda *_: self.set_save_status(
            'properties.saved' if name.get().strip() == self.node_initial else 'properties.unsaved'))
        self.node_name.bind('<Destroy>', lambda _: name.trace_remove('write', trace), add='+')
        group.add_button('Сохранить',self.save_node)

    def save_node(self):
        value = self.node_name.get().strip()
        if value == self.node_initial:return True
        try:self.node_save(self.node,value)
        except (OSError,ValueError) as exc:
            self.show_save_status(str(exc), ERROR)
            return False
        self.node_initial = value
        self.set_save_status('properties.saved')
        return True
