"""Project Assets browser with a folder tree and responsive file tiles."""
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from gothic_editor.core.localization import tr
from gothic_editor.core.resources import open_in_editor, open_in_folder
from gothic_editor.core.asset_files import AssetFiles
from gothic_editor.ui.windows.resource_name import ResourceNameDialog
from gothic_editor.ui.widgets import BG, PANEL, MUTED, INPUT, TXT, label
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea, attach_scrollbar
from gothic_editor.ui.widgets.file_tile import FileTile


class ResourcesPanel(Panel):
    def __init__(self,parent,get_editor,on_hide,on_changed=lambda:None,before_change=lambda:True):
        super().__init__(parent,bg=BG)
        self.project=self.folder=self.menu=self._selected=None
        self._tree_paths={}
        self.paths={}
        self.tiles={}
        self.columns=0
        self.get_editor=get_editor
        self.on_changed,self.before_change=on_changed,before_change
        self._copied=None
        header=tk.Frame(self,bg=PANEL)
        header.pack(fill='x')
        self.location=label(header,'Assets',fg=MUTED,anchor='w')
        self.location.pack(side='left',fill='x',expand=True,padx=10)
        self.add_button('×',on_hide,parent=header).pack(side='right')
        self.add_button(tr('resources.refresh'),self.refresh,parent=header).pack(side='right',padx=6)
        body=tk.PanedWindow(self,orient='horizontal',bg=BG,bd=0,sashwidth=5)
        body.pack(fill='both',expand=True)
        sidebar=tk.Frame(body,bg=PANEL)
        style=ttk.Style(self)
        style.configure('Resources.Treeview',background=PANEL,fieldbackground=PANEL,
                        foreground=TXT,borderwidth=0,rowheight=28)
        # Native Windows Treeview fields otherwise paint empty space white.
        style.layout('Resources.Treeview',[('Treeview.treearea',{'sticky':'nswe'})])
        style.map('Resources.Treeview',background=[('selected',INPUT)],foreground=[('selected',TXT)])
        self.tree=ttk.Treeview(sidebar,show='tree',style='Resources.Treeview',selectmode='browse')
        self.tree.column('#0',width=170,minwidth=60)
        attach_scrollbar(sidebar,self.tree)
        self.tree.pack(fill='both',expand=True)
        self.tree.bind('<<TreeviewSelect>>',self._tree_select)
        self.tree.bind('<<TreeviewOpen>>',self._tree_open)
        self.tree.bind('<Button-3>',self._tree_context)
        self.tree.bind('<Control-KeyPress>',self.shortcut)
        body.add(sidebar,minsize=100,width=180)
        self.scroll_area=ScrollableArea(body,bg=PANEL)
        body.add(self.scroll_area,minsize=120,stretch='always')
        self.scrollbar=self.scroll_area.scrollbar
        self.scroll_area.content.bind('<Configure>',self.layout,add='+')
        for widget in (self.scroll_area.canvas,self.scroll_area.content):
            widget.bind('<Button-3>',self._blank_context)
            widget.bind('<Button-1>',lambda event:(self.select_file(None),event.widget.focus_set()))
            widget.bind('<Control-KeyPress>',self.shortcut)

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

    def _directories(self,path):
        return sorted((child for child in path.iterdir() if child.is_dir()
                       and self.assets in child.resolve().parents),key=lambda child:child.name.casefold())

    def _add_folder(self,parent,path):
        node=self.tree.insert(parent,'end',text=path.name,open=path==self.assets)
        self._tree_paths[node]=path
        if self._directories(path):self.tree.insert(node,'end',text='')
        return node

    def _populate(self,node):
        path=self._tree_paths.get(node)
        if path is None:return
        children=self.tree.get_children(node)
        if children and children[0] not in self._tree_paths:
            self.tree.delete(*children)
            for child in self._directories(path):self._add_folder(node,child)

    def _tree_open(self,_event=None):
        try:self._populate(self.tree.focus())
        except OSError as exc:self.location.config(text=str(exc))

    def _tree_select(self,_event=None):
        selection=self.tree.selection()
        if selection and selection[0] in self._tree_paths:
            path=self._tree_paths[selection[0]]
            if path!=self.folder:self.open_folder(path)

    def open_folder(self,path):
        try:
            path=self._inside(path)
            if not path.is_dir():raise FileNotFoundError(str(path))
            self.folder=path
            self._show_files()
            node=next(iter(self.tree.get_children()),None)
            if node is not None:
                for part in path.relative_to(self.assets).parts:
                    self._populate(node)
                    self.tree.item(node,open=True)
                    node=next(child for child in self.tree.get_children(node)
                              if self._tree_paths[child].name==part)
                self.tree.selection_set(node)
                self.tree.focus(node)
                self.tree.see(node)
        except (OSError,ValueError) as exc:self.location.config(text=str(exc))

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self._tree_paths={}
        try:
            if self.assets and self.assets.is_dir():
                node=self._add_folder('',self.assets)
                self._populate(node)
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
            self.tiles[path].bind('<Control-KeyPress>',self.shortcut)
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
        # Tree folders may be outside the currently displayed directory.
        self.select_file(None)
        self._selected=path
        self.context(event)

    def _operation(self,operation):
        try:
            if not self.before_change():return
            result=operation(AssetFiles(self.project))
            self.refresh()
            if result in self.tiles:self.select_file(result)
            self.scroll_area.canvas.focus_set()
            self.on_changed()
        except (OSError,ValueError) as exc:
            messagebox.showerror(tr('resources.title'),str(exc),parent=self.winfo_toplevel())

    def create_resource(self,script=False):
        if self.folder is None:return
        dialog=ResourceNameDialog(self,script)
        self.wait_window(dialog)
        if dialog.result is not None:
            self._operation(lambda files:files.create(self.folder,dialog.result,script))

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
            self._operation(lambda files:files.delete(path))

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
        try:self.menu.tk_popup(event.x_root,event.y_root)
        finally:self.menu.grab_release()
