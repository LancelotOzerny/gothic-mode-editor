"""Gothic Editor desktop entry — orchestrates views and repository."""
from __future__ import annotations
import os,tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog,messagebox,ttk,simpledialog
from .core.project import ProjectRepository
from .ui.widgets import BG,PANEL,TXT,MUTED,label
from .ui.hierarchy import HierarchyPanel
from .ui.properties import PropertiesPanel
from .ui.viewer import ModelViewer,read_3ds,MeshFormatError
from .core.localization import localization,tr
from .core.settings import EditorSettings,SettingsStore,field_key
from .core.settings_schema import all_fields
from .ui.settings import SettingsWindow
from .core.archive_models import load_archive_model

class EditorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings_store=SettingsStore()
        self.settings=self.settings_store.load()
        localization.set_language(self.settings.get_value('interface.general.language'))
        self.settings_window=None
        self.title('Gothic Editor — 0.2')
        width,height=self.settings.get_value('interface.general.window_size')
        self.geometry(f'{max(870,width)}x{max(540,height)}');self.minsize(870,540)
        self.configure(bg=BG)
        self.repo=ProjectRepository()
        self.current=None
        self._model_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='model-loader')
        self._model_future=None
        self._model_poll=None
        self._build_menu();self._build_layout()
        self.bind('<Control-o>',lambda e:self.open_project())
        self.bind('<Control-s>',lambda e:self.properties.save())

    def _build_menu(self):
        previous=getattr(self,'main_menu',None)
        menu=tk.Menu(self)
        file=tk.Menu(menu,tearoff=False)
        file.add_command(label=tr('app.create_project'),command=self.create_project)
        file.add_command(label=tr('app.open_project'),command=self.open_project,accelerator='Ctrl+O')
        file.add_separator();file.add_command(label=tr('app.refresh'),command=self.refresh)
        file.add_separator();file.add_command(label=tr('app.exit'),command=self.destroy)
        menu.add_cascade(label=tr('app.file'),menu=file)
        project=tk.Menu(menu,tearoff=False)
        project.add_command(label=tr('menu.settings'),command=self.show_settings)
        menu.add_cascade(label=tr('app.project'),menu=project)
        self.config(menu=menu)
        self.main_menu=menu
        if previous is not None:previous.destroy()

    def _build_layout(self):
        header=tk.Frame(self,bg=BG);header.pack(fill='x',padx=14,pady=12)
        label(header,tr('app.mode'),bg=BG,font=('Arial',11)).pack(side='left',padx=(0,10))
        self.mode=ttk.Combobox(header,values=[tr('app.items')],state='readonly',width=19)
        self.mode.current(0);self.mode.pack(side='left')
        self.project_label=label(header,tr('app.no_project'),bg=BG,fg=MUTED,anchor='e')
        self.project_label.pack(side='right',fill='x',expand=True)
        panes=tk.PanedWindow(self,orient='horizontal',bg=BG,bd=0,sashwidth=7)
        panes.pack(fill='both',expand=True,padx=9,pady=(0,8))
        self.hierarchy=HierarchyPanel(panes,self.select,self.create_item,self.duplicate,self.delete,self.rename)
        panes.add(self.hierarchy,width=300,minsize=225)
        middle=tk.Frame(panes,bg='#191e29')
        panes.add(middle,width=550,minsize=250)
        self.viewer=ModelViewer(middle)
        self.viewer.pack(fill='both',expand=True)
        self.properties=PropertiesPanel(panes,self.save_fields)
        panes.add(self.properties,width=350,minsize=240)
        self.status=tk.StringVar(value=tr('messages.start'))
        label(self,textvariable=self.status,bg=BG,fg=MUTED,anchor='w').pack(fill='x',padx=14,pady=(0,8))

    def need_project(self):
        if self.repo.root is None:
            messagebox.showinfo(tr('app.project'),tr('app.need_project'))
            return False
        return True

    def create_project(self):
        base=filedialog.askdirectory(title=tr('app.choose_project_folder'))
        if not base:return
        name=simpledialog.askstring(tr('app.new_project'),tr('app.project_name'),initialvalue=Path(base).name,parent=self)
        if not name:return
        try:self.repo.create(Path(base),name);self.show_project()
        except Exception as exc:messagebox.showerror(tr('app.create_error'),str(exc))

    def open_project(self):
        base=filedialog.askdirectory(title=tr('app.choose_existing_project'))
        if not base:return
        try:self.repo.open(Path(base));self.show_project()
        except Exception as exc:messagebox.showerror(tr('app.open_error'),str(exc))

    def show_project(self):
        self._cancel_model_load()
        self.current=None
        self.project_label.config(text=f'{self.repo.name}   |   {self.repo.root}')
        self.update_hierarchy()
        self.viewer.set_mesh(caption=tr('app.select_item'))
        self.properties.show(None)

    def show_settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        localization.reload()
        project_values={'resources.gothic.game_path':str(self.repo.game) if self.repo.game else ''}
        self.settings_window=SettingsWindow(self,self.settings,project_values,self.apply_settings)

    def apply_settings(self,values):
        settings=EditorSettings({field_key(field):values[field_key(field)]
                                 for field in all_fields() if field.scope=='application'})
        width,height=settings.get_value('interface.general.window_size')
        if width<870 or height<540:
            raise ValueError(tr('settings.invalid',name=tr('settings.items.window_size')))
        game_path=values['resources.gothic.game_path'].strip()
        game=Path(game_path).resolve() if game_path else None
        if self.repo.root is not None:
            game=self.repo.validate_game_path(game_path)
        old_language=localization.language_code
        self.settings_store.save(settings)
        resources_changed=self.repo.root is not None and self.repo.game!=game
        try:
            if resources_changed:self.repo.set_game_path(game_path)
        except OSError:
            self.settings_store.save(self.settings)
            raise
        self.settings=settings
        localization.set_language(settings.get_value('interface.general.language'))
        self.geometry(f'{max(870,width)}x{max(540,height)}')
        if old_language!=localization.language_code:
            self._rebuild_translated_ui()
        elif resources_changed:
            self.show_project()

    def _rebuild_translated_ui(self):
        # Keep the current selection, filters, unsaved fields and camera on language change.
        current=self.current
        drafts={key:entry.get() for key,entry in self.properties.inputs.items()}
        expanded=dict(self.hierarchy.expanded)
        query=self.hierarchy.search.get()
        camera=(self.viewer.angle_x,self.viewer.angle_y,self.viewer.zoom)
        for child in self.winfo_children():
            if not isinstance(child,(tk.Menu,tk.Toplevel)):child.destroy()
        self._build_menu();self._build_layout()
        self.hierarchy.expanded=expanded
        self.hierarchy.search.set(query)
        if self.repo.root is not None:
            self.show_project()
            if current is not None:
                current=next((item for item in self.repo.items if item.instance==current.instance),None)
                if current is not None:
                    self.hierarchy.choose(current);self.select(current,camera=camera)
                    for key,value in drafts.items():
                        if key in self.properties.inputs:
                            entry=self.properties.inputs[key]
                            entry.delete(0,'end');entry.insert(0,value)
                    self.viewer.angle_x,self.viewer.angle_y,self.viewer.zoom=camera
                    self.viewer.draw()

    def refresh(self):
        if not self.need_project():return
        self._cancel_model_load()
        try:
            self.repo.refresh();self.update_hierarchy()
            if self.current is not None:self.select(self.current)
        except Exception as exc:messagebox.showerror(tr('app.refresh_error'),str(exc))

    def update_hierarchy(self):
        self.hierarchy.set_items(self.repo.items)
        project_count=sum(x.origin=='project' for x in self.repo.items)
        self.status.set(tr('messages.stats',total=len(self.repo.items),project=project_count,models=len(self.repo.mesh_index),archived=len(self.repo.archive_models.entries),errors=len(self.repo.errors)))

    def select(self,item,camera=None):
        self._cancel_model_load()
        self.current=item
        self.properties.show(item)
        visual=item.visual
        name=Path(visual.replace('\\','/')).name.lower() if visual else ''
        source_name=str(Path(name).with_suffix('.3ds')) if Path(name).suffix=='.mrm' else name
        mesh=self.repo.mesh_index.get(source_name)
        if mesh is not None and not mesh.is_file():mesh=None
        if mesh is None:
            entry=self.repo.archive_models.find(visual) if visual else None
            if entry is None:
                self.viewer.set_mesh(caption=tr('messages.no_mesh',visual=visual or tr('viewer.no_visual')))
                return
            self.viewer.set_mesh(caption=tr('viewer.loading',name=entry.name))
            future=self._model_executor.submit(load_archive_model,entry)
            self._model_future=future
            self._model_poll=self.after(20,lambda:self._finish_archive_model(future,entry,camera))
            return
        try:
            verts,faces=read_3ds(mesh)
            self.viewer.set_mesh(verts,faces,caption=mesh.name)
            if camera is not None:
                self.viewer.angle_x,self.viewer.angle_y,self.viewer.zoom=camera
                self.viewer.draw()
        except (OSError,MeshFormatError,ValueError) as exc:
            self.viewer.set_mesh(caption=tr('messages.mesh_error',error=str(exc)))

    def _finish_archive_model(self,future,entry,camera=None):
        if future is not self._model_future:return
        self._model_poll=None
        if not future.done():
            self._model_poll=self.after(20,lambda:self._finish_archive_model(future,entry,camera))
            return
        self._model_future=None
        try:
            verts,faces=future.result()
            self.viewer.set_mesh(verts,faces,caption=f'{entry.archive.name} / {entry.name}')
            if camera is not None:
                self.viewer.angle_x,self.viewer.angle_y,self.viewer.zoom=camera
                self.viewer.draw()
        except (OSError,ValueError) as exc:
            self.viewer.set_mesh(caption=tr('messages.mesh_error',error=str(exc)))

    def _cancel_model_load(self):
        if self._model_poll is not None:
            self.after_cancel(self._model_poll)
            self._model_poll=None
        if self._model_future is not None:
            self._model_future.cancel()
            self._model_future=None

    def destroy(self):
        if hasattr(self,'_model_executor'):
            self._cancel_model_load()
            self._model_executor.shutdown(wait=False,cancel_futures=True)
        super().destroy()

    def _action(self,method,*args):
        if not self.need_project():return
        try:
            result=method(*args)
            self.update_hierarchy()
            if result is not None:
                self.hierarchy.choose(result);self.select(result)
            return result
        except Exception as exc:
            messagebox.showerror(tr('app.error'),str(exc))

    def create_item(self,key):self._action(self.repo.create_item,key)
    def duplicate(self,item):self._action(self.repo.duplicate,item)

    def delete(self,item):
        if item.origin!='project':return
        if not messagebox.askyesno(tr('app.delete_item'),tr('messages.delete',instance=item.instance)):
            return
        self._action(self.repo.delete,item)
        self._cancel_model_load()
        self.current=None;self.properties.show(None);self.viewer.set_mesh(caption=tr('app.select_item'))

    def rename(self,item,new_name):
        # The Daedalus name attribute is the in-game name, not INSTANCE.
        escaped=new_name.replace('\\','\\\\').replace('"','\\"')
        self.save_fields(item,{'name':'"'+escaped+'"'})

    def save_fields(self,item,values):
        self._action(self.repo.edit,item,values)


def main():EditorApp().mainloop()
