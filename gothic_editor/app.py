"""Gothic Editor desktop entry — orchestrates views and repository."""
from __future__ import annotations
import os,tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog,messagebox,ttk
from . import __version__
from .core.project import ProjectRepository
from .core.edit_history import EditHistory
from .ui.events import EventBus
from .ui.widgets import BG,PANEL,TXT,MUTED,label,Tooltip
from .ui.widgets.form import create_field
from gothic_editor.ui.panels.hierarchy import HierarchyPanel
from gothic_editor.ui.panels.properties import PropertiesPanel
from gothic_editor.ui.panels.viewer import ModelViewer
from .core.localization import localization,tr
from .core.settings import EditorSettings,SettingsStore,field_key
from .core.settings_schema import all_fields
from gothic_editor.ui.windows.settings import SettingsWindow
from .core.model_preview import ModelPreviewCache
from .core.model_export import export_model_3ds,resolve_model_source,export_texture
from .ui.windows.value_choice import ValueChoiceWindow
from .ui.windows.spreadsheet import SpreadsheetWindow
from .core.project_tools import ProjectTools
from gothic_editor.ui.panels.terminal import TerminalPanel
from gothic_editor.ui.controllers.tool_runner import ToolRunner
from gothic_editor.ui.widgets.icons import IconImages
from gothic_editor.ui.widgets.dock import BottomDock
from gothic_editor.ui.panels.resources import ResourcesPanel
from gothic_editor.ui.panels.media import MediaPanel, MediaPropertiesPanel, MediaPreview
from gothic_editor.core.game_media import GameMedia
from gothic_editor.core.project_selection import ProjectSelection
from .core.recent_projects import RecentProjects
from .core.categories import classify, EDITABLE_CATEGORIES
from gothic_editor.ui.panels.welcome import WelcomeScreen
from gothic_editor.ui.windows.project_dialog import NewProjectDialog
from gothic_editor.ui.windows.item_dialog import AddItemDialog
from gothic_editor.ui.controllers.item_appearance import ItemAppearanceController
from gothic_editor.ui.controllers.world import WorldController
from gothic_editor.ui.panels.world import WorldPanel, WorldPropertiesPanel
from gothic_editor.ui.panels.npc import NpcPropertiesPanel
from gothic_editor.ui.panels.trading import TradingPanel
from gothic_editor.ui.widgets.buttons import PropertyButton
from gothic_editor.ui.controllers.npc import NpcController
from gothic_editor.ui.controllers.recipes import RecipeController
from gothic_editor.ui.panels.recipes import RecipeListPanel, RecipePropertiesPanel

RESOURCE_KEYS={'game_path':'resources.gothic.game_path','compiler_path':'build.compiler.path',
               'resource_editor_path':'resources.editor.path'}

class EditorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.withdraw()
        self.events=EventBus()
        self.events.subscribe('resources.changed',self._on_resource_event)
        self.events.subscribe('items.changed',self._on_item_event)
        self.events.subscribe('npc.changed',self._on_npc_event)
        self.events.subscribe('recipes.changed',self._on_recipe_event)
        self.events.subscribe('world.changed',self._on_world_event)
        self.settings_store=SettingsStore()
        self.settings=self.settings_store.load()
        self.recent_projects=RecentProjects(self.settings_store.path.with_name('recent_projects.json'))
        self.welcome=None
        self._welcome_map_after=None
        self._welcome_taskbar_ready=False
        self.bind('<Map>',self._welcome_mapped,add='+')
        localization.set_language(self.settings.get_value('interface.general.language'))
        self.settings_window=None
        self.spreadsheet_window=None
        self._media_loaded=set()
        self._media_resources=[]
        self._dock_resize_after=None
        self._bottom_tab_specs={}
        self._bottom_tab_variables={}
        self.register_bottom_tab('terminal','terminal.title',lambda parent:TerminalPanel(parent,self.hide_terminal))
        self.register_bottom_tab('resources','resources.title',lambda parent:ResourcesPanel(
            parent,lambda:self.repo.resource_editor_path,lambda:self.hide_bottom_tab('resources'),
            on_changed=lambda source,result:self.events.publish('resources.changed',(source,result)),
            before_change=lambda:self._save_editors(),
            history=lambda:self.history))
        self.terminal_visible=self._bottom_tab_variables['terminal']
        self.resources_visible=self._bottom_tab_variables['resources']
        self.terminal_visible.set(True)
        self.resources_visible.set(True)
        self.terminal_height=self.settings.get_value('interface.terminal.height')
        self.icons=IconImages(self)
        self._tool_runner=ToolRunner(self,lambda message:self.terminal.append(message),self._tool_completed)
        self.title(f'Gothic Editor — v{__version__}')
        width,height=self.settings.get_value('interface.general.window_size')
        width,height=max(870,width),max(540,height)
        x=max(0,(self.winfo_screenwidth()-width)//2)
        y=max(0,(self.winfo_screenheight()-height)//2)
        self._editor_geometry=f'{width}x{height}+{x}+{y}'
        self.geometry(self._editor_geometry);self.minsize(870,540)
        self.configure(bg=BG)
        self.repo=ProjectRepository({key:self.settings.values[value] for key,value in RESOURCE_KEYS.items()
                                     if value in self.settings.values})
        game_path=self.settings.get_value(RESOURCE_KEYS['game_path'])
        self.repo.game=Path(game_path).resolve() if game_path else None
        self.repo.compiler_path=self.settings.get_value(RESOURCE_KEYS['compiler_path'])
        self.repo.resource_editor_path=self.settings.get_value(RESOURCE_KEYS['resource_editor_path'])
        self.current=None
        self.history=EditHistory()
        self.appearance=ItemAppearanceController(self)
        self._model_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='model-loader')
        self._model_future=None
        self._model_poll=None
        self._preview_cache=ModelPreviewCache()
        self._build_menu();self._build_layout()
        self.show_welcome()
        self.bind('<Control-o>',lambda e:self.open_project())
        self.bind('<Control-KeyPress>',self._history_keypress,add='+')
        self.bind('<Control-s>',lambda e:self._save_editors())
        self.bind('<Control-KeyPress>',self._save_shortcut,add='+')
        self.bind('<Alt-F4>',lambda e:self.destroy())
        self.deiconify()

    def _save_editors(self):
        return (self.properties.save(automatic=True) and self.npcs.save() and self.recipes.save()
                and (not getattr(self,'trading_active',False) or self.trading_panel.save()))

    def _save_shortcut(self,event):
        if (event.keysym.lower() in ('s','cyrillic_yeru') or
                (event.keycode==83 and self.tk.call('tk','windowingsystem')=='win32')):
            self._save_editors()
            return 'break'

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
        for title,operation in (('Импорт','import'),('Экспорт','export')):
            submenu=tk.Menu(project,tearoff=False)
            submenu.add_command(label='xlsx',command=lambda current=operation:self.show_spreadsheet(current))
            project.add_cascade(label=title,menu=submenu)
        edit=tk.Menu(menu,tearoff=False)
        edit.add_command(label='Отменить',accelerator='Ctrl+Z',command=lambda:self.undo_redo(False))
        edit.add_command(label='Повторить',accelerator='Ctrl+Y',command=lambda:self.undo_redo(True))
        menu.add_cascade(label='Правка',menu=edit)
        menu.add_cascade(label=tr('app.project'),menu=project)
        view=tk.Menu(menu,tearoff=False)
        windows=tk.Menu(view,tearoff=False)
        for key,(title_key,_) in self._bottom_tab_specs.items():
            windows.add_checkbutton(label=tr(title_key),variable=self._bottom_tab_variables[key],
                                    command=lambda current=key:self.toggle_bottom_tab(current))
        view.add_cascade(label=tr('menu.windows'),menu=windows)
        menu.add_cascade(label=tr('menu.view'),menu=view)
        self.tools_menu=tk.Menu(project,tearoff=False)
        for action in ('compile','sync','launch','build_and_run'):
            self.tools_menu.add_command(label=tr('pipeline.'+action),
                command=lambda current=action:self.run_project_tool(current))
        project.add_cascade(label=tr('menu.build'),menu=self.tools_menu)
        self.config(menu=menu)
        self.main_menu=menu
        if previous is not None:previous.destroy()

    def show_spreadsheet(self,operation):
        if not self.need_project():return
        if self._tool_runner.running:
            self.show_terminal()
            return
        window=self.spreadsheet_window
        if window is not None and window.winfo_exists():
            window.lift()
            return
        if not self._save_editors():return
        self.spreadsheet_window=SpreadsheetWindow(self,self.repo,operation,self._spreadsheet_imported)

    def _spreadsheet_imported(self):
        instance=self.current.instance if self.current is not None else None
        self._cancel_model_load()
        self.properties.editor.reset()
        self.properties.show(None)
        self.current=None
        self.update_hierarchy()
        item=next((item for item in self.repo.items if item.instance==instance),None)
        if item is not None:
            self.hierarchy.choose(item)
            self.select(item)
        else:
            self.resources.set_item(self.repo.root,None)
            self.viewer.set_mesh(caption=tr('app.select_item'))

    def _build_layout(self):
        self.editor_frame=tk.Frame(self,bg=BG)
        self.editor_frame.pack(fill='both',expand=True)
        header=tk.Frame(self.editor_frame,bg=BG);header.pack(fill='x',padx=14,pady=12)
        header.columnconfigure(0,weight=1,uniform='header_side')
        header.columnconfigure(2,weight=1,uniform='header_side')
        self.trading_active=False
        self.workspace_tabs=tk.Frame(header,bg=BG)
        self.workspace_tabs.grid(row=1,column=0,columnspan=3,sticky='w',pady=(8,0))
        self.editor_tab=PropertyButton(self.workspace_tabs,self.close_trading,text='Редактор',height=32)
        self.editor_tab.pack(side='left',padx=(0,6))
        self.project_tab=PropertyButton(self.workspace_tabs,self.open_trading,text='Проект',height=32)
        self.project_tab.pack(side='left')
        self.editor_tab.set_selected(True)
        mode_frame=tk.Frame(header,bg=BG);mode_frame.grid(row=0,column=0,sticky='w')
        label(mode_frame,tr('app.mode'),bg=BG,font=('Arial',11)).pack(side='left',padx=(0,10))
        self.mode=create_field(mode_frame,'choice',options=((tr('app.items'),'items'),('Мир','world'),('Редактор мира','locations'),('NPC','npc'),(tr('recipes.title'),'recipes'),('Медиа','media')),caption=tr('app.mode'))
        self.mode.current(0);self.mode.pack(side='left')
        self.mode.bind('<<ComboboxSelected>>',lambda _:self._switch_resource_browser(self.mode.get()))
        actions=tk.Frame(header,bg=BG);actions.grid(row=0,column=1,padx=16)
        self.play_button=tk.Button(actions,image=self.icons.frames('build.png',26,'#62d785',BG)[0],bg=BG,
                                   activebackground=PANEL,activeforeground='#89eda5',relief='flat',
                                   cursor='hand2',command=lambda:self.run_project_tool('build_and_run'))
        self.play_button.pack(side='left')
        Tooltip(self.play_button,tr('pipeline.build_and_run'))
        self.project_label=label(header,tr('app.no_project'),bg=BG,fg=MUTED,anchor='e',width=1)
        self.project_label.grid(row=0,column=2,sticky='ew')
        self._update_tool_buttons()
        self.workspace=tk.PanedWindow(self.editor_frame,orient='vertical',bg=BG,bd=0,sashwidth=7,opaqueresize=True)
        self.workspace.pack(fill='both',expand=True,padx=9,pady=(0,8))
        panes=tk.PanedWindow(self.workspace,orient='horizontal',bg=BG,bd=0,sashwidth=7)
        self.editor_panes=panes
        self.workspace.add(panes,minsize=160,stretch='always')
        sidebar=tk.Frame(panes,bg=PANEL)
        self.editor_sidebar=sidebar
        panes.add(sidebar,width=300,minsize=225)
        self.hierarchy=HierarchyPanel(sidebar,self.select,self.create_item,self.duplicate,self.delete,self.rename,on_copy=self.copy_to_project,on_export_model=self.export_model,on_export_texture=self.export_item_texture)
        from .ui.controllers.item_hierarchy import ItemHierarchyController
        self.item_hierarchy_controller = ItemHierarchyController(self)
        self.hierarchy.on_node = self.item_hierarchy_controller.select
        self.hierarchy.on_node_action = self.item_hierarchy_controller.action
        self.hierarchy.on_import_category = self.item_hierarchy_controller.import_category
        self.hierarchy.on_move = self.item_hierarchy_controller.move
        self.hierarchy.before_select = self._save_editors
        self.hierarchy.on_multiple = self.item_hierarchy_controller.clear_inspector
        self.hierarchy.on_batch = self.item_hierarchy_controller.batch
        self.hierarchy.pack(fill='both',expand=True)
        self.world=WorldController(self)
        self.npcs=NpcController(self)
        self.recipes=RecipeController(self)
        self.recipe_list=RecipeListPanel(sidebar,self.recipes)
        self.world_panel=WorldPanel(sidebar,self.world.select,self.npcs.select)
        self.media_panel=MediaPanel(sidebar,self.select_media,self.load_media_category,self.import_media)
        middle=tk.Frame(panes,bg='#191e29')
        self.editor_middle=middle
        panes.add(middle,width=550,minsize=250)
        self.viewer=ModelViewer(middle)
        self.viewer.on_texture_mode=self._texture_mode_changed
        self.viewer.pack(fill='both',expand=True)
        self.media_viewer=MediaPreview(middle)
        self.trading_panel=TradingPanel(middle,self.npcs)
        self.location_viewer=None
        from .core.item_options import item_options
        inspector=tk.Frame(panes,bg=PANEL)
        self.editor_inspector=inspector
        panes.add(inspector,width=350,minsize=240)
        self.properties=PropertiesPanel(inspector,self.save_fields,on_appearance=self.appearance.show,
                                        options_provider=lambda source:item_options(self.repo,source))
        self.properties.pack(fill='both',expand=True)
        self.world_properties=WorldPropertiesPanel(inspector,self.world)
        self.npc_properties=NpcPropertiesPanel(inspector,self.npcs)
        self.recipe_properties=RecipePropertiesPanel(inspector,self.recipes)
        self.media_properties=MediaPropertiesPanel(inspector,self)
        self._show_resource_panels('items')
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
        self._welcome_taskbar_ready=False
        if self.welcome is None:
            if self.repo.root is not None:self._editor_geometry=self.geometry()
        self.attributes('-fullscreen',False)
        self.state('normal')
        self.configure(menu='')
        self.overrideredirect(True)
        self.title('Gothic Editor')
        self.minsize(720,480)
        self.resizable(False,False)
        x=max(0,(self.winfo_screenwidth()-720)//2)
        y=max(0,(self.winfo_screenheight()-480)//2)
        self.geometry(f'720x480+{x}+{y}')
        self.editor_frame.pack_forget()
        if self.welcome is not None and self.welcome.winfo_exists():self.welcome.destroy()
        self.welcome=WelcomeScreen(self,self.recent_projects,self.create_project,
                                   self.open_project,self.open_project_path,self._update_recent_menu)
        self.welcome.pack(fill='both',expand=True)

    def _welcome_mapped(self,event):
        if event.widget is self and self.welcome is not None:
            if self._welcome_map_after is not None:self.after_cancel(self._welcome_map_after)
            self._welcome_map_after=self.after_idle(self._activate_welcome)

    def _activate_welcome(self):
        self._welcome_map_after=None
        if self.welcome is None or not self.winfo_viewable() or self._welcome_taskbar_ready:return
        from gothic_editor.ui.platform import show_in_taskbar
        self._welcome_taskbar_ready=True
        try:show_in_taskbar(self)
        except OSError as exc:self.terminal.append(str(exc))
        self.lift()
        self.focus_force()

    def _show_editor(self):
        was_welcome=self.welcome is not None
        if self.welcome is not None and self.welcome.winfo_exists():self.welcome.destroy()
        self.welcome=None
        if was_welcome:
            self.attributes('-fullscreen',False)
            self.overrideredirect(False)
            self.configure(menu=self.main_menu)
            self.title('Gothic Editor — 0.2')
            self.resizable(True,True)
            self.minsize(870,540)
            self.geometry(self._editor_geometry)
            if self.repo.root is not None:
                if os.name=='nt':self.state('zoomed')
                else:
                    try:self.attributes('-zoomed',True)
                    except tk.TclError:pass
        self.editor_frame.pack(fill='both',expand=True)

    def need_project(self):
        if self.repo.root is None:
            messagebox.showinfo(tr('app.project'),tr('app.need_project'))
            return False
        return True

    def create_project(self,beside_recent=False):
        if not self._save_editors():return
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
        if not self._save_editors():return
        try:
            self.repo.open(Path(path),confirm_migration=lambda count:messagebox.askyesno(
                tr('item_assets.migration_title'),tr('item_assets.migration_confirm',count=count),parent=self))
            self._remember_project()
            self.show_project(reset_hierarchy=True)
        except Exception as exc:messagebox.showerror(tr('app.open_error'),str(exc))

    def show_project(self,reset_hierarchy=False):
        self._show_editor()
        if getattr(self,'trading_active',False):self.close_trading()
        self._cancel_model_load()
        self.current=None
        self.world.current=None
        self.npcs.deselect()
        self.recipes.deselect()
        self.recipe_properties.show(None)
        self.npcs.stamp=None
        self.world.catalog_stamp=None
        self._show_resource_panels('items')
        self.project_label.config(text=f'{self.repo.name}   |   {self.repo.root}')
        # A project can be attached before show_project() without passing
        # reset_hierarchy=True (e.g. embedded/project-restored workflows).
        # Never retain undo snapshots belonging to a different project.
        expected_history_root=(self.repo.root/'Assets').resolve() if self.repo.root else None
        if reset_hierarchy or self.history.root!=expected_history_root:
            self.history.reset(self.repo.root)
        if reset_hierarchy:
            self._media_loaded.clear()
            self._media_resources=[]
            self.media_panel.set_resources([],set())
            self.hierarchy.collapse_all()
        self.update_hierarchy()
        self.viewer.set_mesh(caption=tr('app.select_item'))
        self.properties.show(None)
        self.resources.set_item(self.repo.root,None)
        self.terminal.set_project(self.repo.root)
        self._update_tool_buttons()

    def _update_tool_buttons(self):
        running=self._tool_runner.running
        state='normal' if self.repo.root is not None and not running else 'disabled'
        self.play_button.config(state=state)
        for index in range(4):self.tools_menu.entryconfig(index,state=state)

    def run_project_tool(self,action):
        self.show_terminal()
        if self._tool_runner.running:return
        if self.repo.root is None:
            self.terminal.append(tr('app.need_project'))
            return
        if not self._save_editors():return
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
        if not self._save_editors():return
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
        if not self._save_editors():return
        previous_mode=self._resource_browser
        recipe_id=self.recipes.current['id'] if self.recipes.current else None
        self.recipes.deselect()
        npc_id=self.npcs.current.instance if self.npcs.current else None
        world_name=self.world.current.name if self.world.current else None
        self.npcs.deselect()
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
        terminal_state=self.terminal.detach()
        selected_tab=self.bottom_dock.selected_key()
        for child in self.winfo_children():
            if not isinstance(child,(tk.Menu,tk.Toplevel)):child.destroy()
        self._build_menu();self._build_layout()
        self.terminal.adopt(terminal_state)
        self.properties.collapsed=collapsed
        if terminal_text:self.terminal.append(terminal_text.rstrip('\n'))
        if selected_tab in self.bottom_dock.visible_keys():
            self.bottom_dock.select(self.bottom_dock.panels[selected_tab])
        self.hierarchy.expanded=expanded
        self.hierarchy.search.set(query)
        if self.repo.root is not None:
            self.show_project()
            if previous_mode in ('world','npc','recipes','media'):
                self._switch_resource_browser(previous_mode)
                if recipe_id:
                    recipe=next((value for value in self.recipes.items if value['id']==recipe_id),None)
                    if recipe:self.recipes.select(recipe)
                if npc_id:
                    npc=next((value for value in self.npcs.items if value.instance==npc_id),None)
                    if npc:self.npcs.select(npc)
                elif world_name:
                    resource=next((value for value in self.world.catalog if value.name==world_name),None)
                    if resource:self.world.select(resource,camera)
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
                            self.properties.editor.changed(key)
                    self.viewer.angle_x,self.viewer.angle_y,self.viewer.zoom=camera
                    self.viewer.draw()
        elif showing_welcome:self.show_welcome()

    def _on_resource_event(self,event):
        self._resource_files_changed(*event.payload)

    def _on_item_event(self,event):
        previous,updated,inserted=event.payload
        self.update_hierarchy(previous=previous,updated=updated,inserted=inserted)

    def _on_npc_event(self,event):
        npc,structural=event.payload
        if structural:self.npcs.show_list()
        elif npc is not None:self.world_panel.update_npc(npc)

    def _on_recipe_event(self,event):
        previous,updated,structural=event.payload
        if structural or updated is None:self.recipe_list.populate()
        else:self.recipe_list.update_recipe(previous,updated)

    def _on_world_event(self,event):
        kind,resource=event.payload
        if kind=='selection':
            self.world.refresh()
            return
        # Model replacements invalidate both the repository index and the catalog.
        self.repo.refresh()
        self.world.catalog_stamp=None
        self.world.refresh()
        self.resources.refresh()

    def _resource_files_changed(self, source=None, result=None):
        """Avoid rescanning Gothic and rebuilding the item hierarchy for plain assets.

        Script/item/model/world assets affect the repository indexes and still need
        a full project-only refresh. Texts and other independent resource files
        only invalidate option lists and cached previews.
        """
        from pathlib import Path
        root = self.repo.root
        if root is None:
            return
        assets = root / 'Assets'
        indexed_roots = {
            'items', 'models', 'worlds', 'world', 'locations', 'npc', 'npcs',
            'textures', 'animations', 'meshes',
        }
        for changed in (source, result):
            if changed is None:
                continue
            path = Path(changed)
            try:
                relative = path.relative_to(assets)
            except ValueError:
                self.refresh(project_only=True)
                return
            parts = [part.casefold() for part in relative.parts]
            if parts and (parts[0] in indexed_roots or
                          (parts[0] == 'scripts' and len(parts) > 1 and parts[1] == 'content')):
                self.refresh(project_only=True)
                return
        self.repo.options_cache.clear()
        self.repo.resource_revision += 1

    def refresh(self,project_only=False):
        if not self.need_project():return
        if not self._save_editors():return
        self._cancel_model_load()
        try:
            self.repo.refresh(project_only=project_only);self.update_hierarchy()
            if self._resource_browser=='recipes':self.recipes.load()
            if self._resource_browser in ('world','npc'):
                name=self.world.current.name if self.world.current else None
                npc_id=self.npcs.current.instance if self.npcs.current else None
                if self._resource_browser=='npc':self.npcs.show_list()
                else:self.world.refresh()
                resource=next((value for value in self.world.catalog if value.name==name),None)
                npc=next((value for value in self.npcs.items if value.instance==npc_id),None)
                if npc is not None:self.npcs.select(npc)
                elif resource is not None:self.world.select(resource)
                else:
                    self.world.current=None
                    self.npcs.deselect()
                    self.world_properties.show(None)
                    self._show_resource_panels(self._resource_browser)
                    self.viewer.set_mesh(caption='Выберите объект мира')
            if self.current is not None:
                updated=next((item for item in self.repo.items if item.instance.casefold()==self.current.instance.casefold()),None)
                if updated is not None:self.select(updated)
                else:
                    self.current=None
                    self.properties.show(None)
                    self.resources.set_item(self.repo.root,None)
                    self.viewer.set_mesh(caption=tr('app.select_item'))
        except Exception as exc:messagebox.showerror(tr('app.refresh_error'),str(exc))

    def update_hierarchy(self,previous=None,updated=None,inserted=None):
        self.hierarchy.store = self.repo.item_hierarchy
        project_only=self.settings.get_value('project.hierarchy.display_mode')=='project_only'
        if project_only and self.current is not None and self.current.origin=='game':
            self.current=None
            self.hierarchy.selected=None
            self.properties.show(None)
            self.resources.set_item(self.repo.root,None)
            self._cancel_model_load()
            self.viewer.set_mesh(caption=tr('app.select_item'))
        items=self.repo.project_items if project_only else self.repo.items
        if inserted is not None:self.hierarchy.insert_item(inserted,items)
        elif previous is not None and updated is not None:self.hierarchy.update_item(previous,updated,items)
        else:self.hierarchy.set_items(items)
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

    def export_item_texture(self,item):
        try:
            source=resolve_model_source(item.visual,self.repo.mesh_index,self.repo.archive_models)
            assets=source.parent if isinstance(source,Path) else None
            key=self._preview_cache.key(source,(self.repo.root,self.repo.resource_revision),True,assets)
            future=self._model_executor.submit(self._preview_cache.load,key,source,self.repo.root,self.repo.game,
                assets,dict(self.repo.archive_models.texture_entries),with_textures=True)
        except (OSError,ValueError) as exc:
            messagebox.showerror(tr('app.error'),str(exc),parent=self)
            return
        def finish():
            if not future.done():
                self.after(30,finish)
                return
            try:
                preview=future.result()
                names=list(preview.textures)
                if not names:raise ValueError('Текстуры модели не найдены')
            except (OSError,ValueError) as exc:
                messagebox.showerror(tr('app.error'),str(exc),parent=self)
                return
            def save(name):
                source=preview.texture_sources.get(name)
                types=[('TGA (*.tga)','*.tga')]
                if source and Path(source.name).suffix.lower()=='.tex':types.append(('Gothic TEX (*.tex)','*.tex'))
                destination=filedialog.asksaveasfilename(parent=self,title='Скачать текстуру',
                    initialfile=Path(name.replace('\\','/')).with_suffix('.tga').name,
                    defaultextension='.tga',filetypes=types)
                if not destination:return
                try:export_texture(preview.textures[name],source,destination)
                except (OSError,ValueError) as exc:messagebox.showerror(tr('app.error'),str(exc),parent=self)
            if len(names)==1:save(names[0])
            else:
                def choose(index):
                    window.destroy()
                    save(names[index])
                window=ValueChoiceWindow(self,[(name,name) for name in names],0,'Выберите текстуру',
                    choose,lambda:window.destroy())
                window.show()
        self.after(30,finish)

    def select(self,item,camera=None):
        if getattr(self.properties,"node",None) is not None and not self._save_editors():return
        if (self.npcs.current is not None or self.recipes.current is not None) and not self._save_editors():return
        if item is self.current and self.properties.current is item and camera is None:return
        previous=self.properties.current
        if previous is not None and item is not None and previous.path!=item.path:
            if not self._save_editors():
                self.hierarchy.choose(previous)
                return
        self._cancel_model_load()
        self.world.current=None
        self.npcs.deselect()
        self.recipes.deselect()
        # Switching items must not rebuild the active pane layout on every click.
        if self._resource_browser!='items':self._show_resource_panels('items')
        self.current=item
        self.properties.show(item)
        self.resources.set_item(self.repo.root,item)
        self._show_model(item,camera)

    def _show_model(self,item,camera=None):
        from .core.inventory_preview import rotation
        self.viewer.set_inventory_source(lambda:rotation(item.fields,classify(item),self.repo))
        self._cancel_model_load()
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
        else:
            entry=mesh
        self._show_model_source(entry,camera)

    def open_trading(self):
        if self.repo.root is None or self.npcs.current is None:
            self.terminal.append('Торговля: сначала выберите NPC в редакторе.')
            return
        if not self.npcs.save():return
        try:
            self.trading_panel.show(self.npcs.current)
        except (OSError,ValueError) as exc:
            self.terminal.append('Торговля: '+str(exc))
            self.show_terminal()
            return
        self.trading_active=True
        self.editor_tab.set_selected(False)
        self.project_tab.set_selected(True)
        self.viewer.pack_forget()
        self.media_viewer.pack_forget()
        self.editor_panes.paneconfigure(self.editor_middle,hide=False)
        self.editor_panes.paneconfigure(self.editor_inspector,hide=False)
        self.trading_panel.pack(fill='both',expand=True)

    def close_trading(self):
        if not getattr(self,'trading_active',False):return
        if not self.trading_panel.save():return
        self.trading_active=False
        self.trading_panel.pack_forget()
        self.editor_tab.set_selected(True)
        self.project_tab.set_selected(False)
        self._show_resource_panels(self._resource_browser)

    def _show_resource_panels(self,mode):
        if getattr(self,'trading_active',False):
            if not self.trading_panel.save():return
            self.trading_active=False
            self.trading_panel.pack_forget()
            self.editor_tab.set_selected(True)
            self.project_tab.set_selected(False)
        # Location editor uses the entire main area, keeping the terminal below.
        if mode=='locations':
            self._resource_browser=mode
            self.editor_panes.paneconfigure(self.editor_sidebar,hide=True)
            self.editor_panes.paneconfigure(self.editor_inspector,hide=True)
            self.editor_panes.paneconfigure(self.editor_middle,hide=False)
            self.viewer.pack_forget()
            self.media_viewer.pack_forget()
            if self.location_viewer is None:
                from gothic_editor.ui.windows.world_preview import WorldPreviewPanel
                self.location_viewer=WorldPreviewPanel(self.editor_middle,self.repo.game,
                                                        app=self)
            else:
                self.location_viewer.set_game(self.repo.game)
            self.location_viewer.pack(fill='both',expand=True)
            self.mode.set_expression(mode)
            return
        if self.location_viewer is not None:
            self.location_viewer.pack_forget()
        self.editor_panes.paneconfigure(self.editor_sidebar,hide=False)
        self.editor_panes.paneconfigure(self.editor_inspector,hide=False)
        if mode!='items':self.viewer.set_inventory_source(None)
        self._resource_browser=mode
        if mode=='media':
            self.viewer.pack_forget()
            self.media_viewer.pack(fill='both',expand=True)
        else:
            self.media_viewer.pack_forget()
            self.viewer.pack(fill='both',expand=True)
        self.hierarchy.pack_forget()
        self.world_panel.pack_forget()
        self.media_panel.pack_forget()
        self.properties.pack_forget()
        self.world_properties.pack_forget()
        self.media_properties.pack_forget()
        self.npc_properties.pack_forget()
        self.recipe_list.pack_forget()
        self.recipe_properties.pack_forget()
        (self.media_panel if mode=='media' else self.recipe_list if mode=='recipes' else self.world_panel if mode!='items' else self.hierarchy).pack(fill='both',expand=True)
        inspector=self.media_properties if mode=='media' else self.recipe_properties if mode=='recipes' else self.npc_properties if mode=='npc' else self.world_properties if mode=='world' else self.properties
        # Let the recipe form use the central area as well as the inspector.
        if mode=='recipes':
            self.viewer.master.master.paneconfigure(self.viewer.master,hide=True)
        else:
            self.viewer.master.master.paneconfigure(self.viewer.master,hide=False)
        self.world_panel.on_add=self.npcs.add if mode=='npc' else self.world.add
        self.world_panel.on_remove=self.npcs.remove if mode=='npc' else self.world.remove
        inspector.pack(fill='both',expand=True)
        self.mode.set_expression(mode)

    def _switch_resource_browser(self,mode):
        if not self.repo.root or mode==self._resource_browser:return
        if not self._save_editors():
            self.mode.set_expression(self._resource_browser)
            return
        if mode in ('world','npc'):
            try:
                if mode=='npc':self.npcs.show_list()
                else:self.world.refresh()
            except (OSError,ValueError,UnicodeError) as exc:
                messagebox.showerror('Ресурсы мира',str(exc),parent=self)
                self.mode.set_expression(self._resource_browser)
                return
        self._cancel_model_load()
        self.current=None
        self.world.current=None
        self.npcs.deselect()
        self.recipes.deselect()
        self.recipe_properties.show(None)
        if mode=='recipes':self.recipes.load()
        if mode=='media':
            self.load_media(keep=False)
            self.media_viewer.show(None)
        self.properties.show(None)
        self.world_properties.show(None)
        self.npc_properties.show(None)
        self.media_properties.show(None)
        self._show_resource_panels(mode)
        if mode=='locations':return
        self.viewer.set_mesh(caption={'world':'Выберите объект мира','npc':'Выберите NPC','media':'Выберите медиа'}.get(mode,tr('app.select_item')))

    def load_media_category(self,category):
        self._media_loaded.add(category)
        self.load_media(keep=True)
        self.media_panel.expand(category)

    def load_media(self,keep=False):
        if self.repo.root is None:return
        selected=self.media_properties.current if keep else None
        try:
            selected_names=ProjectSelection(self.repo.root,'Media').read()
            all_resources=(GameMedia(self.repo.root).catalog(self.repo.archive_models,self.repo.game)
                           if self._media_loaded or selected_names else GameMedia(self.repo.root).catalog())
            self._media_resources=all_resources
            self.media_panel.set_resources(all_resources,self._media_loaded,selected_names)
            if selected is not None:
                row=next((x for x in all_resources if x.kind==selected.kind and
                          x.name.casefold()==selected.name.casefold()),None)
                self.media_properties.show(row)
                self.media_viewer.show(row,self.repo.game)
            else:
                self.media_properties.show(None)
                self.media_viewer.show(None)
        except (OSError,ValueError) as exc:
            messagebox.showerror('Медиа',str(exc),parent=self)

    def import_media(self,category):
        from .ui.windows.media_import import MediaImportWindow
        if self.repo.root is None:return
        options=[row for row in GameMedia(self.repo.root).catalog(
            self.repo.archive_models,self.repo.game) if row.category==category and not row.overridden]
        if not options:
            messagebox.showinfo('Медиа','В этой категории не найдены ресурсы Gothic.',parent=self)
            return
        def choose(resource):
            selection=ProjectSelection(self.repo.root,'Media')
            saved=self.history.capture((selection.path,))
            selection.add(resource.kind+':'+resource.name)
            self.history.record(saved)
            window.destroy()
            self.load_media(keep=False)
            key=resource.kind+':'+resource.name.casefold()
            self.media_panel.expand(category)
            if key in self.media_panel.entries:
                self.media_panel.select(key)
        window=MediaImportWindow(self,options,choose)
        window.show_centered(modal=True)

    def select_media(self,resource):
        self.media_properties.show(resource)
        self.media_viewer.show(resource,self.repo.game)

    def _texture_mode_changed(self):
        camera=(self.viewer.angle_x,self.viewer.angle_y,self.viewer.zoom)
        if self.npcs.current is not None:self.npcs.preview(camera)
        elif self.world.current is not None:
            self._show_model_source(self.world.current.source,camera)
        elif self.current is not None:self._show_model(self.current,camera)

    def _show_model_source(self,entry,camera=None):
        self._cancel_model_load()
        assets=entry.parent if isinstance(entry,Path) else None
        try:key=self._preview_cache.key(entry,(self.repo.root,self.repo.resource_revision),self.viewer.textured,assets)
        except OSError as exc:
            self.viewer.set_mesh(caption=str(exc))
            return
        cached=self._preview_cache.get(key)
        if cached is not None:
            self.viewer.set_preview(cached,caption=entry.name,camera=camera)
            self.world.loaded(cached)
            return
        if camera is None:self.viewer.set_mesh(caption=tr('viewer.loading',name=entry.name))
        future=self._model_executor.submit(self._preview_cache.load,key,entry,self.repo.root,self.repo.game,
            assets,dict(self.repo.archive_models.texture_entries),with_textures=self.viewer.textured,
            animation_entries=dict(self.repo.archive_models.animation_entries))
        self._model_future=future
        self._model_poll=self.after(20,lambda:self._finish_archive_model(future,entry,camera))

    def _finish_archive_model(self,future,entry,camera=None):
        if future is not self._model_future:return
        self._model_poll=None
        if not future.done():
            self._model_poll=self.after(20,lambda:self._finish_archive_model(future,entry,camera))
            return
        self._model_future=None
        try:
            preview=future.result()
            caption=entry.name if isinstance(entry,Path) else f'{entry.archive.name} / {entry.name}'
            self.viewer.set_preview(preview,caption=caption,camera=camera)
            self.world.loaded(preview)
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
        window=getattr(self,'spreadsheet_window',None)
        if window is not None and window.winfo_exists() and window.runner.running:
            window.lift()
            return
        if self._tool_runner.running:
            self.show_terminal()
            return
        if hasattr(self,'properties') and not self._save_editors():return
        if hasattr(self,'npcs'):self.npcs.deselect()
        if hasattr(self,'recipes'):self.recipes.deselect()
        self._tool_runner.close()
        if self._welcome_map_after is not None:
            self.after_cancel(self._welcome_map_after)
            self._welcome_map_after=None
        self._cancel_dock_resize()
        if hasattr(self,'_model_executor'):
            self._cancel_model_load()
            self._model_executor.shutdown(wait=False,cancel_futures=True)
        super().destroy()

    def _history_capture(self,item=None,whole=False):
        if self.history.root is None:return {}
        paths=[self.repo.item_hierarchy.path]
        if item is not None:
            path=item.path
            if self.history.root==path or self.history.root in path.parents:
                paths.append(path.parent if whole and self.repo.components.owns(path) else path)
            elif item.origin=='game':
                paths.append(self.repo._destination_for(item))
                if classify(item)=='potions':
                    paths.append(self.repo.root/'Assets'/'Items'/'Potions'/item.instance)
        return self.history.capture(paths)

    def _history_record(self,before,result=None):
        if result is None:
            self.history.record(before)
        else:
            path=result.path
            if path not in before and self.repo.components.owns(path):path=path.parent
            self.history.record(before,(path,))

    def _history_keypress(self,event):
        key=event.keysym.lower()
        # Windows virtual-key codes refer to physical keys regardless of layout.
        if self.tk.call('tk','windowingsystem')=='win32':
            key={90:'z',89:'y'}.get(event.keycode,key)
        if key in ('z','cyrillic_ya'):
            return self._history_shortcut(bool(event.state & 1),event)
        if key in ('y','cyrillic_en'):
            return self._history_shortcut(True,event)

    def _history_shortcut(self,redo,event):
        focused=self.focus_get()
        if isinstance(focused,(tk.Entry,tk.Text,tk.Spinbox,ttk.Entry)):
            if self.properties.editor.dirty:return
        self.undo_redo(redo)
        return 'break'

    def undo_redo(self,redo=False):
        if self.repo.root is None:return
        if not (self.history.redo_stack if redo else self.history.undo_stack):return
        if not self._save_editors():return
        selected=self.current.instance.casefold() if self.current else None
        mode=self._resource_browser
        recipe_id=self.recipes.current['id'] if self.recipes.current else None
        npc_id=self.npcs.current.instance if self.npcs.current else None
        world_name=self.world.current.name if self.world.current else None
        try:
            if not self.history.apply(redo):return
            self._cancel_model_load()
            self.properties.show(None)
            self.current=None
            self.repo.item_hierarchy.reload()
            self.repo.refresh(project_only=True)
            self.update_hierarchy()
            if mode=='media':
                self.load_media(keep=True)
            if mode=='recipes':
                self.recipes.deselect()
                self.recipe_properties.show(None)
                self.recipes.load()
                recipe=next((value for value in self.recipes.items if value['id']==recipe_id),None)
                if recipe is not None:self.recipes.select(recipe)
            elif mode=='npc':
                self.npcs.deselect()
                self.npc_properties.show(None)
                self.npcs.stamp=None
                self.npcs.show_list()
                npc=next((value for value in self.npcs.items if value.instance==npc_id),None)
                if npc is not None:self.npcs.select(npc)
                else:self.viewer.set_mesh(caption='Выберите NPC')
            else:
                item=next((value for value in self.repo.items if value.instance.casefold()==selected),None)
                if item is not None:
                    self.hierarchy.choose(item)
                    self.select(item)
                elif mode=='items':
                    self.hierarchy.choose(None)
                    self.viewer.set_mesh(caption=tr('app.select_item'))
                elif mode=='world':
                    self.world.catalog_stamp=None
                    self.world.refresh()
                    resource=next((value for value in self.world.catalog
                                   if value.name.casefold()==(world_name or '').casefold()),None)
                    if resource is not None:self.world.select(resource)
                    else:
                        self.world.current=None
                        self.world_properties.show(None)
                        self.viewer.set_mesh(caption='Выберите объект мира')
            self.resources.refresh()
        except (OSError,ValueError) as exc:
            messagebox.showerror('История изменений',str(exc),parent=self)

    def _action(self,method,*args,**kwargs):
        if not self.need_project():return
        try:
            selected_before=self.properties.current
            if not self._save_editors():return
            if args and hasattr(args[0],'instance'):
                if (selected_before is not None and args[0].instance.casefold()==selected_before.instance.casefold()
                        and args[0].origin==selected_before.origin):
                    first=self.properties.current
                else:first=next((item for item in self.repo.items if item.instance.casefold()==args[0].instance.casefold()),args[0])
                args=(first,)+args[1:]
            target=args[0] if args and hasattr(args[0],'instance') else None
            whole=(target is not None and (method.__name__=='delete' or
                   (method.__name__=='edit' and kwargs.get('instance') not in (None,target.instance))))
            saved=self._history_capture(target,whole=whole)
            before={self.hierarchy.item_key(item) for item in self.repo.items}
            result=method(*args,**kwargs)
            self._history_record(saved,result)
            inserted=result if result is not None and self.hierarchy.item_key(result) not in before else None
            previous=target if target is not None and result is not None and inserted is None else None
            self.events.publish('items.changed',(previous,result if previous is not None else None,inserted))
            if result is not None:
                self.hierarchy.choose(result);self.select(result)
            return result
        except Exception as exc:
            messagebox.showerror(tr('app.error'),str(exc))

    def create_item(self,key):
        if key not in EDITABLE_CATEGORIES:return
        if not self.need_project():return
        dialog=AddItemDialog(self,key,self.repo.game_items)
        self.wait_window(dialog)
        if dialog.result is None:return
        action,value=dialog.result
        if action=='copy':
            if isinstance(value,list):
                return self.item_hierarchy_controller.import_items(value)
            return self._action(self.repo.copy_to_project,value)
        return self._action(self.repo.create_item,key,value)
    def duplicate(self,item):
        if classify(item) in EDITABLE_CATEGORIES:self._action(self.repo.duplicate,item)
    def copy_to_project(self,item):
        if classify(item) in EDITABLE_CATEGORIES:self._action(self.repo.copy_to_project,item)

    def delete(self,item):
        if classify(item) not in EDITABLE_CATEGORIES:return
        if item.origin!='project':return
        if not messagebox.askyesno(tr('app.delete_item'),tr('messages.delete',instance=item.instance)):
            return
        self._action(self.repo.delete,item)
        self._cancel_model_load()
        self.current=None;self.properties.show(None);self.viewer.set_mesh(caption=tr('app.select_item'))
        self.resources.set_item(self.repo.root,None)

    def rename(self,item,new_name):
        if classify(item) not in EDITABLE_CATEGORIES:return
        # The Daedalus name attribute is the in-game name, not INSTANCE.
        escaped=new_name.replace('\\','\\\\').replace('"','\\"')
        self.save_fields(item,{'name':'"'+escaped+'"'})

    def save_fields(self,item,values,autosave=False,**options):
        if classify(item) not in EDITABLE_CATEGORIES:return
        if not autosave:return self._action(self.repo.edit,item,values,**options)
        saved=self._history_capture(item,whole=options.get('instance') not in (None,item.instance))
        result=self.repo.edit(item,values,**options)
        self._history_record(saved,result)
        self.current=result
        self.hierarchy.selected=self.hierarchy.item_key(result)
        self.events.publish('items.changed',(item,result,None))
        if result.path!=item.path:self.resources.set_item(self.repo.root,result)
        else:self.resources.item=result
        if result.visual!=item.visual:
            self._show_model(result,(self.viewer.angle_x,self.viewer.angle_y,self.viewer.zoom))
        elif any(key.lower().startswith('inv_rot') for key in values):
            from .core.inventory_preview import rotation
            self.viewer.set_inventory_source(lambda:rotation(result.fields,classify(result),self.repo))
        return result


def main():EditorApp().mainloop()
