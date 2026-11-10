"""Responsive dark file tiles for resources of the selected item."""
import tkinter as tk
from tkinter import messagebox
from gothic_editor.core.localization import tr
from gothic_editor.core.resources import item_resource_files, open_in_editor, open_in_folder
from gothic_editor.ui.widgets import BG, PANEL, MUTED, INPUT, TXT, label
from gothic_editor.ui.widgets.panel import Panel, ScrollableArea
from gothic_editor.ui.widgets.file_tile import FileTile


class ResourcesPanel(Panel):
    def __init__(self,parent,get_editor,on_hide):
        super().__init__(parent,bg=BG)
        self.project=self.item=self.menu=self._selected=None
        self.paths={}
        self.tiles={}
        self.columns=0
        self.get_editor=get_editor
        header=tk.Frame(self,bg=PANEL)
        header.pack(fill='x')
        self.location=label(header,tr('resources.select_item'),fg=MUTED,anchor='w')
        self.location.pack(side='left',fill='x',expand=True,padx=10)
        self.add_button('×',on_hide,parent=header).pack(side='right')
        self.add_button(tr('resources.refresh'),self.refresh,parent=header).pack(side='right',padx=6)
        self.scroll_area=ScrollableArea(self)
        self.scrollbar=self.scroll_area.scrollbar
        self.scroll_area.pack(fill='both',expand=True)
        self.scroll_area.content.bind('<Configure>',self.layout,add='+')

    def set_item(self,project,item):
        self.project,self.item=project,item
        self.refresh()

    def refresh(self):
        selected=self._selected
        for tile in self.tiles.values():tile.destroy()
        self.paths={}
        self.tiles={}
        self._selected=None
        self.columns=0
        if self.project is None or self.item is None:
            self.location.config(text=tr('resources.select_item'))
            return
        try:
            folder,files=item_resource_files(self.project,self.item.instance)
            if not files and self.item.path.is_file():
                folder,files=self.item.path.parent,[self.item.path]
            self.location.config(text=str(folder) if files else tr('resources.empty',path=str(folder)))
            for index,path in enumerate(files):
                self.paths[str(index)]=path
                self.tiles[path]=FileTile(self.scroll_area.content,path,path.relative_to(folder).as_posix(),
                                         self.select_file,self.open_selected,self.context)
            self.layout()
            if selected in self.tiles:self.select_file(selected)
        except (OSError,ValueError) as exc:self.location.config(text=str(exc))

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
        try:open_in_editor(self._selected,self.get_editor(),self.project)
        except (OSError,ValueError) as exc:
            messagebox.showerror(tr('resources.title'),str(exc),parent=self.winfo_toplevel())

    def reveal_selected(self):
        if self._selected is None:return
        try:open_in_folder(self._selected)
        except OSError as exc:
            messagebox.showerror(tr('resources.title'),str(exc),parent=self.winfo_toplevel())

    def context(self,event):
        if self.menu is not None:self.menu.destroy()
        self.menu=tk.Menu(self,tearoff=False,bg=INPUT,fg=TXT)
        self.menu.add_command(label=tr('resources.open'),command=self.open_selected)
        self.menu.add_command(label=tr('resources.reveal'),command=self.reveal_selected)
        try:self.menu.tk_popup(event.x_root,event.y_root)
        finally:self.menu.grab_release()
