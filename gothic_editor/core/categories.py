"""Virtual hierarchy. Subtypes use flags; custom classes can be added here."""
from dataclasses import dataclass,field
import re

@dataclass
class Category:
    name:str
    icon:str
    key:str
    children:list['Category']=field(default_factory=list)
    mainflag:str='ITEM_KAT_NONE'
    flags:str='0'

CATEGORIES=[
 Category('Зелья','⚗','potions',mainflag='ITEM_KAT_POTIONS'),
 Category('Оружие','⚔','weapons',[
  Category('Мечи','⚔','swords',[
   Category('Одноручные','⚔','onehand',mainflag='ITEM_KAT_NF',flags='ITEM_SWD'),
   Category('Двуручные','⚔','twohand',mainflag='ITEM_KAT_NF',flags='ITEM_2HD_SWD')]),
  Category('Топоры и булавы','⚒','axes',[
   Category('Одноручные','⚒','oneaxe',mainflag='ITEM_KAT_NF',flags='ITEM_AXE'),
   Category('Двуручные','⚒','twoaxe',mainflag='ITEM_KAT_NF',flags='ITEM_2HD_AXE')]),
  Category('Дальний бой','➶','ranged',[
   Category('Луки','➶','bows',mainflag='ITEM_KAT_FF',flags='ITEM_BOW'),
   Category('Арбалеты','➶','crossbows',mainflag='ITEM_KAT_FF',flags='ITEM_CROSSBOW')])]),
 Category('Броня','▣','armor',mainflag='ITEM_KAT_ARMOR'),
 Category('Магия','✦','magic',[
  Category('Руны','✦','runes',mainflag='ITEM_KAT_RUNE'),
  Category('Свитки','▤','scrolls',mainflag='ITEM_KAT_RUNE')]),
 Category('Еда и напитки','♨','food',mainflag='ITEM_KAT_FOOD'),
 Category('Амулеты и кольца','◇','jewelry',[
  Category('Амулеты','◇','amulets',mainflag='ITEM_KAT_MAGIC'),
  Category('Кольца','◈','rings',mainflag='ITEM_KAT_MAGIC')]),
 Category('Документы и книги','▤','documents',mainflag='ITEM_KAT_DOCS'),
 Category('Боеприпасы','➤','ammo',mainflag='ITEM_KAT_MUN'),
 Category('Разное','▦','misc',mainflag='ITEM_KAT_NONE'),
]

def walk_categories(nodes=CATEGORIES):
    for node in nodes:
        yield node
        yield from walk_categories(node.children)

def tokens(raw):return {s.upper() for s in re.findall(r'[A-Za-z_]\w*|\d+',raw)}

def classify(item):
    f=item.fields;main=tokens(f.get('mainflag','')); flags=tokens(f.get('flags',''))
    instance=item.instance.upper()
    if 'ITEM_KAT_POTIONS' in main or '128' in main or instance.startswith(('ITPO_','ITPO')):return 'potions'
    if 'ITEM_KAT_ARMOR' in main:return 'armor'
    if 'ITEM_KAT_FOOD' in main:return 'food'
    if 'ITEM_KAT_DOCS' in main:return 'documents'
    if 'ITEM_KAT_MUN' in main:return 'ammo'
    if 'ITEM_KAT_RUNE' in main:
        if 'SCROLL' in instance or 'SCROLL' in item.path.name.upper():return 'scrolls'
        return 'runes'
    if 'ITEM_KAT_MAGIC' in main:
        return 'rings' if 'RING' in instance else 'amulets'
    if 'ITEM_KAT_FF' in main:
        return 'crossbows' if 'ITEM_CROSSBOW' in flags else 'bows'
    if 'ITEM_KAT_NF' in main:
        if 'ITEM_2HD_AXE' in flags:return 'twoaxe'
        if 'ITEM_2HD_SWD' in flags:return 'twohand'
        if 'ITEM_AXE' in flags:return 'oneaxe'
        return 'onehand'
    return 'misc'

def get_category(key):return next((x for x in walk_categories() if x.key==key),CATEGORIES[-1])

def leaf_for(node):
    if not node.children:return node
    return leaf_for(node.children[0])
