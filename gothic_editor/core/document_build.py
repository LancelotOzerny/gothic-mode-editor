"""Attach authored document text to C_Item read events in the staging tree."""
from __future__ import annotations

from pathlib import Path

from .categories import classify
from .daedalus_merge import ScriptTree, definitions, target_path
from .document_pages import load_document, render_document
from .item_actions import assignments
from .item_layout import project_scripts
from .scripts import parse_items, replace_field

OUTPUT = Path('GE_Documents/Texts.d')


def apply_documents(project, content):
    authored = []
    project_scripts_root = project_scripts(project) / 'Content'
    if not project_scripts_root.is_dir():
        return []
    for path in sorted(project_scripts_root.rglob('*.d')):
        for item in parse_items(path, 'project'):
            reference = item.editor_metadata.get('document_text', '')
            if reference and classify(item) == 'documents':
                authored.append((item, reference))
    if not authored:
        return []

    tree = ScriptTree(content)
    edits = {}
    functions = []
    seen = set()
    for item, reference in authored:
        key = item.instance.casefold()
        if key in seen:
            raise ValueError('Повторяющийся документ с текстом: ' + item.instance)
        seen.add(key)
        location = tree.unique(item.instance, 'instance')
        if location is None:
            raise ValueError(f'{item.instance}: документ отсутствует в исходниках сборки.')
        path, definition = location
        source = tree.documents[path].text[definition.start:definition.end]
        try:
            raw = load_document(project, reference)
            book = 'book' in item.visual.casefold()
            script = render_document(item.instance, raw, book=book)
        except (OSError, ValueError) as exc:
            raise ValueError(
                f'Документ {item.instance} ({reference}): {exc}'
            ) from exc
        # The user-selected actions still run, but a replaced original read
        # callback must not show its old page over this newly generated text.
        if any(row['id'] for row in assignments(item.editor_metadata.get('item_actions', ''))):
            action = 'GE_ItemActions_' + item.instance
            entry = f'func void GE_ShowDocument_{item.instance}()\n{{'
            script = script.replace(entry, entry + f'\n    {action}();', 1)
        for parsed in definitions(script, item.instance):
            for name in parsed.names:
                if tree.unique(name):
                    raise ValueError('Конфликт имени функции чтения: ' + name)
        functions.append(script)
        edited = replace_field(source, 'on_state[0]', 'GE_ShowDocument_' + item.instance)
        edits.setdefault(path, []).append((definition.start, definition.end, edited))

    text = '\n\n'.join(functions) + '\n'
    target = target_path(content, OUTPUT)
    if target.exists():
        raise ValueError('Занят путь генерации текста документов: ' + str(OUTPUT))
    target.parent.mkdir(parents=True, exist_ok=True)
    text.encode('cp1251')
    # Publish only after all input documents and symbols pass validation.
    tree.apply(edits)
    target.write_bytes(text.encode('cp1251'))
    return [OUTPUT]
