"""Shared field construction; validation and persistence belong to form controllers."""
import tkinter as tk
from .inputs import PropertyEntry, NumberField
from .choice_field import ExpressionChoiceField
from .buttons import PropertyButton, PropertyToggle
from .field_label import FieldLabel
from .sections import PropertySectionFrame


def create_field(parent, kind='text', variable=None, value='', options=(), caption='',
                 enabled=True, readonly=False, minimum=None, maximum=None):
    state = 'normal' if enabled else 'disabled'
    if kind == 'choice':
        field = ExpressionChoiceField(parent, options, caption=caption,
            state='readonly' if enabled else 'disabled')
        field.set_expression(variable.get() if variable is not None else value)
        if variable is not None:
            def update_value(*_):
                value=field.get()
                if variable.get()!=value:variable.set(value)
            value_trace=variable.trace_add('write',lambda *_:field.set_expression(variable.get()))
            caption_trace=field.variable.trace_add('write',update_value)
            def dispose(event):
                if event.widget is field:
                    variable.trace_remove('write',value_trace)
                    field.variable.trace_remove('write',caption_trace)
            field.bind('<Destroy>',dispose,add='+')
    elif kind == 'boolean':
        field = PropertyToggle(parent, variable if variable is not None else
                               tk.BooleanVar(parent,value=False if value=='' else value))
        field.configure(state=state)
    else:
        kwargs = {'textvariable': variable} if variable is not None else {}
        field = (NumberField(parent, minimum=minimum, maximum=maximum, **kwargs)
                 if kind == 'number' else PropertyEntry(parent, **kwargs))
        if variable is None:field.insert(0, value)
        field.configure(state='readonly' if enabled and readonly else state)
    return field


class FormGroup(PropertySectionFrame):
    def add_field(self, title, kind='text', tooltip='', **kwargs):
        FieldLabel(self.body, title, tooltip).pack(fill='x', padx=8, pady=(6,2))
        field = create_field(self.body, kind, caption=title, **kwargs)
        field.pack(fill='x', padx=8)
        return field

    def add_button(self, text, command, **kwargs):
        button = PropertyButton(self.body, command, text=text, **kwargs)
        button.pack(fill='x', padx=8, pady=6)
        return button
