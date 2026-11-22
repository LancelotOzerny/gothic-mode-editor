"""Generate standard Gothic II merchant scripts in disposable staging only."""
import re
from pathlib import Path

from .daedalus_merge import ScriptTree, target_path
from .npcs import NpcCatalog
from .scripts import mask_comments
from .trading import TradingStore

OUTPUT = Path('Story/GE_Trading.d')
MAIN = 'B_GiveTradeInv'

def _code(npc, config):
    ident = npc.upper()
    lines = []
    lines.append(f'var int GE_TradeLast_{ident};')
    for chapter in sorted({r['chapter'] for r in config['stock']}):
        lines.append(f'var int GE_TradeChapter_{ident}_{chapter};')
    lines.append(f'func void GE_TradeStock_{ident}(var C_Npc slf) {{')
    for chapter in sorted({r['chapter'] for r in config['stock']}):
        lines.append(f'    if ((Kapitel >= {chapter}) && (GE_TradeChapter_{ident}_{chapter} == FALSE)) {{')
        for row in config['stock']:
            if row['chapter'] == chapter:
                lines.append(f"        CreateInvItems(slf, {row['item']}, {row['quantity']});")
        lines.append(f'        GE_TradeChapter_{ident}_{chapter} = TRUE;')
        lines.append('    };')
    hours = config.get('refresh_hours', 0)
    if hours:
        lines += [
            '    var int geHour;', '    var int geMinute;', '    var int geNow;',
            '    Wld_GetTime(geHour, geMinute);',
            '    geNow = (Wld_GetDay() * 24) + geHour + 1;',
            f'    if ((GE_TradeLast_{ident} == 0) || ((geNow - GE_TradeLast_{ident}) >= {hours})) {{'
        ]
        # Target is the cumulative stock of all unlocked chapters, never an unlimited grant.
        items = {}
        for row in config['stock']:
            items.setdefault(row['item'].casefold(), []).append(row)
        for rows in items.values():
            item = rows[0]['item']
            for chapter in sorted({row['chapter'] for row in rows}):
                target = sum(row['quantity'] for row in rows if row['chapter'] <= chapter)
                lines += [
                    f'        if (Kapitel >= {chapter}) {{',
                    f'            if (Npc_HasItems(slf, {item}) < {target}) {{',
                    f'                CreateInvItems(slf, {item}, {target} - Npc_HasItems(slf, {item}));',
                    '            };',
                    '        };'
                ]
        lines += [f'        GE_TradeLast_{ident} = geNow;', '    };']
    lines.append('};')
    if config.get('dialog', True):
        lines += [
            f'func int GE_TradeCondition_{ident}() {{',
            f"    if (Kapitel >= {config.get('min_chapter', 1)}) {{ return TRUE; }};",
            '    return FALSE;', '};',
            f'func void GE_TradeInfo_{ident}() {{',
            f'    GE_TradeStock_{ident}(self);',
            '};',
            f'instance GE_TradeDialog_{ident}(C_Info) {{',
            f'    npc = {npc};', '    nr = 999;',
            f'    condition = GE_TradeCondition_{ident};',
            f'    information = GE_TradeInfo_{ident};',
            '    permanent = TRUE;', '    description = "Покажи мне свои товары";',
            '    trade = TRUE;', '};'
        ]
    return '\n'.join(lines)

def prepare_trading(project, content):
    """Inject stock hooks into main vanilla dispatcher and create optional C_Info dialogs."""
    traders = TradingStore(project).read()
    if not traders:
        return None
    catalog = NpcCatalog(project, content=content)
    known = {npc.instance.casefold(): npc.instance for npc in catalog.load()}
    tree = ScriptTree(content)
    chunks = []
    for key, config in sorted(traders.items()):
        if key not in known:
            raise ValueError(f'Торговец {key}: NPC отсутствует в скриптах.')
        npc = known[key]
        for row in config['stock']:
            match = tree.unique(row['item'], 'instance')
            if match is None:
                raise ValueError(f'Торговец {npc}: предмет {row["item"]} не найден в игровых скриптах.')
        for name in (f'GE_TradeLast_{npc.upper()}', f'GE_TradeStock_{npc.upper()}',
                     f'GE_TradeDialog_{npc.upper()}'):
            if tree.unique(name):
                raise ValueError(f'Конфликт генерируемого торгового символа: {name}')
        chunks.append(_code(npc, config))
    # Patch vanilla dispatcher only in staging, preserving its original actions.
    match = tree.unique(MAIN, 'func')
    if match:
        path, definition = match
        source = tree.documents[path].text[definition.start:definition.end]
        header = re.search(r'\bfunc\s+void\s+B_GiveTradeInv\s*\(\s*var\s+C_Npc\s+(\w+)\s*\)\s*\{', mask_comments(source), re.I)
        if not header:
            raise ValueError(f'{path}: неподдерживаемая сигнатура B_GiveTradeInv.')
        argument = header[1]
        hooks = []
        for key, config in sorted(traders.items()):
            npc = known[key]
            hooks.append(f'    if (Hlp_GetInstanceID({argument}) == Hlp_GetInstanceID({npc})) {{')
            if config.get('min_chapter', 1) > 1:
                hooks.append(f"        if (Kapitel >= {config['min_chapter']}) {{")
                hooks.append(f'            GE_TradeStock_{npc.upper()}({argument});')
                hooks.append('        };')
            else:
                hooks.append(f'        GE_TradeStock_{npc.upper()}({argument});')
            if config.get('replace_original', False):
                hooks.append('        return;')
            hooks.append('    };')
        updated = source[:header.end()] + '\n' + '\n'.join(hooks) + '\n' + source[header.end():]
        tree.apply({path: [(definition.start, definition.end, updated)]})
    destination = target_path(content, OUTPUT)
    if destination.exists():
        raise ValueError('Занят файл автогенерации торговцев: ' + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(('// Gothic Editor: торговцы\n' + '\n\n'.join(chunks) + '\n').encode('cp1251'))
    return OUTPUT

def prioritize_trading(manifest):
    """Place generated declarations before the vanilla merchant dispatcher and NPC dialogues."""
    from .scripts import load_text
    source, codec = load_text(manifest)
    lines = source.splitlines()
    path = OUTPUT.as_posix().casefold()
    matches = [line for line in lines if line.strip().replace('\\','/').casefold() == path]
    if len(matches) != 1:
        raise ValueError('Gothic.src: отсутствует или повторяется GE_Trading.d.')
    lines = [line for line in lines if line not in matches]
    index = next((i for i, line in enumerate(lines) if 'b_givetradeinv' in line.casefold()
                  or 'dialog' in line.casefold()), len(lines))
    lines.insert(index, matches[0])
    manifest.write_text('\r\n'.join(lines) + '\r\n', encoding=codec, newline='')
