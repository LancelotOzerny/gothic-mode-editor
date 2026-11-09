import tkinter as tk
from .theme import INPUT, MUTED
from .inputs import PropertyEntry

def add_placeholder(widget, variable, text):
    """Show a visual hint without ever inserting it into the actual value."""
    if not text:
        return
    hint = tk.Label(widget, text=text, bg=INPUT, fg=MUTED, anchor='w', cursor='xterm')

    def update(*_):
        if not variable.get() and widget.focus_get() is not widget:
            hint.place(x=0 if isinstance(widget,PropertyEntry) else 4, rely=.5, anchor='w', relwidth=.85)
        else:
            hint.place_forget()

    trace = variable.trace_add('write', update)
    widget.bind('<FocusIn>', update, add='+')
    widget.bind('<FocusOut>', update, add='+')
    hint.bind('<Button-1>', lambda _: widget.focus_set())
    widget.bind('<Destroy>', lambda event: variable.trace_remove('write', trace)
                if event.widget is widget else None, add='+')
    widget.value_variable = variable
    widget.placeholder = hint
    update()
