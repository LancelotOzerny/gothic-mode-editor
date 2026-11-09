"""Validate edited fields and persist changes without rebuilding the view."""
import re
from tkinter import messagebox

from gothic_editor.core.localization import tr
from gothic_editor.core.properties_schema import property_key


class PropertyEditor:
    def __init__(self, form):
        self.form = form
        self._saving = False

    def save(self, keys=None, automatic=False):
        form = self.form
        if self._saving or not form.current or not form.editable:return True
        self._saving = True
        try:return self._save(keys,automatic)
        finally:self._saving = False

    def _save(self,keys,automatic):
        form=self.form
        values,metadata,instance={}, {}, None
        for key,entry in form.inputs.items():
            if keys is not None and key not in keys:continue
            field=form.fields[key]
            if field.field_type=='key_value_list':
                if field.export:
                    try:values.update(entry.updates())
                    except ValueError as exc:
                        messagebox.showerror(tr('app.error'),str(exc),parent=form.winfo_toplevel())
                        return False
                continue
            value=entry.get() if field.source=='editor_metadata' or field.field_type in ('string','resource') else entry.get().strip()
            if value==form.initial[key]:continue
            if field.required and not value:
                messagebox.showerror(tr('app.error'),tr('properties.required',name=field.label),parent=form.winfo_toplevel())
                return False
            if field.source=='instance_id':
                instance=value if not field.prefix or value.casefold().startswith(field.prefix.casefold()) else field.prefix+value
            elif field.source=='editor_metadata':metadata[key]=value
            elif field.export:
                if field.field_type in ('string','resource') and value and not re.fullmatch(r'"(?:\\.|[^"\\])*"',value):
                    value='"'+value.replace('\\','\\\\').replace('"','\\"')+'"'
                values[property_key(key)]=value
        if values or metadata or instance is not None:
            options={}
            if instance is not None:options['instance']=instance
            if metadata:options['metadata']=metadata
            if automatic:options['autosave']=True
            result=form.on_save(form.current,values,**options)
            if result is None:return False
            if automatic:
                form.current=result
                form.info.config(text=result.instance)
                for key,entry in form.inputs.items():
                    if keys is not None and key not in keys:continue
                    if form.fields[key].field_type=='key_value_list':entry.accept_saved(result.fields)
                    form.initial[key]=entry.get()
        return True

