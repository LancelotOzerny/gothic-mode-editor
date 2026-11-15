"""Inventory orientation, following OpenGothic InventoryRenderer::itemRotation."""
import ast
import math
import operator
import re
from .mesh import PreviewMesh
from .scripts import load_text


BASE = {'potions':(180,0,0),'food':(180,0,45),'armor':(0,-90,180),
        'runes':(90,0,90),'scrolls':(90,0,90),'rings':(200,0,90),'amulets':(200,0,90),
        'documents':(180,90,-90),'misc':(135,90,45)}


def number(expression, repo=None, seen=()):
    operations={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,
                ast.Div:operator.truediv,ast.FloorDiv:operator.floordiv,ast.BitOr:operator.or_,
                ast.LShift:operator.lshift,ast.RShift:operator.rshift}
    def evaluate(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):return node.value
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.USub,ast.UAdd)):
            return (-1 if isinstance(node.op,ast.USub) else 1)*evaluate(node.operand)
        if isinstance(node,ast.BinOp) and type(node.op) in operations:return operations[type(node.op)](evaluate(node.left),evaluate(node.right))
        if isinstance(node,ast.Name) and repo is not None and node.id.casefold() not in seen:
            key=('inventory_constants',repo.resource_revision)
            if key not in repo.options_cache:
                constants={}
                for root in (repo._game_content(),repo._project_content()):
                    if root is None:continue
                    for path in root.rglob('*.d'):
                        from .scripts import mask_comments
                        text=mask_comments(load_text(path)[0])
                        for match in re.finditer(r'\bconst\s+int\s+(\w+)\s*=\s*([^;]+);',text,re.I):constants[match[1].casefold()]=match[2]
                repo.options_cache[key]=constants
            value=repo.options_cache[key].get(node.id.casefold())
            if value is not None:return number(value,repo,seen+(node.id.casefold(),))
        raise ValueError('Не удалось вычислить угол: '+expression)
    try:
        result=evaluate(ast.parse(expression.strip() or '0',mode='eval').body)
        if not math.isfinite(result):raise ValueError()
        return result
    except (SyntaxError,ArithmeticError,TypeError,ValueError) as exc:
        raise ValueError('Не удалось вычислить угол: '+expression) from exc


def rotation(fields, category, repo=None):
    base=BASE.get(category,(-45,0,90))
    offsets=[number(fields.get('inv_rot'+axis,'0'),repo) for axis in 'xyz']
    if category=='documents':return base
    return tuple(a+(-b if category=='misc' else b) for a,b in zip(base,offsets))


def inventory_mesh(mesh, angles):
    rx,ry,rz=map(math.radians,angles)
    cx,sx,cy,sy,cz,sz=math.cos(rx),math.sin(rx),math.cos(ry),math.sin(ry),math.cos(rz),math.sin(rz)
    vertices=[]
    for x,y,z in mesh.vertices:
        x,z=x*cy+z*sy,-x*sy+z*cy
        x,y=x*cz-y*sz,x*sz+y*cz
        y,z=y*cx-z*sx,y*sx+z*cx
        # Tempest swaps matrix rows (output axes), not input coordinates.
        # Vulkan inventory viewport has Y down and near depth smaller; our
        # rasterizer uses Y up and larger depth nearer the viewer.
        vertices.append((z,-y,-x))
    return PreviewMesh(vertices,mesh.faces,mesh.uvs,mesh.texture_names,mesh.material_names)
