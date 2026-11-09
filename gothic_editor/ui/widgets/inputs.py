import tkinter as tk
from tkinter import font as tkfont
from gothic_editor.core.localization import tr
from .theme import INPUT, PANEL, TXT, MUTED, BORDER, ACCENT, FIELD_HEIGHT, FIELD_FONT, rounded_box

def entry_menu(widget):
    menu=tk.Menu(widget,tearoff=False)
    for title,sequence in [(tr('widgets.cut'),'<<Cut>>'),(tr('widgets.copy'),'<<Copy>>'),(tr('widgets.paste'),'<<Paste>>'),(tr('widgets.select_all'),None)]:
        if sequence:menu.add_command(label=title,command=lambda s=sequence:widget.event_generate(s))
        else:menu.add_command(label=title,command=lambda:widget.select_range(0,'end') if isinstance(widget,tk.Entry) else widget.selection_range(0,'end'))
    def show(e):widget.focus_set();menu.tk_popup(e.x_root,e.y_root)
    widget.bind('<Button-3>',show,add='+')
    def shortcut(event):
        key = event.keysym.lower()
        if widget.tk.call('tk','windowingsystem') == 'win32':
            key = {65:'a',67:'c',86:'v',88:'x'}.get(event.keycode,key)
        key = {'cyrillic_ef':'a','cyrillic_es':'c','cyrillic_em':'v','cyrillic_che':'x',
               'ф':'a','с':'c','м':'v','ч':'x'}.get(key,key)
        if key == 'a':
            if widget.cget('state') != 'disabled':
                widget.selection_range(0,'end')
                widget.icursor('end')
            return 'break'
        sequence = {'c':'<<Copy>>','x':'<<Cut>>','v':'<<Paste>>'}.get(key)
        if sequence:
            widget.event_generate(sequence)
            return 'break'
    widget.bind('<Control-KeyPress>',shortcut,add='+')
    return widget

def make_entry(parent,**kw):
    return PropertyEntry(parent,**kw)

class PropertyEntry(tk.Entry):
    """A native entry (selection, clipboard, focus) inside a padded dark surface."""
    def __init__(self, parent, right_padding=10, **kwargs):
        font = kwargs.pop('font', FIELD_FONT)
        width = kwargs.get('width',20)
        self.surface = tk.Canvas(parent, bg=parent.cget('bg'), height=FIELD_HEIGHT,
                                 width=tkfont.Font(root=parent,font=font).measure('0')*int(width)+20,
                                 highlightthickness=0, bd=0)
        self.right_padding = right_padding
        self.hovered = False
        super().__init__(self.surface, bg=INPUT, readonlybackground=INPUT, disabledbackground=INPUT, fg=TXT,
                         disabledforeground=MUTED, insertbackground=TXT, font=font,
                         relief='flat', bd=0, highlightthickness=0, **kwargs)
        self._entry_window=self.surface.create_window(10,FIELD_HEIGHT/2,window=self,anchor='w')
        entry_menu(self)
        self.bind('<Button-1>',lambda _:self.focus_set(),add='+')
        self.surface.bind('<Configure>', lambda _:self.paint())
        for widget in (self, self.surface):
            widget.bind('<Enter>', lambda _:self.highlight(True), add='+')
            widget.bind('<Leave>', lambda _:self.highlight(False), add='+')
        self.bind('<FocusIn>', lambda _:self.paint(), add='+')
        self.bind('<FocusOut>', lambda _:self.paint(), add='+')
        self.surface.bind('<Button-1>', lambda _:self.focus_set())

    def pack(self, **kwargs):
        kwargs.pop('ipady', None)
        return self.surface.pack(**kwargs)

    def grid(self, **kwargs):return self.surface.grid(**kwargs)
    def place(self, **kwargs):return self.surface.place(**kwargs)
    def pack_forget(self):return self.surface.pack_forget()
    def grid_forget(self):return self.surface.grid_forget()
    def grid_remove(self):return self.surface.grid_remove()

    def highlight(self, hovered):
        self.hovered = hovered
        self.paint()

    def paint(self):
        focused = self.focus_get() is self
        border = ACCENT if focused else MUTED if self.hovered else BORDER
        width=self.surface.winfo_width()
        self.surface.itemconfigure(self._entry_window,width=max(1,width-10-self.right_padding))
        if hasattr(self,'_arrow_window'):
            self.surface.coords(self._arrow_window,width-10,FIELD_HEIGHT/2)
        if hasattr(self,'_buttons_window'):
            self.surface.coords(self._buttons_window,width-3,FIELD_HEIGHT/2)
        rounded_box(self.surface, width, FIELD_HEIGHT, INPUT, border)


class NumberField(PropertyEntry):
    """An editable native entry with bounded stepping; validation stays in the controller."""
    def __init__(self, parent, minimum=None, maximum=None, **kwargs):
        self.minimum, self.maximum = minimum, maximum
        super().__init__(parent, right_padding=36, **kwargs)
        controls = tk.Frame(self.surface, bg=INPUT)
        for title, delta in (('▴',1),('▾',-1)):
            tk.Button(controls,text=title,command=lambda d=delta:self.step(d),bg=INPUT,fg=TXT,
                activebackground=BORDER,activeforeground=TXT,bd=0,padx=4,pady=0,
                font=('Arial',8),takefocus=False).pack(fill='x')
        self._buttons_window = self.surface.create_window(0,FIELD_HEIGHT/2,window=controls,anchor='e')
        self.bind('<Up>',lambda _:self.step(1))
        self.bind('<Down>',lambda _:self.step(-1))

    def step(self, delta):
        if self.cget('state') != 'normal':return 'break'
        try:value = int(self.get()) + delta
        except ValueError:return 'break'
        if self.minimum is not None:value = max(self.minimum,value)
        if self.maximum is not None:value = min(self.maximum,value)
        self.delete(0,'end')
        self.insert(0,str(value))
        return 'break'
