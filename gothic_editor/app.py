"""Gothic Editor desktop entry — orchestrates views and repository."""
from __future__ import annotations
import os,tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog,messagebox,ttk
from .core.project import ProjectRepository
from .ui.widgets import BG,PANEL,TXT,MUTED,label,Tooltip
from .ui.hierarchy import HierarchyPanel
from .ui.properties import PropertiesPanel
from .ui.viewer import ModelViewer,read_3ds,MeshFormatError
from .core.localization import localization,tr
from .core.settings import EditorSettings,SettingsStore,field_key
from .core.settings_schema import all_fields
from .ui.settings import SettingsWindow
from .core.archive_models import load_archive_model
from .core.model_export import export_model_3ds
from .core.project_tools import ProjectTools
from .ui.terminal import TerminalPanel,ToolRunner
from .ui.icons import IconImages
from .ui.bottom_dock import BottomDock
from .ui.resources import ResourcesPanel
from .core.recent_projects import RecentProjects
from .core.categories import classify
from .ui.welcome import WelcomeScreen
from .ui.project_dialog import NewProjectDialog
from .ui.item_dialog import AddItemDialog
from .ui.item_appearance import ItemAppearanceController

RESOURCE_KEYS={'game_path':'resources.gothic.game_path','compiler_path':'build.compiler.path',
               'resource_editor_path':'resources.editor.path'}

class EditorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.settings_store=SettingsStore()
        self.settings=self.settings_store.load()
        self.recent_projects=RecentProjects(self.settings_store.path.with_name('recent_projects.json'))
        self.welcome=None
        localization.set_language(self.settings.get_value('interface.general.language'))
        self.settings_window=None
        self._dock_resize_after=None
        self._bottom_tab_specs={}
        self._bottom_tab_variables={}
        self.register_bottom_tab('terminal','terminal.title',lambda parent:TerminalPanel(parent,self.hide_terminal))
        self.register_bottom_tab('resources','resources.title',lambda parent:ResourcesPanel(
            parent,lambda:self.repo.resource_editor_path,lambda:self.hide_bottom_tab('resources')))
        self.terminal_visible=self._bottom_tab_variables['terminal']
        self.resources_visible=self._bottom_tab_variables['resources']
        self.terminal_visible.set(True)
        self.resources_visible.set(True)
        self.terminal_height=self.settings.get_value('interface.terminal.height')
        self.icons=IconImages(self)
        self._tool_runner=ToolRunner(self,lambda message:self.terminal.append(message),self._tool_completed)
        self.title('Gothic Editor — 0.2')
        width,height=self.settings.get_value('interface.general.window_size')
        width,height=max(870,width),max(540,height)
        x=max(0,(self.winfo_screenwidth()-width)//2)
        y=max(0,(self.winfo_screenheight()-height)//2)
        self.geometry(f'{width}x{height}+{x}+{y}');self.minsize(870,540)
        self.configure(bg=BG)
        self.repo=ProjectRepository({key:self.settings.values[value] for key,value in RESOURCE_KEYS.items()
                                     if value in self.settings.values})
        game_path=self.settings.get_value(RESOURCE_KEYS['game_path'])
        self.repo.game=Path(game_path).resolve() if game_path else None
        self.repo.compiler_path=self.settings.get_value(RESOURCE_KEYS['compiler_path'])
        self.repo.resource_editor_path=self.settings.get_value(RESOURCE_KEYS['resource_editor_path'])
        self.current=None
        self.appearance=ItemAppearanceController(self)
        self._model_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='model-loader')
        self._model_future=None
        self._model_poll=None
        self._build_menu();self._build_layout()
        self.show_welcome()
        self.bind('<Control-o>',lambda e:self.open_project())
        self.bind('<Control-s>',lambda e:self.properties.save())
        self.deiconify()
        if os.name=='nt':self.state('zoomed')
        else:
            try:self.attributes('-zoomed',True)
            except tk.TclError:pass

    def _build_menu(self):
        previous=getattr(self,'main_menu',None)
        menu=tk.Menu(self)
        file=tk.Menu(menu,tearoff=False)
        file.add_command(label=tr('app.create_project'),command=self.create_project)
        file.add_command(label=tr('app.open_project'),command=self.open_project,accelerator='Ctrl+O')
        self.recent_menu=tk.Menu(file,tearoff=False)
        file.add_cascade(label=tr('welcome.menu_recent'),menu=self.recent_menu)
        self._update_recent_menu()
        file.add_separator();file.add_command(label=tr('app.refresh'),command=self.refresh)
        file.add_separator();file.add_command(label=tr('app.exit'),command=self.destroy)
        menu.add_cascade(label=tr('app.file'),menu=file)
        project=tk.Menu(menu,tearoff=False)
        project.add_command(label=tr('menu.settings'),command=self.show_settings)
        menu.add_cascade(label=tr('app.project'),menu=project)
        view=tk.Menu(menu,tearoff=False)
        windows=tk.Menu(view,tearoff=False)
        for key,(title_key,_) in self._bottom_tab_specs.items():
            windows.add_checkbutton(label=tr(title_key),variable=self._bottom_tab_variables[key],
                                    command=lambda current=key:self.toggle_bottom_tab(current))
        view.add_cascade(label=tr('menu.windows'),menu=windows)
        menu.add_cascade(label=tr('menu.view'),menu=view)
        self.tools_menu=tk.Menu(menu,tearoff=False)
        for action in ('compile','sync','launch','build_and_run'):
            self.tools_menu.add_command(label=tr('pipeline.'+action),
                command=lambda current=action:self.run_project_tool(current))
        menu.add_cascade(label=tr('tools.title'),menu=self.tools_menu)
        self.config(menu=menu)
        self.main_menu=menu
        if previous is not None:previous.destroy()

    def _build_layout(self):
        self.editor_frame=tk.Frame(self,bg=BG)
        self.editor_frame.pack(fill='both',expand=True)
        header=tk.Frame(self.editor_frame,bg=BG);header.pack(fill='x',padx=14,pady=12)
        header.columnconfigure(0,weight=1,uniform='header_side')
        header.columnconfigure(2,weight=1,uniform='header_side')
        mode_frame=tk.Frame(header,bg=BG);mode_frame.grid(row=0,column=0,sticky='w')
        label(mode_frame,tr('app.mode'),bg=BG,font=('Arial',11)).pack(side='left',padx=(0,10))
        self.mode=ttk.Combobox(mode_frame,values=[tr('app.items')],state='readonly',width=19)
        self.mode.current(0);self.mode.pack(side='left')
        actions=tk.Frame(header,bg=BG);actions.grid(row=0,column=1,padx=16)
        self.play_button=tk.Button(actions,image=self.icons.frames('build.png',26,'#62d785',BG)[0],bg=BG,
                                   activebackground=PANEL,activeforeground='#89eda5',relief='flat',
                                   text=tr('pipeline.build_and_run'),compound='left',
                                   cursor='hand2',command=lambda:self.run_project_tool('build_and_run'))
        self.play_button.pack(side='left',padx=(0,8))
        self.sync_button=tk.Button(actions,image=self.icons.frames('sync.png',26,'#80b4f9',BG)[0],bg=BG,
                                   activebackground=PANEL,relief='flat',cursor='hand2',
                                   command=lambda:self.run_project_tool('sync'))
        self.sync_button.pack(side='left')
        Tooltip(self.play_button,tr('pipeline.build_and_run'))
        Tooltip(self.sync_button,tr('tools.sync'))
        self.project_label=label(header,tr('app.no_project'),bg=BG,fg=MUTED,anchor='e',width=1)
        self.project_label.grid(row=0,column=2,sticky='ew')
        self._update_tool_buttons()
        self.workspace=tk.PanedWindow(self.editor_frame,orient='vertical',bg=BG,bd=0,sashwidth=7,opaqueresize=True)
        self.workspace.pack(fill='both',expand=True,padx=9,pady=(0,8))
        panes=tk.PanedWindow(self.workspace,orient='horizontal',bg=BG,bd=0,sashwidth=7)
        self.workspace.add(panes,minsize=160,stretch='always')
        self.hierarchy=HierarchyPanel(panes,self.select,self.create_item,self.duplicate,self.delete,self.rename,on_copy=self.copy_to_project,on_export_model=self.export_model)
        panes.add(self.hierarchy,width=300,minsize=225)
        middle=tk.Frame(panes,bg='#191e29')
        panes.add(middle,width=550,minsize=250)
        self.viewer=ModelViewer(middle)
        self.viewer.pack(fill='both',expand=True)
        self.properties=PropertiesPanel(panes,self.save_fields,on_appearance=self.appearance.show)
        panes.add(self.properties,width=350,minsize=240)
        self.bottom_dock=BottomDock(self.workspace)
        for key,(title_key,factory) in self._bottom_tab_specs.items():
            self.bottom_dock.register(key,tr(title_key),factory(self.bottom_dock))
        self.terminal=self.bottom_dock.panels['terminal']
        self.resources=self.bottom_dock.panels['resources']
        for key,variable in self._bottom_tab_variables.items():
            if variable.get():self.toggle_bottom_tab(key)
        self.workspace.bind('<ButtonRelease-1>',lambda _:self.after_idle(self._remember_terminal_height))
        self.workspace.bind('<Configure>',lambda _:self._schedule_dock_resize() if self.bottom_dock.visible_keys() else None)
        self.status=tk.StringVar(value=tr('messages.start'))
        self._tool_runner.on_progress=lambda message:self.status.set(message)
        label(self.editor_frame,textvariable=self.status,bg=BG,fg=MUTED,anchor='w').pack(fill='x',padx=14,pady=(0,8))

    def _update_recent_menu(self):
        self.recent_menu.delete(0,'end')
        for entry in self.recent_projects.entries[:5]:
            self.recent_menu.add_command(label=f'{entry.name} — {entry.path}',
                                         command=lambda path=entry.path:self.open_project_path(path))
        if not self.recent_projects.entries:
            self.recent_menu.add_command(label=tr('welcome.empty'),state='disabled')

    def _remember_project(self):
        # Adopt legacy per-project resources once; subsequent projects use the
        # application values, including explicitly cleared paths.
        resources={'game_path':str(self.repo.game) if self.repo.game else '',
                   'compiler_path':self.repo.compiler_path,'resource_editor_path':self.repo.resource_editor_path}
        for key in ('compiler_path','resource_editor_path'):
            if resources[key]:resources[key]=str((self.repo.root/Path(resources[key])).resolve())
        try:
            for key,value in resources.items():self.settings.values[RESOURCE_KEYS[key]]=value
            self.settings_store.save(self.settings)
            self.repo.shared_resources.update(resources)
            self.repo.compiler_path=resources['compiler_path']
            self.repo.resource_editor_path=resources['resource_editor_path']
        except OSError as exc:self.terminal.append(str(exc))
        try:self.recent_projects.remember(self.repo.root,self.repo.name)
        except OSError as exc:self.terminal.append(tr('welcome.save_error',error=str(exc)))
        self._update_recent_menu()

    def show_welcome(self):
        self.editor_frame.pack_forget()
        if self.welcome is not None and self.welcome.winfo_exists():self.welcome.destroy()
        self.welcome=WelcomeScreen(self,self.recent_projects,self.create_project,
                                   self.open_project,self.open_project_path)
        self.welcome.pack(fill='both',expand=True)

    def _show_editor(self):
        if self.welcome is not None and self.welcome.winfo_exists():self.welcome.destroy()
        self.welcome=None
        self.editor_frame.pack(fill='both',expand=True)

    def need_project(self):
        if self.repo.root is None:
            messagebox.showinfo(tr('app.project'),tr('app.need_project'))
            return False
        return True

    def create_project(self,beside_recent=False):
        parent=self.recent_projects.parent_directory()
        dialog=NewProjectDialog(self,parent)
        self.wait_window(dialog)
        if dialog.result is None:return
        base,name=dialog.result
        try:
            self.repo.create(Path(base),name)
            self._remember_project()
            self.show_project(reset_hierarchy=True)
        except Exception as exc:messagebox.showerror(tr('app.create_error'),str(exc))

    def open_project(self):
        parent=self.recent_projects.parent_directory()
        options={'initialdir':str(parent)} if parent is not None else {}
        base=filedialog.askdirectory(title=tr('app.choose_existing_project'),**options)
        if not base:return
        self.open_project_path(Path(base))

    def open_project_path(self,path):
        try:
            self.repo.open(Path(path),confirm_migration=lambda count:messagebox.askyesno(
                tr('item_assets.migration_title'),tr('item_assets.migration_confirm',count=count),parent=self))
            self._remember_project()
            self.show_project(reset_hierarchy=True)
        except Exception as exc:messagebox.showerror(tr('app.open_error'),str(exc))

    def show_project(self,reset_hierarchy=False):
        self._show_editor()
        self._cancel_model_load()
        self.current=None
        self.project_label.config(text=f'{self.repo.name}   |   {self.repo.root}')
        if reset_hierarchy:self.hierarchy.collapse_all()
        self.update_hierarchy()
        self.viewer.set_mesh(caption=tr('app.select_item'))
        self.properties.show(None)
        self.resources.set_item(self.repo.root,None)
        self._update_tool_buttons()

    def _update_tool_buttons(self):
        running=self._tool_runner.running
        state='normal' if self.repo.root is not None and not running else 'disabled'
        self.play_button.config(state=state)
        self.sync_button.config(state=state)
        for index in range(4):self.tools_menu.entryconfig(index,state=state)

    def run_project_tool(self,action):
        self.show_terminal()
        if self._tool_runner.running:return
        if self.repo.root is None:
            self.terminal.append(tr('app.need_project'))
            return
        try:
            tools=ProjectTools(self.repo.root,self.repo.game,self.repo.compiler_path)
        except (OSError,ValueError) as exc:
            self.terminal.append(str(exc))
            self.status.set(tr('tools.failure'))
            return
        operations={'compile':tools.compile,'sync':tools.synchronize,'launch':tools.launch,'build_and_run':tools.build_and_run}
        operation=operations[action]
        title=tr('pipeline.'+action)
        self.status.set(tr('tools.running', action=title))
        self._tool_runner.start(title+' — '+self.repo.name,operation,
                                tools.logs_dir/'compile.log' if action in ('compile','build_and_run') else None)
        self._update_tool_buttons()

    def _tool_completed(self,success,result):
        self._update_tool_buttons()
        if success and getattr(result,'manual',False):
            self.status.set(tr('pipeline.manual_launch',name=result.output.name))
        else:self.status.set(tr('tools.success') if success else tr('tools.failure'))

    def register_bottom_tab(self,key,title_key,factory):
        """Register another dock panel; its factory receives the notebook parent."""
        if key in self._bottom_tab_specs:raise ValueError(f'Duplicate dock tab: {key}')
        self._bottom_tab_specs[key]=(title_key,factory)
        self._bottom_tab_variables[key]=tk.BooleanVar(self,value=False)
        if hasattr(self,'bottom_dock'):
            self.bottom_dock.register(key,tr(title_key),factory(self.bottom_dock))
            self._build_menu()

    def show_bottom_tab(self,key):
        self._bottom_tab_variables[key].set(True)
        self.toggle_bottom_tab(key)

    def hide_bottom_tab(self,key):
        self._bottom_tab_variables[key].set(False)
        self.toggle_bottom_tab(key)

    def show_terminal(self):
        self.show_bottom_tab('terminal')

    def hide_terminal(self):
        self.hide_bottom_tab('terminal')

    def toggle_terminal(self):
        self.toggle_bottom_tab('terminal')

    def toggle_bottom_tab(self,key):
        if self._bottom_tab_variables[key].get():self._show_editor()
        self.bottom_dock.set_visible(key,self._bottom_tab_variables[key].get())
        visible=str(self.bottom_dock) in tuple(map(str,self.workspace.panes()))
        if self.bottom_dock.visible_keys() and not visible:
            self.workspace.add(self.bottom_dock,height=self.terminal_height,minsize=80,stretch='never')
            self._schedule_dock_resize()
        elif not self.bottom_dock.visible_keys() and visible:
            self.workspace.forget(self.bottom_dock)
        if key=='resources' and self.resources_visible.get():self.resources.refresh()

    def _resize_terminal(self):
        if (self.bottom_dock.visible_keys() and len(self.workspace.panes())>1
                and str(self.bottom_dock) in tuple(map(str,self.workspace.panes()))):
            height=min(self.terminal_height,max(80,self.workspace.winfo_height()-167))
            self.workspace.sash_place(0,0,max(160,self.workspace.winfo_height()-height-7))

    def _cancel_dock_resize(self):
        if self._dock_resize_after is not None:
            self.after_cancel(self._dock_resize_after)
            self._dock_resize_after=None

    def _schedule_dock_resize(self):
        self._cancel_dock_resize()
        def resize():
            self._dock_resize_after=None
            self._resize_terminal()
        self._dock_resize_after=self.after_idle(resize)

    def _remember_terminal_height(self):
        if self.bottom_dock.visible_keys():
            self.terminal_height=max(80,min(2000,self.bottom_dock.winfo_height()))
            self.settings.values['interface.terminal.height']=self.terminal_height
            try:self.settings_store.save(self.settings)
            except OSError as exc:self.terminal.append(str(exc))

    def show_settings(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        localization.reload()
        project_values={**self.repo.project_settings,'resources.gothic.game_path':str(self.repo.game) if self.repo.game else '',
                        'build.compiler.path':self.repo.compiler_path,
                        'resources.editor.path':self.repo.resource_editor_path}
        self.settings_window=SettingsWindow(self,self.settings,project_values,self.apply_settings)

    def apply_settings(self,values):
        settings=EditorSettings({field_key(field):values[field_key(field)]
                                 for field in all_fields() if field.scope=='application'})
        width,height=settings.get_value('interface.general.window_size')
        if width<870 or height<540:
            raise ValueError(tr('settings.invalid',name=tr('settings.items.window_size')))
        game_path=values['resources.gothic.game_path'].strip()
        game,compiler_path,editor_path=self.repo.validate_configuration(
            game_path,values['build.compiler.path'],values['resources.editor.path'])
        settings.values.update({'resources.gothic.game_path':str(game) if game else '',
                                'build.compiler.path':compiler_path,'resources.editor.path':editor_path})
        old_language=localization.language_code
        hierarchy_changed=self.settings.get_value('project.hierarchy.display_mode')!=settings.get_value('project.hierarchy.display_mode')
        self.settings_store.save(settings)
        resources_changed=self.repo.root is not None and self.repo.game!=game
        previous_config=(self.repo.root/'project.json').read_bytes() if self.repo.root is not None else None
        previous_project_settings=dict(self.repo.project_settings)
        try:
            if self.repo.root is not None:
                self.repo.save_project_settings(values)
                from .core.mod_config import ModConfiguration
                ModConfiguration.load(self.repo.root)
            self.repo.set_configuration(game_path,compiler_path,editor_path)
        except (OSError,ValueError):
            if previous_config is not None:
                (self.repo.root/'project.json').write_bytes(previous_config)
                self.repo.project_settings=previous_project_settings
            self.settings_store.save(self.settings)
            raise
        self.settings=settings
        self.terminal_height=settings.get_value('interface.terminal.height')
        localization.set_language(settings.get_value('interface.general.language'))
        self.geometry(f'{max(870,width)}x{max(540,height)}')
        if old_language!=localization.language_code:
            self._rebuild_translated_ui()
        elif resources_changed:
            self.show_project()
        elif hierarchy_changed and self.repo.root is not None:
            self.update_hierarchy()
        if self.bottom_dock.visible_keys():self._schedule_dock_resize()

    def _rebuild_translated_ui(self):
        self._cancel_dock_resize()
        showing_welcome=self.welcome is not None and self.welcome.winfo_exists()
        # Keep the current selection, filters, unsaved fields and camera on language change.
        current=self.current
        drafts={key:entry.get() for key,entry in self.properties.inputs.items()}
        collapsed=dict(self.properties.collapsed)
        expanded=dict(self.hierarchy.expanded)
        query=self.hierarchy.search.get()
        camera=(self.viewer.angle_x,self.viewer.angle_y,self.viewer.zoom)
        terminal_text=self.terminal.log.get('1.0','end-1c')
        selected_tab=self.bottom_dock.selected_key()
        for child in self.winfo_children():
            if not isinstance(child,(tk.Menu,tk.Toplevel)):child.destroy()
        self._build_menu();self._build_layout()
        self.properties.collapsed=collapsed
        if terminal_text:self.terminal.append(terminal_text.rstrip('\n'))
        if selected_tab in self.bottom_dock.visible_keys():
            self.bottom_dock.select(self.bottom_dock.panels[selected_tab])
        self.hierarchy.expanded=expanded
        self.hierarchy.search.set(query)
        if self.repo.root is not None:
            self.show_project()
            if current is not None:
                current=next((item for item in self.repo.project_items+self.repo.game_items
                              if item.instance==current.instance and item.origin==current.origin),None)
                if current is not None:
                    self.hierarchy.choose(current);self.select(current,camera=camera)
                    for key,value in drafts.items():
                        if key in self.properties.inputs:
                            entry=self.properties.inputs[key]
                            if hasattr(entry,'set_expression'):entry.set_expression(value)
                            else:
                                entry.delete(0,'end');entry.insert(0,value)
                    self.viewer.angle_x,self.viewer.angle_y,self.viewer.zoom=camera
                    self.viewer.draw()
        elif showing_welcome:self.show_welcome()

    def refresh(self):
        if not self.need_project():return
        self._cancel_model_load()
        try:
            self.repo.refresh();self.update_hierarchy()
            if self.current is not None:self.select(self.current)
        except Exception as exc:messagebox.showerror(tr('app.refresh_error'),str(exc))

    def update_hierarchy(self):
        project_only=self.settings.get_value('project.hierarchy.display_mode')=='project_only'
        if project_only and self.current is not None and self.current.origin=='game':
            self.current=None
            self.hierarchy.selected=None
            self.properties.show(None)
            self.resources.set_item(self.repo.root,None)
            self._cancel_model_load()
            self.viewer.set_mesh(caption=tr('app.select_item'))
        self.hierarchy.set_items(self.repo.project_items if project_only else self.repo.items)
        project_count=sum(x.origin=='project' for x in self.repo.items)
        self.status.set(tr('messages.stats',total=len(self.repo.items),project=project_count,models=len(self.repo.mesh_index),archived=len(self.repo.archive_models.entries),errors=len(self.repo.errors)))

    def export_model(self,item):
        visual=item.visual
        name=Path(visual.replace('\\','/')).name if visual else item.instance
        destination=filedialog.asksaveasfilename(parent=self,title=tr('hierarchy.download_model_3ds'),
            initialfile=str(Path(name).with_suffix('.3ds')),defaultextension='.3ds',
            filetypes=[('3D Studio (*.3ds)','*.3ds')])
        if not destination:return
        try:
            converted=export_model_3ds(visual,self.repo.mesh_index,self.repo.archive_models,Path(destination))
        except (OSError,ValueError) as exc:
            messagebox.showerror(tr('app.error'),str(exc),parent=self)
            return
        self.status.set(tr('model_export.converted' if converted else 'model_export.saved',path=destination))

    def select(self,item,camera=None):
        self._cancel_model_load()
        self.current=item
        self.properties.show(item)
        self.resources.set_item(self.repo.root,item)
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
        if self._tool_runner.running:
            self.show_terminal()
            return
        self._tool_runner.close()
        self._cancel_dock_resize()
        if hasattr(self,'_model_executor'):
            self._cancel_model_load()
            self._model_executor.shutdown(wait=False,cancel_futures=True)
        super().destroy()

    def _action(self,method,*args,**kwargs):
        if not self.need_project():return
        try:
            result=method(*args,**kwargs)
            self.update_hierarchy()
            if result is not None:
                self.hierarchy.choose(result);self.select(result)
            return result
        except Exception as exc:
            messagebox.showerror(tr('app.error'),str(exc))

    def create_item(self,key):
        if not self.need_project():return
        dialog=AddItemDialog(self,key,self.repo.game_items)
        self.wait_window(dialog)
        if dialog.result is None:return
        action,value=dialog.result
        if action=='copy':self.copy_to_project(value)
        else:self._action(self.repo.create_item,key,value)
    def duplicate(self,item):self._action(self.repo.duplicate,item)
    def copy_to_project(self,item):self._action(self.repo.copy_to_project,item)

    def delete(self,item):
        if item.origin!='project':return
        if not messagebox.askyesno(tr('app.delete_item'),tr('messages.delete',instance=item.instance)):
            return
        self._action(self.repo.delete,item)
        self._cancel_model_load()
        self.current=None;self.properties.show(None);self.viewer.set_mesh(caption=tr('app.select_item'))
        self.resources.set_item(self.repo.root,None)

    def rename(self,item,new_name):
        if classify(item)!='potions':return
        # The Daedalus name attribute is the in-game name, not INSTANCE.
        escaped=new_name.replace('\\','\\\\').replace('"','\\"')
        self.save_fields(item,{'name':'"'+escaped+'"'})

    def save_fields(self,item,values,**options):
        if classify(item)!='potions':return
        self._action(self.repo.edit,item,values,**options)


def main():EditorApp().mainloop()
