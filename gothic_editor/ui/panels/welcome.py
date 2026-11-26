"""Searchable startup project list; project files are never removed here."""
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox

from gothic_editor.core.localization import tr
from gothic_editor.ui.widgets.icons import IconImages
from gothic_editor.ui.widgets import BG, PANEL, MUTED, TXT, ACCENT, label, make_entry
from gothic_editor.ui.widgets.buttons import RoundedIconButton
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea
from gothic_editor.ui.widgets.theme import blend


from gothic_editor.ui.windows.confirmation import ProjectConfirmationDialog

class WelcomeScreen(Panel):
    def __init__(self, parent, history, on_create, on_browse, on_open, on_history_change=lambda:None):
        super().__init__(parent, bg=BG)
        self.history = history
        self.entries = list(history.entries)
        self.on_open, self.on_browse = on_open, on_browse
        self.on_history_change = on_history_change
        self.icons = IconImages(self)
        self.rows = []
        self.selected = None
        self.is_fullscreen=False
        self._opening_dialog=False
        content = tk.Frame(self, bg=BG)
        content.pack(fill='both', expand=True, padx=20, pady=12)
        self.title_bar = tk.Frame(content,bg=BG)
        self.title_bar.pack(fill='x',pady=(0,25))
        title_label=label(self.title_bar, 'Gothic Editor', bg=BG, font=('Arial',20,'bold'))
        title_label.pack(side='left')
        self._drag_origin=None
        for widget in (self.title_bar,title_label):
            widget.bind('<ButtonPress-1>',self.start_drag)
            widget.bind('<B1-Motion>',self.drag)
            widget.bind('<ButtonRelease-1>',self.stop_drag)
        self.close_button=RoundedIconButton(self.title_bar,self.icons,'close.png','×',tr('app.exit'),
                                            parent.destroy,background=BG,size=30,padding=5)
        self.close_button.pack(side='right')
        self.fullscreen_button=RoundedIconButton(self.title_bar,self.icons,'fullscreen.png','□',
            tr('welcome.fullscreen'),self.toggle_fullscreen,background=BG,size=30,padding=5)
        self.fullscreen_button.pack(side='right',padx=(0,6))
        self.header = tk.Frame(content, bg=BG)
        self.header.pack(fill='x', pady=(0,12))
        self.search_frame = tk.Frame(self.header, bg=BG)
        self.search_frame.columnconfigure(1, weight=1)
        self.search_frame.rowconfigure(0, minsize=40)
        label(self.search_frame, bg=BG, **self.icon('search.png', tr('welcome.search'),size=36)).grid(row=0, column=0, padx=(0,8))
        self.query = tk.StringVar(self)
        self.search = make_entry(self.search_frame, textvariable=self.query, width=15)
        self.search.grid(row=0, column=1, sticky='nsew')
        self.search.bind('<Return>', lambda _:self.open_selected())
        self.actions = tk.Frame(self.header, bg=BG)
        for filename, caption, fallback, command in [('create_project.png', 'welcome.create_button', '+', on_create),
                                                     ('open_project.png', 'welcome.open_button', '…', on_browse)]:
            RoundedIconButton(self.actions,self.icons,filename,fallback,tr(caption),command,
                              background=BG).pack(side='left',padx=(8,0))
        self.header.bind('<Configure>', self.layout_header)
        label(content, tr('welcome.recent_title'), bg=BG, fg=MUTED).pack(anchor='w', pady=(0,10))
        table = tk.Frame(content, bg=BG)
        table.pack(fill='both', expand=True)
        self.scroll_area=ScrollableArea(table,bg=BG)
        self.scroll_area.pack(fill='both',expand=True)
        self.canvas,self.projects=self.scroll_area.canvas,self.scroll_area.content
        self.scrollbar,self.window=self.scroll_area.scrollbar,self.scroll_area.window
        self.query.trace_add('write', lambda *_:self.render_projects())
        self.render_projects()

    def icon(self, filename, fallback, size=18):
        image = ''
        if (self.icons.directory / filename).is_file():
            try:image = self.icons.frames(filename, size, TXT, BG)[0]
            except (tk.TclError, OSError):pass
        return {'image':image, 'text':'' if image else fallback}

    def layout_header(self, event):
        self.header.columnconfigure(0, weight=1)
        self.search_frame.grid(row=0, column=0, sticky='ew')
        self.actions.grid(row=0, column=1, sticky='e')

    def render_projects(self):
        for child in self.projects.winfo_children():child.destroy()
        self.rows = []
        self.entries = list(self.history.entries)
        query = self.query.get().strip().casefold()
        visible = [entry for entry in self.entries if query in f'{entry.name} {entry.path}'.casefold()]
        self.selected = next((entry for entry in visible if self.valid_project(entry)),None)
        for entry in visible:self.add_row(entry)
        if not visible:
            label(self.projects, tr('welcome.no_matches' if query else 'welcome.empty'),
                  bg=BG, fg=MUTED).pack(anchor='w', pady=20)
        self.canvas.yview_moveto(0)

    def add_row(self, entry):
        available=self.valid_project(entry)
        row = tk.Frame(self.projects, bg=PANEL, padx=12, pady=10, takefocus=available)
        row.available=available
        row.animation=None
        row.progress=0
        row.target=0
        row.pack(fill='x', pady=(0,6))
        row.columnconfigure(1, weight=1)
        initials = ''.join(word[0] for word in entry.name.split()[:2]).upper() or '?'
        badge = label(row, initials, bg=BG, fg=ACCENT if available else MUTED, width=3, height=2, font=('Arial',14,'bold'))
        badge.grid(row=0, column=0, rowspan=2, padx=(0,14))
        name = label(row, entry.name, anchor='w', justify='left', fg=TXT if available else MUTED,
                     font=('Arial',11,'bold') if available else ('Arial',11,'bold overstrike'))
        row.name_label=name
        name.grid(row=0, column=1, sticky='ew')
        path = label(row, str(entry.path), fg=MUTED, anchor='w', justify='left')
        path.grid(row=1, column=1, sticky='ew', pady=(4,0))
        actions = tk.Frame(row, bg=PANEL, width=88, height=40)
        actions.grid(row=0, column=2, rowspan=2, padx=(12,0))
        actions.grid_propagate(False)
        actions.columnconfigure(0,minsize=44)
        actions.columnconfigure(1,minsize=44)
        buttons = []
        for index, (filename, caption, fallback, command) in enumerate([
                ('open_folder.png', 'welcome.open_folder', '[П]', lambda:self.open_folder(entry)),
                ('remove_recent.png', 'welcome.remove', '[×]', lambda:self.remove_recent(entry))]):
            if not available and filename=='open_folder.png':continue
            button = RoundedIconButton(actions,self.icons,filename,fallback,tr(caption),command)
            button.grid(row=0, column=index, padx=2)
            button.paint(opacity=0 if available else 1)
            button.grid_remove()
            buttons.append(button)

        def animate():
            row.animation=None
            if row.progress!=row.target:
                row.progress += 1 if row.target>row.progress else -1
            amount=row.progress/6
            background=blend(PANEL,'#252e3c',amount)
            for widget in (row,name,path,actions):widget.configure(bg=background)
            for button in buttons:
                if row.progress:button.grid()
                button.paint(background,amount)
                if not row.progress:button.grid_remove()
            if row.progress!=row.target:row.animation=row.after(20,animate)

        def hover(_=None):
            x, y = row.winfo_pointerxy()
            inside = (row.winfo_rootx() <= x < row.winfo_rootx()+row.winfo_width()
                      and row.winfo_rooty() <= y < row.winfo_rooty()+row.winfo_height())
            if not available:
                for button in buttons:
                    if inside:button.grid()
                    else:button.grid_remove()
                return
            row.target=6 if inside else 0
            if row.animation is None and row.progress!=row.target:animate()

        def cancel_animation(event):
            if event.widget is row and row.animation is not None:
                row.after_cancel(row.animation)
                row.animation=None

        row.bind('<Destroy>',cancel_animation)

        def select(_=None):
            self.selected = entry
            row.focus_set()

        def resize(event):
            for widget in (name,path):widget.configure(wraplength=max(80,event.width-220))

        for widget in (row,badge,name,path,actions,*buttons):
            widget.configure(cursor='hand2')
            widget.bind('<Enter>', hover, add='+')
            widget.bind('<Leave>', hover, add='+')
        for widget in (row,badge,name,path):
            widget.bind('<Button-1>', select)
            widget.bind('<ButtonRelease-1>', lambda _, current=entry:self.open_entry(current))
        row.bind('<Return>', lambda _:self.open_entry(entry))
        row.bind('<Configure>', resize)
        self.rows.append((entry,row,buttons))

    def toggle_fullscreen(self):
        owner=self.winfo_toplevel()
        if not self.is_fullscreen:self._normal_geometry=owner.geometry()
        self.is_fullscreen=not self.is_fullscreen
        if self.is_fullscreen:owner.overrideredirect(False)
        owner.attributes('-fullscreen',self.is_fullscreen)
        if not self.is_fullscreen:
            owner.overrideredirect(True)
            owner.geometry(self._normal_geometry)
        self.fullscreen_button.filename='restore.png' if self.is_fullscreen else 'fullscreen.png'
        self.fullscreen_button.text='▣' if self.is_fullscreen else '□'
        self.fullscreen_button.tooltip.text=tr('welcome.restore' if self.is_fullscreen else 'welcome.fullscreen')
        self.fullscreen_button.paint()

    def start_drag(self,event):
        if self.is_fullscreen:return
        owner=self.winfo_toplevel()
        self._drag_origin=(event.x_root,event.y_root,owner.winfo_x(),owner.winfo_y())

    def drag(self,event):
        if self._drag_origin is None:return
        mouse_x,mouse_y,window_x,window_y=self._drag_origin
        x=window_x+event.x_root-mouse_x
        y=window_y+event.y_root-mouse_y
        from gothic_editor.ui.platform import move_window
        move_window(self.winfo_toplevel(),x,y)

    def stop_drag(self,event):
        self._drag_origin=None

    def scroll(self, event):
        return self.scroll_area.wheel(event)

    def open_selected(self):
        if self.selected:self.open_entry(self.selected)
        else:self.on_browse()

    def open_entry(self,entry):
        if self._opening_dialog:return
        if not self.valid_project(entry):
            self.remove_recent(entry)
            return
        self._opening_dialog=True
        try:
            dialog=ProjectConfirmationDialog(self,entry,'open')
            self.wait_window(dialog)
        finally:self._opening_dialog=False
        if dialog.result:
            if self.valid_project(entry):self.on_open(entry.path)
            else:self.render_projects()

    def open_folder(self, entry):
        try:
            if not entry.path.is_dir():raise FileNotFoundError(str(entry.path))
            if sys.platform == 'win32':os.startfile(str(entry.path))
            else:subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(entry.path)])
        except OSError as exc:
            messagebox.showerror(tr('app.error'), str(exc), parent=self.winfo_toplevel())

    def remove_recent(self, entry):
        dialog = ProjectConfirmationDialog(self, entry, 'remove')
        self.wait_window(dialog)
        if not dialog.result:return
        try:self.history.forget(entry.path)
        except OSError as exc:
            messagebox.showerror(tr('app.error'), tr('welcome.save_error',error=str(exc)), parent=self.winfo_toplevel())
            return
        self.on_history_change()
        self.render_projects()

    @staticmethod
    def valid_project(entry):
        return entry.path.is_dir() and (entry.path/'project.json').is_file()
