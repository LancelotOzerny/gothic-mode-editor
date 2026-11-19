"""Resizable panel containers and one scoped, disposable scrolling implementation."""
import tkinter as tk

from .theme import PANEL
from .scrollbar import RoundedScrollbar


class Panel(tk.Frame):
    def __init__(self, parent, **kwargs):
        kwargs.setdefault('bg', PANEL)
        super().__init__(parent, **kwargs)

    def add_group(self, title, closed=False, on_toggle=lambda _:None, parent=None, *, compact=False):
        from .form import FormGroup
        group = FormGroup(parent if parent is not None else self, title, closed, on_toggle, compact=compact)
        group.pack(fill='x', pady=(0,25 if compact else 30))
        return group

    def add_button(self, text, command, parent=None, **kwargs):
        from .buttons import PropertyButton
        return PropertyButton(parent if parent is not None else self, command, text=text, **kwargs)


def attach_scrollbar(parent, widget):
    """The same scrollbar also attaches to native Text, Treeview and Listbox widgets."""
    scrollbar = RoundedScrollbar(parent, widget.yview)
    scrollbar.pack(side='right', fill='y')
    widget.configure(yscrollcommand=scrollbar.set)
    return scrollbar


class ScrollableArea(Panel):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        background = self.cget('bg')
        self.canvas = tk.Canvas(self, bg=background, highlightthickness=0, bd=0)
        self.scrollbar = attach_scrollbar(self, self.canvas)
        self.canvas.pack(fill='both', expand=True)
        self.content = tk.Frame(self.canvas, bg=background)
        self.window = self.canvas.create_window((0,0), window=self.content, anchor='nw')
        self.canvas.bind('<Configure>', self._resize)
        self.content.bind('<Configure>', self._update_region)
        self.owner = self.winfo_toplevel()
        self._bindings = [(sequence, self.owner.bind(sequence, self.wheel, add='+'))
                          for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>')]
        self.bind('<Destroy>', self._dispose, add='+')

    def _resize(self, event):
        self.canvas.itemconfigure(self.window, width=event.width)
        self._update_region()

    def _update_region(self, _event=None):
        self.canvas.configure(scrollregion=(0,0,max(1,self.canvas.winfo_width()),
            max(self.canvas.winfo_height(), self.content.winfo_reqheight())))

    def wheel(self, event):
        if not (self.winfo_rootx() <= event.x_root < self.winfo_rootx()+self.winfo_width()
                and self.winfo_rooty() <= event.y_root < self.winfo_rooty()+self.winfo_height()):
            return
        first, last = self.canvas.yview()
        if last-first < .999:
            delta = getattr(event, 'delta', 0)
            if not delta and getattr(event,'num',None) not in (4,5):return 'break'
            units = (-max(1,round(abs(delta)/120)) if delta > 0 else max(1,round(abs(delta)/120)))
            if getattr(event, 'num', None) in (4,5):units = -1 if event.num == 4 else 1
            self.canvas.yview_scroll(units, 'units')
        return 'break'

    def _dispose(self, event):
        if event.widget is self:
            for sequence, binding in self._bindings:
                if binding:self.owner.unbind(sequence, binding)
            self._bindings.clear()
