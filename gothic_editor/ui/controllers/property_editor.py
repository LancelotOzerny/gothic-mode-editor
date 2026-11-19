"""In-memory form drafts and debounced persistence without rebuilding widgets."""
import re

from gothic_editor.core.localization import tr
from gothic_editor.core.properties_schema import property_key
from gothic_editor.core.property_lists import validate_expression


class PropertyEditor:
    AUTOSAVE_DELAY = 1000

    def __init__(self, form):
        self.form = form
        self._saving = False
        self._after = None
        self._traces = []
        self.dirty = set()
        self.draft = {}
        self.removed_actions = set()

    def cancel(self):
        if self._after is not None:
            self.form.after_cancel(self._after)
            self._after = None

    def reset(self):
        self.cancel()
        for variable, trace in self._traces:
            variable.trace_remove('write', trace)
        self._traces.clear()
        self.dirty.clear()
        self.draft.clear()
        self.removed_actions.clear()

    def watch(self, key, variable):
        trace = variable.trace_add('write', lambda *_:self.changed(key))
        self._traces.append((variable, trace))

    def changed(self, key):
        form = self.form
        if self._saving or getattr(form,'_loading',False) or not form.editable or key not in form.inputs:return
        entry = form.inputs[key]
        # A Tk variable trace can precede the native Entry's content update.
        value = entry.get() if form.fields[key].field_type=='key_value_list' else entry.value_variable.get()
        if form.fields[key].widget=='combobox':value=entry.get()
        self.draft[key] = value
        if value == form.initial[key]:self.dirty.discard(key)
        else:self.dirty.add(key)
        form.clear_field_error(key)
        self.schedule_save()

    def remove_action(self, key):
        self.removed_actions.add(key)
        self.schedule_save()

    def schedule_save(self):
        form = self.form
        pending = self.dirty or self.removed_actions
        self.cancel()
        if any(error.winfo_manager() == 'pack' for error in form.error_labels.values()):
            form.set_save_status('properties.invalid', failed=True)
        else:
            form.set_save_status('properties.unsaved' if pending else 'properties.saved')
        if pending:self._after = form.after(self.AUTOSAVE_DELAY, self._autosave)

    def _autosave(self):
        self._after = None
        self.save(automatic=True)

    def save(self, keys=None, automatic=False):
        form = self.form
        if self._saving or not form.current or not form.editable:return True
        self.cancel()
        self._saving = True
        try:return self._save(keys)
        finally:self._saving = False

    def _save(self, keys):
        form = self.form
        removed_actions = {key for key in self.removed_actions if keys is None or key in keys}
        values, metadata, instance = dict.fromkeys(removed_actions, ''), {}, None
        instance_key = None
        valid = True
        selected = [key for key in form.inputs if keys is None or key in keys]
        for key in selected:
            entry, field = form.inputs[key], form.fields[key]
            form.clear_field_error(key)
            try:
                if field.field_type=='key_value_list':
                    if field.export:values.update(entry.updates())
                    continue
                value = entry.get()
                if field.source!='editor_metadata' and field.field_type not in ('string','resource'):value=value.strip()
                if value==form.initial[key]:continue
                if field.field_type=='action_list':entry.validate()
                if field.required and not value:
                    raise ValueError(tr('properties.required',name=field.label))
                if field.field_type=='expression' and not validate_expression(value):
                    raise ValueError(tr('properties.expression_required'))
                if field.source=='instance_id':
                    instance_key = key
                    instance = value if not field.prefix or value.casefold().startswith(field.prefix.casefold()) else field.prefix+value
                    if not re.fullmatch(r'[A-Za-z_]\w*',instance,re.ASCII):
                        raise ValueError(tr('properties.invalid_instance'))
                elif field.source=='editor_metadata':metadata[key]=value
                elif field.export:
                    if field.field_type in ('string','resource') and value and not re.fullmatch(r'"(?:\\.|[^"\\])*"',value):
                        value='"'+value.replace('\\','\\\\').replace('"','\\"')+'"'
                    values[property_key(key)]=value
            except ValueError as exc:
                form.show_field_error(key,str(exc))
                valid = False
        if not valid:
            form.set_save_status('properties.invalid',failed=True)
            return False
        if values or metadata or instance is not None:
            options = {'autosave':True}
            if instance is not None:options['instance']=instance
            if metadata:options['metadata']=metadata
            form.set_save_status('properties.saving')
            try:result=form.on_save(form.current,values,**options)
            except (OSError,ValueError) as exc:
                form.set_save_status('properties.save_error',failed=True,detail=str(exc))
                if instance_key is not None:form.show_field_error(instance_key,str(exc))
                return False
            if result is None:
                form.set_save_status('properties.save_error',failed=True,detail=tr('properties.save_rejected'))
                return False
            form.current=result
            form.info.config(text=result.instance)
        for key in selected:
            entry=form.inputs[key]
            if form.fields[key].field_type=='key_value_list':entry.accept_saved(form.current.fields)
            form.initial[key]=entry.get()
            self.draft.pop(key,None)
            self.dirty.discard(key)
        if removed_actions:
            self.removed_actions.difference_update(removed_actions)
            form._show_original_actions(form.current)
        self.schedule_save()
        return True
