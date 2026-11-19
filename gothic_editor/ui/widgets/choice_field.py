import tkinter as tk
from gothic_editor.core.localization import tr
from .theme import INPUT, TXT
from .inputs import PropertyEntry
from gothic_editor.ui.windows.value_choice import ValueChoiceWindow

class ExpressionChoiceField(PropertyEntry):
    def __init__(self, parent, options, **kwargs):
        self.caption=kwargs.pop('caption',tr('settings.choose'))
        self.options = options
        self.variable=kwargs.pop('textvariable',None) or tk.StringVar(parent)
        self.selection_window=None
        self.owner=parent.winfo_toplevel()
        super().__init__(parent,right_padding=32,textvariable=self.variable,**kwargs)
        self.arrow=tk.Label(self.surface,text='…',bg=INPUT,fg=TXT,cursor='hand2')
        self._arrow_window=self.surface.create_window(0,self.height/2,window=self.arrow,anchor='e')
        for widget in (self,self.surface,self.arrow):
            widget.bind('<ButtonRelease-1>',self.open_choices)
            widget.configure(cursor='hand2')
        self.bind('<Down>',self.open_choices)
        self.bind('<Alt-Down>',self.open_choices)
        self.bind('<Destroy>',lambda _:self.close_choices(restore_focus=False),add='+')

    def set(self, caption):
        self.variable.set(caption)

    def current(self, index=None):
        if index is None:
            return next((i for i,(name,_) in enumerate(self.options) if name==self.variable.get()),-1)
        self.set(self.options[index][0])

    def open_choices(self, event=None):
        if self.cget('state') == 'disabled':return 'break'
        if self.selection_window is not None:
            self.selection_window.lift()
            self.selection_window.focus_set()
            return 'break'
        self.focus_set()
        self.selection_window = ValueChoiceWindow(self.owner, self.options, self.current(),
            self.caption, self.accept_choice, self.close_choices)
        self.selection_window.bind('<Destroy>', self.dialog_destroyed, add='+')
        self.selection_window.show()
        return 'break'

    def accept_choice(self, index):
        self.current(index)
        self.close_choices()
        self.event_generate('<<ComboboxSelected>>')

    def dialog_destroyed(self, event):
        if event.widget is self.selection_window:self.selection_window = None

    def close_choices(self, restore_focus=True):
        window = self.selection_window
        self.selection_window = None
        if window is not None and window.winfo_exists():
            window.destroy()
            if restore_focus and self.winfo_exists():
                self.owner.focus_force()
                self.focus_set()

    def set_expression(self, expression):
        self.set(next((name for name, value in self.options if value == expression), expression))

    def get(self):
        caption = self.variable.get()
        return next((value for name, value in self.options if name == caption), caption)
