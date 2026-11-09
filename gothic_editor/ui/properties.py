"""Schema-driven property form with per-field project autosave."""
import tkinter as tk
import re
from tkinter import messagebox
from ..core.categories import classify
from ..core.localization import tr
from ..core.properties_schema import PropertyField,property_key,schema_for
from .widgets import PANEL,MUTED,BORDER,label,Tooltip
from .property_widgets import ExpressionCombobox,PropertySectionFrame,KeyValueList,add_placeholder
from .property_controls import PropertyEntry

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
        self._saving=False
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
        self.editable=classify(item)=='potions' and item.origin=='project'
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
            entry=KeyValueList(parent,field,value,self.editable,on_commit=commit)
            entry.pack(fill='x',padx=8)
            self.inputs[field.key]=entry
            self.fields[field.key]=field
            self.initial[field.key]=entry.get()
            return
        if field.field_type=='string' and re.fullmatch(r'"(?:\\.|[^"\\])*"',value):
            value=re.sub(r'\\([\\"])',r'\1',value[1:-1])
        label(parent,field.label,fg=MUTED,anchor='w',font=('Arial',9)).pack(fill='x',padx=8,pady=(6,2))
        variable=tk.StringVar(self)
        if field.widget=='combobox':
            options=list(field.options)
            if field.options_source and self.options_provider:
                for option in self.options_provider(field.options_source):
                    if option[1] not in {value for _,value in options}:options.append(option)
            entry=ExpressionCombobox(parent,options,textvariable=variable,state='readonly',caption=field.label)
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
        hint=field.description
        if field.placeholder:hint+=('\n' if hint else '')+tr('properties.example',value=field.placeholder)
        if hint:Tooltip(entry,hint)
        self.inputs[field.key]=entry
        self.fields[field.key]=field
        self.initial[field.key]=value

    def commit_field(self,key,generation):
        if generation!=self._generation:return
        entry=self.inputs.get(key)
        if isinstance(entry,ExpressionCombobox) and entry.popup is not None:return
        self.save(keys=(key,),automatic=True)

    def save(self,keys=None,automatic=False):
        if self._saving or not self.current or not self.editable:return True
        self._saving=True
        try:return self._save(keys,automatic)
        finally:self._saving=False

    def _save(self,keys,automatic):
        values,metadata,instance={}, {}, None
        for key,entry in self.inputs.items():
            if keys is not None and key not in keys:continue
            field=self.fields[key]
            if field.field_type=='key_value_list':
                if field.export:
                    try:values.update(entry.updates())
                    except ValueError as exc:
                        messagebox.showerror(tr('app.error'),str(exc),parent=self.winfo_toplevel())
                        return False
                continue
            value=entry.get() if field.source=='editor_metadata' or field.field_type=='string' else entry.get().strip()
            if value==self.initial[key]:continue
            if field.required and not value:
                messagebox.showerror(tr('app.error'),tr('properties.required',name=field.label),parent=self.winfo_toplevel())
                return False
            if field.source=='instance_id':
                instance=value if not field.prefix or value.casefold().startswith(field.prefix.casefold()) else field.prefix+value
            elif field.source=='editor_metadata':metadata[key]=value
            elif field.export:
                if field.field_type=='string' and value and not re.fullmatch(r'"(?:\\.|[^"\\])*"',value):
                    value='"'+value.replace('\\','\\\\').replace('"','\\"')+'"'
                values[property_key(key)]=value
        if values or metadata or instance is not None:
            options={}
            if instance is not None:options['instance']=instance
            if metadata:options['metadata']=metadata
            if automatic:options['autosave']=True
            result=self.on_save(self.current,values,**options)
            if result is None:return False
            if automatic:
                self.current=result
                self.info.config(text=result.instance)
                for key,entry in self.inputs.items():
                    if keys is not None and key not in keys:continue
                    if self.fields[key].field_type=='key_value_list':entry.accept_saved(result.fields)
                    self.initial[key]=entry.get()
        return True
