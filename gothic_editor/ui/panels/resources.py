"""Project Assets browser with a folder tree and responsive file tiles."""
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from gothic_editor.core.localization import tr
from gothic_editor.core.resources import open_in_editor, open_in_folder
from gothic_editor.core.asset_files import AssetFiles
from gothic_editor.ui.windows.resource_name import ResourceNameDialog
from gothic_editor.ui.widgets import BG, BORDER, PANEL, MUTED, INPUT, TXT, label
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea, attach_scrollbar
from gothic_editor.ui.widgets.file_tile import FileTile
from gothic_editor.ui.widgets.drag_preview import DragPreview
from gothic_editor.ui.widgets.icons import IconImages
from gothic_editor.ui.widgets.dock import TAB_ACTION_HEIGHT


class ResourcesPanel(Panel):
    def __init__(self,parent,get_editor,on_hide,on_changed=lambda:None,before_change=lambda:True,history=None):
        super().__init__(parent,bg=BG)
        self.project=self.folder=self.menu=self._selected=None
        self._tree_paths={}
        self.paths={}
        self.tiles={}
        self.columns=0
        self.get_editor=get_editor
        self.on_changed,self.before_change=on_changed,before_change
        self.history=history
        self.on_hide = on_hide
        self._copied=None
        self._drag = self._preview = self._drop = None
        self.icons = IconImages.shared(self)
        header=tk.Frame(self,bg=PANEL)
        header.pack(fill='x')
        self.location=label(header,'Assets',fg=MUTED,anchor='w')
        self.location.pack(side='left',fill='x',expand=True,padx=10)
        body=tk.PanedWindow(self,orient='horizontal',bg=BG,bd=0,sashwidth=5,sashrelief='flat')
        body.pack(fill='both',expand=True)
        sidebar=tk.Frame(body,bg=PANEL)
        self._style_tree()
        self.tree=ttk.Treeview(sidebar,show='tree',style='Resources.Treeview',selectmode='browse')
        self.tree.tag_configure('drop_allowed', background='#315b50')
        self.tree.tag_configure('drop_denied', background='#683f48')
        self.tree.column('#0',width=170,minwidth=60)
        attach_scrollbar(sidebar,self.tree)
        self.tree.pack(fill='both',expand=True)
        self.tree.bind('<<TreeviewSelect>>',self._tree_select)
        self.tree.bind('<<TreeviewOpen>>',self._tree_open)
        self.tree.bind('<Button-3>',self._tree_context)
        self.tree.bind('<Button-1>', self._tree_press, add='+')
        self.tree.bind('<Double-Button-1>', self._tree_open_file, add='+')
        self.tree.bind('<Control-KeyPress>',self.shortcut)
        self.tree.bind('<F2>', self._tree_rename)
        self._bind_drag(self.tree)
        body.add(sidebar,minsize=100,width=180)
        self.scroll_area=ScrollableArea(body,bg=PANEL)
        body.add(self.scroll_area,minsize=120,stretch='always')
        self.scrollbar=self.scroll_area.scrollbar
        self.scroll_area.content.bind('<Configure>',self.layout,add='+')
        self.bind('<Unmap>', self.cancel_drag)
        for widget in (self.scroll_area.canvas,self.scroll_area.content):
            widget.bind('<Button-3>',self._blank_context)
            widget.bind('<Button-1>',lambda event:(self.select_file(None),event.widget.focus_set()))
            widget.bind('<Control-KeyPress>',self.shortcut)
            widget.bind('<Escape>',self.cancel_drag)

    def build_tab_actions(self, parent):
        self.add_button(tr('resources.refresh'), self.refresh, parent=parent,
                        height=TAB_ACTION_HEIGHT).pack(side='left', padx=(0, 4))
        self.add_button('', self.on_hide, parent=parent, filename='close.png', caption=tr('tools.close'),
                        height=TAB_ACTION_HEIGHT).pack(side='left')

    def _style_tree(self):
        style = ttk.Style(self)
        indicator = 'Resources.Treeitem.indicator'
        icon_gap = 'Resources.Treeitem.icon_gap'
        if indicator not in style.element_names():
            closed, *_, opened = self.icons.disclosure(MUTED, PANEL)
            selected = self.icons.disclosure(MUTED, INPUT)
            empty = tk.PhotoImage(master=self, width=18, height=18)
            self.icons.blank_disclosure = empty
            gap = tk.PhotoImage(master=self, width=5, height=1)
            self.icons.resource_icon_gap = gap
            style.element_create(icon_gap, 'image', gap)
            style.element_create(indicator, 'image', closed, ('user2', empty),
                                 ('user1', 'selected', selected[-1]), ('user1', opened),
                                 ('selected', selected[0]), width=20, sticky='w')
        style.configure('Resources.Treeview', background=PANEL, fieldbackground=PANEL,
                        foreground=TXT, borderwidth=0, rowheight=28)
        style.layout('Resources.Treeview', [('Treeview.treearea', {'sticky': 'nswe'})])
        style.layout('Resources.Treeview.Item', [('Treeitem.padding', {'sticky': 'nswe', 'children': [
            (indicator, {'side': 'left', 'sticky': ''}),
            ('Treeitem.image', {'side': 'left', 'sticky': ''}),
            (icon_gap, {'side': 'left', 'sticky': ''}),
            ('Treeitem.text', {'side': 'left', 'sticky': ''}),
        ]})])
        style.map('Resources.Treeview', background=[('selected', INPUT)], foreground=[('selected', TXT)])

    @property
    def assets(self):
        return self.project/'Assets' if self.project else None

    def set_item(self,project,item):
        # Kept for existing callers: item selection never changes the browser folder.
        project=Path(project).resolve() if project else None
        changed=project!=self.project
        self.project=project
        if changed:
            self.folder=self.assets
            self._copied=None
        if changed or item is None:self.refresh()

    def _inside(self,path):
        path=Path(path).resolve()
        if self.assets is None or (path!=self.assets and self.assets not in path.parents):
            raise ValueError(tr('resources.invalid_folder'))
        return path

    def _children(self, path):
        return sorted((child for child in path.iterdir()
                       if (child.is_dir() or child.suffix.lower() == '.d')
                       and self.assets in child.resolve().parents),
                      key=lambda child: (not child.is_dir(), child.name.casefold()))

    def _add_node(self,parent,path):
        node=self.tree.insert(parent,'end',text=path.name,open=path==self.assets,
                              image=self.icons.resource(path, 64, 3))
        self._tree_paths[node]=path
        if path.is_dir() and self._children(path):self.tree.insert(node,'end',text='')
        return node

    def _populate(self,node):
        path=self._tree_paths.get(node)
        if path is None:return
        children=self.tree.get_children(node)
        if children and children[0] not in self._tree_paths:
            self.tree.delete(*children)
            for child in self._children(path):self._add_node(node,child)

    def _tree_open(self,_event=None):
        try:self._populate(self.tree.focus())
        except OSError as exc:self.location.config(text=str(exc))

    def _tree_select(self,_event=None):
        selection=self.tree.selection()
        if selection and selection[0] in self._tree_paths:
            path=self._tree_paths[selection[0]]
            if path.is_dir():
                if path!=self.folder:self.open_folder(path)
            elif path.parent != self.folder:
                self.open_folder(path.parent, selection=path)
            else:
                self.select_file(path)

    def open_folder(self,path,*,selection=None):
        try:
            path=self._inside(path)
            if not path.is_dir():raise FileNotFoundError(str(path))
            self.folder=path
            self._show_files()
            node=next(iter(self.tree.get_children()),None)
            if node is not None:
                for part in (selection or path).relative_to(self.assets).parts:
                    self._populate(node)
                    self.tree.item(node,open=True)
                    node=next(child for child in self.tree.get_children(node)
                              if self._tree_paths[child].name==part)
                if self.tree.selection() != (node,):self.tree.selection_set(node)
                self.tree.focus(node)
                self.tree.see(node)
            if selection is not None:self.select_file(selection)
        except (OSError,ValueError) as exc:self.location.config(text=str(exc))

    def refresh(self):
        self.cancel_drag()
        self.tree.delete(*self.tree.get_children())
        self._tree_paths={}
        try:
            if self.assets and self.assets.is_dir():
                self._populate(self._add_node('',self.assets))
                folder=self.folder or self.assets
                while folder!=self.assets and not folder.is_dir():folder=folder.parent
                self.open_folder(folder)
            else:self._show_files()
        except (OSError,ValueError) as exc:self.location.config(text=str(exc))

    def _show_files(self):
        selected=self._selected
        for tile in self.tiles.values():tile.destroy()
        self.paths={}
        self.tiles={}
        self._selected=None
        self.columns=0
        if self.assets is None or self.folder is None or not self.folder.is_dir():
            self.location.config(text='Assets')
            return
        self._inside(self.folder)
        files=sorted((path for path in self.folder.iterdir()
                      if self.assets in path.resolve().parents),
                     key=lambda path:(not path.is_dir(),path.name.casefold()))
        relative=self.folder.relative_to(self.assets).as_posix()
        self.location.config(text='Assets'+('/'+relative if relative!='.' else ''))
        for index,path in enumerate(files):
            self.paths[str(index)]=path
            self.tiles[path]=FileTile(self.scroll_area.content,path,path.name,
                                     self.select_file,self.open_selected,self.context)
            tile = self.tiles[path]
            tile.bind('<Control-KeyPress>',self.shortcut)
            tile.bind('<F2>',self._tile_rename)
            tile.bind('<Button-1>', lambda event, path=path: self.start_drag(event, path), add='+')
            self._bind_drag(tile)
        self.scroll_area.canvas.yview_moveto(0)
        self.layout()
        if selected in self.tiles:self.select_file(selected)

    def layout(self,_event=None):
        columns=max(1,self.scroll_area.content.winfo_width()//122)
        if columns==self.columns:return
        self.columns=columns
        for index,tile in enumerate(self.tiles.values()):
            tile.grid(row=index//columns,column=index%columns,padx=5,pady=5,sticky='nw')

    def select_file(self,path):
        previous=self.tiles.get(self._selected)
        if previous is not None:previous.set_selected(False)
        self._selected=path if path in self.tiles else None
        if self._selected is not None:self.tiles[path].set_selected(True)

    def selected_file(self):return self._selected

    def open_selected(self):
        if self._selected is None:return
        try:
            self._inside(self._selected)
            if self._selected.is_dir():self.open_folder(self._selected)
            else:open_in_editor(self._selected,self.get_editor(),self.project)
        except (OSError,ValueError) as exc:
            messagebox.showerror(tr('resources.title'),str(exc),parent=self.winfo_toplevel())

    def reveal_selected(self):
        if self._selected is None:return
        try:open_in_folder(self._selected)
        except OSError as exc:
            messagebox.showerror(tr('resources.title'),str(exc),parent=self.winfo_toplevel())

    def _blank_context(self,event):
        self.select_file(None)
        event.widget.focus_set()
        self.context(event)

    def _tree_context(self,event):
        node=self.tree.identify_row(event.y)
        path=self._tree_paths.get(node)
        if path is None:return
        self.tree.focus_set()
        self.tree.focus(node)
        # Tree folders may be outside the currently displayed directory.
        self.select_file(None)
        self._selected=path
        self.context(event)

    def _operation(self,operation,*,source=None):
        try:
            if not self.before_change():return
            history=self.history() if self.history is not None else None
            snapshot=history.capture((source,)) if history is not None and source is not None else {}
            result=operation(AssetFiles(self.project))
            if history is not None:history.record(snapshot,(result,) if result is not None else ())
            if source is not None:
                if self.folder is not None and self.folder.is_relative_to(source):
                    self.folder = result / self.folder.relative_to(source)
                if self._copied is not None and self._copied.is_relative_to(source):
                    self._copied = result / self._copied.relative_to(source)
            self.refresh()
            if result in self.tiles:
                self.select_file(result)
                self.tiles[result].focus_set()
            else:
                self.scroll_area.canvas.focus_set()
            self.on_changed(source, result)
        except (OSError,ValueError) as exc:
            messagebox.showerror(tr('resources.title'),str(exc),parent=self.winfo_toplevel())

    def create_resource(self,script=False):
        if self.folder is None:return
        dialog=ResourceNameDialog(self,script)
        self.wait_window(dialog)
        if dialog.result is not None:
            self._operation(lambda files:files.create(self.folder,dialog.result,script))

    def rename_selected(self, path=None):
        path = self._selected if path is None else path
        if path is None or path == self.assets:
            return
        dialog = ResourceNameDialog(self, resource=path)
        self.wait_window(dialog)
        if dialog.result is not None and dialog.result != path.name:
            self._operation(lambda files: files.rename(path, dialog.result), source=path)

    def _tree_rename(self, _event):
        path = self._tree_paths.get(self.tree.focus())
        if path is not None:
            self.rename_selected(path)
        return 'break'

    def _tile_rename(self, event):
        self.rename_selected(event.widget.path)
        return 'break'

    def _tree_open_file(self, event):
        path = self._tree_paths.get(self.tree.identify_row(event.y))
        if path is not None and path.is_file():
            self.open_folder(path.parent, selection=path)
            self.open_selected()
            return 'break'

    def _tree_press(self, event):
        if self.tree.identify_element(event.x, event.y).endswith('indicator'):
            self.cancel_drag()
            return
        node = self.tree.identify_row(event.y)
        path = self._tree_paths.get(node)
        self.start_drag(event, path)
        if self._drag is not None:
            self.tree.focus_set()
            self.tree.focus(node)
            return 'break'

    def _bind_drag(self, widget):
        widget.bind('<B1-Motion>', self.drag_motion)
        widget.bind('<ButtonRelease-1>', self.release_drag)
        widget.bind('<Escape>', self.cancel_drag)

    def start_drag(self, event, path):
        self.cancel_drag()
        if path is not None and path != self.assets:
            self._drag = (path, event.x_root, event.y_root)

    def _destination(self, x, y):
        widget = self.winfo_containing(x, y)
        node = None
        path = None
        if widget is self.tree:
            node = self.tree.identify_row(y - self.tree.winfo_rooty())
            path = self._tree_paths.get(node)
        elif isinstance(widget, FileTile) and widget.master is self.scroll_area.content:
            path = widget.path
        elif widget in (self.scroll_area.canvas, self.scroll_area.content):
            path = self.folder
        if path is not None and path.is_dir():
            return path, widget, node
        return None, None, None

    def _paint_drop(self, widget=None, node=None, allowed=False):
        previous = self._drop
        self._drop = (widget, node, allowed) if widget is not None else None
        if previous == self._drop:
            return
        if previous is not None:
            self._color_drop(*previous[:2], None)
        if self._drop is not None:
            self._color_drop(widget, node, 'drop_allowed' if allowed else 'drop_denied')

    def _color_drop(self, widget, node, tag):
        if widget is self.tree and node and self.tree.exists(node):
            tags = tuple(value for value in self.tree.item(node, 'tags') if value not in ('drop_allowed', 'drop_denied'))
            self.tree.item(node, tags=tags + ((tag,) if tag else ()))
        elif isinstance(widget, FileTile) and widget.winfo_exists():
            widget.set_drop_color({'drop_allowed': '#315b50', 'drop_denied': '#683f48'}.get(tag))

    def drag_motion(self, event):
        if self._drag is None:
            return
        source, x, y = self._drag
        if self._preview is None and abs(event.x_root - x) + abs(event.y_root - y) <= 6:
            return 'break'
        if self._preview is None:
            self._preview = DragPreview(self)
        folder, widget, node = self._destination(event.x_root, event.y_root)
        allowed = False
        if folder is not None:
            try:
                AssetFiles(self.project).move_target(source, folder)
                allowed = True
            except (OSError, ValueError):
                pass
        self._paint_drop(widget, node, allowed)
        self._preview.move(event.x_root, event.y_root, folder.name if folder is not None else '', allowed)
        return 'break'

    def cancel_drag(self, _event=None):
        active = self._drag is not None
        self._drag = None
        if self._preview is not None:
            self._preview.destroy()
            self._preview = None
        self._paint_drop()
        if active:
            return 'break'

    def release_drag(self, event):
        if self._preview is None:
            if self._drag is not None and event.widget is self.tree:
                node = self.tree.identify_row(event.y)
                if self._tree_paths.get(node) == self._drag[0]:
                    self.tree.selection_set(node)
            self.cancel_drag()
            return
        source = self._drag[0]
        folder, _, _ = self._destination(event.x_root, event.y_root)
        self.cancel_drag()
        if folder is not None:
            try:
                AssetFiles(self.project).move_target(source, folder)
            except (OSError, ValueError):
                return 'break'
            self._operation(lambda files: files.move(source, folder), source=source)
        return 'break'

    def copy_selected(self):
        path=self._selected
        if path is None and self.focus_get()==self.tree:
            selection=self.tree.selection()
            if selection:path=self._tree_paths.get(selection[0])
        if path is not None and path!=self.assets:self._copied=path

    def paste(self):
        if self._copied is not None and self.folder is not None:
            self._operation(lambda files:files.copy(self._copied,self.folder))

    def duplicate_selected(self):
        path=self._selected
        if path is not None and path!=self.assets:
            self._operation(lambda files:files.copy(path,path.parent))

    def delete_selected(self):
        path=self._selected
        if path is None or path==self.assets:return
        if messagebox.askyesno(tr('resources.delete_title'),
                tr('resources.delete_question',name=path.name)+ ('\n'+tr('resources.delete_contents') if path.is_dir() else ''),
                parent=self.winfo_toplevel()):
            self._operation(lambda files:files.delete(path),source=path)

    def copy_path(self,absolute=False):
        if self._selected is None:return
        path=self._inside(self._selected)
        value=str(path) if absolute else path.relative_to(self.project).as_posix()
        self.clipboard_clear()
        self.clipboard_append(value)

    def shortcut(self,event):
        key=event.keysym.lower()
        if self.tk.call('tk','windowingsystem')=='win32':
            key={67:'c',86:'v'}.get(event.keycode,key)
        if key=='c':self.copy_selected()
        elif key=='v':self.paste()
        else:return
        return 'break'

    def context(self,event):
        if self.project is None:return
        if self.menu is not None:self.menu.destroy()
        def menu(parent):return tk.Menu(parent,tearoff=False,bg=INPUT,fg=TXT,
                                        activebackground=PANEL,activeforeground=TXT)
        self.menu=menu(self)
        path=self._selected
        if path is None:
            self.menu.add_command(label=tr('resources.create_directory'),command=self.create_resource)
            scripts=menu(self.menu)
            scripts.add_command(label=tr('resources.empty_script'),command=lambda:self.create_resource(True))
            self.menu.add_cascade(label=tr('resources.scripts'),menu=scripts)
        elif path.is_dir():
            mutable='disabled' if path==self.assets else 'normal'
            self.menu.add_command(label=tr('resources.delete'),command=self.delete_selected,state=mutable)
            self.menu.add_command(label=tr('resources.duplicate'),command=self.duplicate_selected,state=mutable)
            paths=menu(self.menu)
            paths.add_command(label=tr('resources.project_path'),command=self.copy_path)
            paths.add_command(label=tr('resources.absolute_path'),command=lambda:self.copy_path(True))
            self.menu.add_cascade(label=tr('resources.copy_path'),menu=paths)
            self.menu.add_command(label=tr('resources.open'),command=self.open_selected)
        else:
            self.menu.add_command(label=tr('resources.duplicate'),command=self.duplicate_selected)
            self.menu.add_command(label=tr('resources.reveal'),command=self.reveal_selected)
            self.menu.add_command(label=tr('resources.delete'),command=self.delete_selected)
            self.menu.add_command(label=tr('resources.open'),command=self.open_selected)
        if path is not None:
            self.menu.add_command(label=tr('resources.rename'),command=self.rename_selected,accelerator='F2',
                                  state='disabled' if path == self.assets else 'normal')
        try:self.menu.tk_popup(event.x_root,event.y_root)
        finally:self.menu.grab_release()
