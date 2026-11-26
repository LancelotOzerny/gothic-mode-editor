"""Editor-only hierarchy actions, sharing the existing inspector and dialogs."""
from tkinter import messagebox
from gothic_editor.core.categories import walk_categories, classify, get_category
from gothic_editor.ui.windows.dialog import EditorDialog
from gothic_editor.ui.widgets.form import FormGroup


class ItemHierarchyController:
    def __init__(self, app):
        self.app = app

    def _remember_hierarchy(self, operation):
        history=self.app.history
        before=history.capture((self.app.repo.item_hierarchy.path,))
        result=operation()
        history.record(before)
        return result

    def select(self, node):
        app = self.app
        if not app._save_editors():return False
        app._cancel_model_load()
        app.current = None
        app.viewer.set_inventory_source(None)
        app.viewer.set_mesh(caption=node.name)
        app.resources.set_item(app.repo.root,None)
        app.properties.show_node(node,self.rename)
        return True

    def rename(self, node, name):
        self._remember_hierarchy(lambda:self.app.repo.item_hierarchy.rename(node.key,name))
        node.name = name.strip()
        self.app.hierarchy.rebuild()

    def move(self, item, key):
        if not self.app._save_editors():return
        try:
            self._remember_hierarchy(lambda:self.app.repo.item_hierarchy.assign(item,key))
            self.app.update_hierarchy()
            self.app.hierarchy.choose(item)
        except (ValueError,OSError) as exc:messagebox.showerror('Иерархия',str(exc),parent=self.app)

    def action(self, action, node):
        app = self.app
        if not app._save_editors():return
        store = app.repo.item_hierarchy
        try:
            key = node.key
            if action == 'rename':
                dialog = EditorDialog(app)
                dialog.title('Переименовать')
                group = FormGroup(dialog,'Группа' if node.kind=='group' else 'Категория')
                group.pack(fill='both',expand=True,padx=16,pady=16)
                code = group.add_field('Код',value=node.code) if node.kind=='category' else None
                name = group.add_field('Название',value=node.name)
                def save():
                    try:self._remember_hierarchy(lambda:store.rename(key,name.get(),code.get() if code else None))
                    except (OSError,ValueError) as exc:
                        messagebox.showerror('Иерархия',str(exc),parent=dialog)
                        return
                    dialog.destroy()
                    self.refresh(key)
                group.add_button('Сохранить',save)
                group.add_button('Отмена',dialog.destroy)
                dialog.bind('<Escape>',lambda _:dialog.destroy())
                dialog.show_centered(modal=True)
                return
            if action == 'create':key = self._remember_hierarchy(lambda:store.create_group(key))
            elif action == 'duplicate':key = self._remember_hierarchy(lambda:store.duplicate(key))[key]
            elif action == 'delete':
                if not messagebox.askyesno('Удалить',
                        'Удалить «'+node.name+'» и вложенные группы? Предметы сохранятся.',parent=app):return
                self._remember_hierarchy(lambda:store.delete(key))
                app.properties.show(None)
                app.hierarchy.selected_node = None
                app.update_hierarchy()
                return
            elif action == 'add':
                result = app.create_item(node.source)
                if isinstance(result,list):
                    self._remember_hierarchy(lambda:store.assign_many(result,key))
                    app.update_hierarchy()
                elif result is not None:self.move(result,key)
                return
            self.refresh(key)
        except (ValueError,OSError) as exc:messagebox.showerror('Иерархия',str(exc),parent=app)

    def import_items(self, originals):
        """Import multiple original items as a single undoable operation."""
        app=self.app
        if not originals or not app._save_editors():return []
        paths={app.repo.item_hierarchy.path}
        from gothic_editor.core.categories import classify
        for item in originals:
            paths.add(app.repo.components.item_path(item.instance) if classify(item)=='potions'
                      else app.repo._destination_for(item))
        saved=app.history.capture(paths)
        imported=[]
        try:
            for item in originals:
                imported.append(app.repo.copy_to_project(item))
        except (OSError, ValueError, UnicodeError) as exc:
            messagebox.showerror('Импорт предметов',
                str(exc) + f'\nИмпортировано до ошибки: {len(imported)}.',
                parent=app)
        finally:
            app.history.record(saved)
            app.update_hierarchy()
        if imported:app.select(imported[-1])
        return imported

    def import_category(self, node):
        """Import original items from this category (including its subcategories).

        Existing project overrides are left untouched. All imported paths and
        hierarchy membership share one undo entry.
        """
        app = self.app
        if not app._save_editors() or not app.need_project():
            return
        store = app.repo.item_hierarchy
        try:
            originals = [item for item in app.repo.game_items
                         if store.accepts(node.key, item)]
            if not originals:
                messagebox.showinfo('Импорт из Gothic',
                                    'Исходные предметы для этой категории не найдены. '
                                    'Проверьте путь к установленной Gothic и её скриптам.',
                                    parent=app)
                return
            existing = {item.instance.casefold() for item in app.repo.project_items}
            pending = [item for item in originals if item.instance.casefold() not in existing]
            if not pending:
                messagebox.showinfo('Импорт из Gothic', 'Все доступные предметы уже импортированы.',
                                    parent=app)
                return
            if not messagebox.askyesno('Импорт из Gothic',
                    f'Импортировать {len(pending)} предметов из Gothic в «{node.name}»? '
                    'Уже импортированные предметы останутся без изменений.',
                    parent=app):
                return
            # Resolve affected script paths before writes; several instances may
            # belong to the same source .d file.
            paths = {store.path}
            for item in pending:
                if classify(item) == 'potions':
                    paths.add(app.repo.components.item_path(item.instance))
                else:
                    paths.add(app.repo._destination_for(item))
            before = app.history.capture(paths)
            imported = []
            try:
                for item in pending:
                    imported.append(app.repo.copy_to_project(item))
                # Preserve normal subcategories when importing a whole branch;
                # an individual leaf category receives its new items directly.
                allowed = {category.key for category in walk_categories([get_category(node.source)])}
                if len(allowed) == 1 and imported:
                    store.assign_many(imported, node.key)
            finally:
                # Even an interrupted bulk import remains one undoable action.
                app.history.record(before)
                app.update_hierarchy()
            messagebox.showinfo('Импорт из Gothic',
                                f'Импортировано предметов: {len(imported)}.', parent=app)
        except (OSError, ValueError, UnicodeError) as exc:
            messagebox.showerror('Импорт из Gothic', str(exc), parent=app)

    def refresh(self, key):
        panel = self.app.hierarchy
        nodes = list(walk_categories(self.app.repo.item_hierarchy.tree()))
        node = next(node for node in nodes if node.key==key)
        parent = node.parent
        while parent:
            panel.expanded[('project',parent)] = True
            parent = next(value.parent for value in nodes if value.key==parent)
        panel.selected_node = key
        self.app.update_hierarchy()
        self.select(node)

    def clear_inspector(self):
        app = self.app
        app._cancel_model_load()
        app.current = None
        app.properties.show(None)
        app.properties.info.config(text='')
        app.viewer.set_inventory_source(None)
        app.viewer.set_mesh(caption='')
        app.resources.set_item(app.repo.root,None)

    def batch(self,action,values,target=''):
        from gothic_editor.core.item_hierarchy import HierarchyNode
        app = self.app
        if not app._save_editors():return
        panel,store = app.hierarchy,app.repo.item_hierarchy
        nodes = {node.key:node for node in walk_categories(store.tree())}
        items = {panel.item_key(item):item for item in app.repo.items}
        values = [nodes.get(value.key) if isinstance(value,HierarchyNode) else items.get(panel.item_key(value))
                  for value in values]
        values = [value for value in values if value is not None]
        if not values:return
        if action=='delete' and not messagebox.askyesno('Удалить выбранное',
                'Удалить выбранные предметы и группировки ('+str(len(values))+')? '
                'Предметы внутри удаляемых групп сохранятся, если не выбраны отдельно.',parent=app):return
        saved=app._history_capture()
        for value in values if action!='move' else ():
            if saved is None:break
            if not isinstance(value,HierarchyNode):
                current=app._history_capture(value,whole=action=='delete')
                if current is None:saved=None
                else:saved.update(current)
        original_items={(item.origin,item.instance.casefold()) for item in app.repo.project_items}
        completed = 0
        try:
            if action=='move':
                store.move_many(values,target)
                parents = {row['key']:row['parent'] for row in store.data['nodes']}
                for value in values:
                    if isinstance(value,HierarchyNode):
                        parent = parents[value.key]
                        while parent:
                            panel.expanded[('project',parent)] = True
                            parent = parents[parent]
                    else:panel.reveal(value)
            else:
                # An ancestor already duplicates/deletes its whole visual subtree.
                chosen = {value.key for value in values if isinstance(value,HierarchyNode)}
                roots = [key for key in chosen if not any(key in store.descendants(other)
                         for other in chosen if other!=key)]
                for value in values:
                    if isinstance(value,HierarchyNode):
                        if value.key not in roots:continue
                        if action=='delete':store.delete(value.key)
                        elif action=='duplicate':store.duplicate(value.key)
                    else:
                        # Resolve again: preceding operations can reparse a shared .d file.
                        value = next(item for item in app.repo.items if panel.item_key(item)==panel.item_key(value))
                        if action=='delete':app.repo.delete(value)
                        elif action=='duplicate':app.repo.duplicate(value)
                        elif action=='copy':app.repo.copy_to_project(value)
                    completed += 1
                panel.multiple.clear()
                panel.selected = panel.selected_node = None
                self.clear_inspector()
        except (OSError,ValueError) as exc:
            messagebox.showerror('Иерархия',str(exc)+'\nВыполнено операций: '+str(completed),parent=app)
        finally:
            added=[]
            for item in app.repo.project_items:
                if (item.origin,item.instance.casefold()) not in original_items:
                    added.append(item.path.parent if app.repo.components.owns(item.path) else item.path)
            app.history.record(saved,added)
            app.update_hierarchy()
            panel.paint_selection()
