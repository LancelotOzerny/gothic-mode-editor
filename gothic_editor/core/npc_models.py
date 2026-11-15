"""Neutral-pose NPC previews from native MDM/MMB/MRM, without an animation engine.

Chunk layouts follow GothicKit/ZenKit ModelMesh, ModelHierarchy and MorphMesh.
"""
from pathlib import Path
import math
import re
import struct
from uuid import uuid4

from .asset_files import AssetFiles
from .mesh import PreviewMesh, read_mrm
from .model_preview import ModelPreview, load_model_preview
from .scripts import unquote


def chunk(data, position):
    if position+6>len(data):raise ValueError('Обрезанный заголовок модели NPC.')
    kind,size=struct.unpack_from('<HI',data,position)
    end=position+6+size
    if end>len(data):raise ValueError('Обрезанный блок модели NPC.')
    return kind,position+6,end


def line(data, position, end):
    start=position
    while position<end and data[position] not in (0,10,13):position+=1
    if position>=end:raise ValueError('Незавершённое имя узла NPC.')
    value=data[start:position].decode('cp1251')
    position+=1
    return value,position


IDENTITY=(1.,0.,0.,0., 0.,1.,0.,0., 0.,0.,1.,0., 0.,0.,0.,1.)


def multiply(a,b):
    return tuple(sum(a[row*4+k]*b[k*4+column] for k in range(4)) for row in range(4) for column in range(4))


def transform(point, matrix):
    return tuple(sum(matrix[row*4+k]*point[k] for k in range(3))+matrix[row*4+3] for row in range(3))


def hierarchy(data):
    position=0
    while position<len(data):
        kind,start,end=chunk(data,position)
        if kind==0xD100:
            if start+6>end:raise ValueError('Некорректная иерархия NPC.')
            version,count=struct.unpack_from('<IH',data,start)
            if version!=3 or count>1024:raise ValueError('Неподдерживаемая иерархия NPC.')
            nodes=[]
            matrices={}
            cursor=start+6
            for index in range(count):
                name,cursor=line(data,cursor,end)
                if cursor+66>end:raise ValueError('Обрезанная матрица узла NPC.')
                parent=struct.unpack_from('<h',data,cursor)[0]
                matrix=struct.unpack_from('<16f',data,cursor+2)
                cursor+=66
                if not all(math.isfinite(value) for value in matrix):raise ValueError('Некорректная матрица NPC.')
                if parent!=-1:
                    if not 0<=parent<index:raise ValueError('Некорректный родитель узла NPC.')
                    matrix=multiply(nodes[parent],matrix)
                nodes.append(matrix)
                matrices[name.upper()]=matrix
            if cursor+60<=end:
                root=struct.unpack_from('<3f',data,cursor+48)
                if not all(math.isfinite(value) for value in root):raise ValueError('Некорректное положение корня NPC.')
                for name,matrix in matrices.items():
                    matrix=list(matrix)
                    for axis in range(3):matrix[axis*4+3]+=root[axis]
                    matrices[name]=tuple(matrix)
            return matrices
        position=end
    return {}


def combine(meshes):
    result=PreviewMesh([],[],[],[],[])
    for mesh in meshes:
        offset=len(result.vertices)
        result.vertices.extend(mesh.vertices)
        result.faces.extend(tuple(offset+i for i in face) for face in mesh.faces)
        result.uvs.extend(mesh.uvs)
        result.texture_names.extend(mesh.texture_names)
        result.material_names.extend(mesh.material_names)
    if not result.faces:raise ValueError('Модель NPC не содержит треугольников.')
    if any(not math.isfinite(number) for vertex in result.vertices for number in vertex):
        raise ValueError('Некорректные координаты модели NPC.')
    return result


def validate_npc_model(data,suffix):
    if len(data)<6:raise ValueError('Обрезанная модель NPC.')
    first=struct.unpack_from('<H',data)[0]
    if (suffix=='.mdm' and first!=0xD000) or (suffix=='.mmb' and first not in (0xE010,0xE020)):
        raise ValueError('Файл имеет неподходящий формат модели NPC.')
    return read_npc_mesh(data)


def read_npc_mesh(data, matrices=None):
    meshes, attachments = [], []
    position=0
    while position<len(data):
        kind,start,end=chunk(data,position)
        if kind==0xD020:
            count=struct.unpack_from('<H',data,start)[0]
            cursor=start+2
            for _ in range(count):
                name,cursor=line(data,cursor,end)
                attachments.append(name)
        elif kind==0xB100:
            mesh=read_mrm(data[position:end],preview=True)
            name=attachments.pop(0) if attachments else ''
            matrix=(matrices or {}).get(name.upper())
            if matrix:mesh.vertices=[transform(vertex,matrix) for vertex in mesh.vertices]
            meshes.append(mesh)
        elif kind==0xB1FF and meshes and end-start>=12*len(meshes[-1].vertices):
            # Morph mesh reference positions (no face animation).
            meshes[-1].vertices=list(struct.iter_unpack('<3f',data[start:start+12*len(meshes[-1].vertices)]))
        elif kind==0xD030:
            if start+6>end:raise ValueError('Некорректный список мешей NPC.')
            count=struct.unpack_from('<H',data,start+4)[0]
            if count>1024:raise ValueError('Слишком много мешей NPC.')
            cursor=end
            for _ in range(count):
                while cursor<len(data):
                    sub,first,last=chunk(data,cursor)
                    if sub==0xB100:meshes.append(read_mrm(data[cursor:last],preview=True))
                    cursor=last
                    if sub==0xE110:break
                else:raise ValueError('Незавершённый меш NPC.')
            end=cursor
        position=end
    return combine(meshes)


class NpcModelIndex:
    def __init__(self, repo):
        self.project,self.game=repo.root,repo.game
        self.models=dict(repo.archive_models.animation_entries)
        self.models.update(repo.archive_models.entries)
        self.models.update(repo.mesh_index)
        for root in ([repo.game/'_work/data/Anims',repo.game/'_work/data/Meshes'] if repo.game else []) + [repo.root/'Assets/NPC/Models']:
            for path in sorted(root.rglob('*')):
                if path.is_file() and path.suffix.lower() in ('.mdm','.mdh','.mdl','.mmb','.mrm','.msb','.mds'):
                    self.models[path.name.casefold()]=path
        self.textures=dict(repo.archive_models.texture_entries)
        self.armors={item.instance.casefold():unquote(item.fields.get('visual_change','')) for item in repo.items
                     if item.fields.get('mainflag','').upper()=='ITEM_KAT_ARMOR'}

    def find(self, name, extensions):
        base=Path(name.replace('\\','/')).stem.casefold()
        return next((self.models[base+suffix] for suffix in extensions if base+suffix in self.models),None)

    def options(self, kind):
        suffixes={'body':('.mdm',),'head':('.mmb',),'visual':('.mdh',)}[kind]
        result=[]
        for name in sorted(self.models):
            if Path(name).suffix not in suffixes:continue
            if kind=='visual' and not any(Path(name).stem+suffix in self.models for suffix in ('.msb','.mds')):continue
            if kind=='head' and not ('head' in name or name.startswith('ge_npc_')):continue
            value=Path(self.models[name].name).stem
            if kind=='visual':value+='.MDS'
            result.append((value,value))
        if kind=='head':result.insert(0,('Нет',''))
        return result

    def import_model(self, source, kind):
        source=Path(source)
        suffix=source.suffix.lower()
        if suffix not in ({'body':('.mdm',),'head':('.mmb',)}[kind]):
            raise ValueError('Выберите скомпилированную модель NPC соответствующего типа.')
        if source.stat().st_size>64*1024*1024:raise ValueError('Модель NPC превышает 64 МБ.')
        data=source.read_bytes()
        validate_npc_model(data,suffix)
        folder=AssetFiles(self.project).checked(self.project/'Assets/NPC/Models')
        folder.mkdir(parents=True,exist_ok=True)
        name='GE_NPC_'+re.sub(r'[^A-Za-z0-9_]','_',source.stem)
        name=name[:48]
        target=folder/(name+suffix)
        number=2
        while target.exists() or target.name.casefold() in self.models:
            target=folder/(name+'_'+str(number)+suffix)
            number+=1
        temporary=folder/('.npc-import-'+uuid4().hex+'.tmp')
        try:
            temporary.write_bytes(data)
            temporary.rename(target)
        finally:temporary.unlink(missing_ok=True)
        return target.stem


def load_npc_preview(npc, index, catalog, textured=False):
    if not npc.body_args:raise ValueError('Внешность этого NPC задаётся скриптом, который пока не распознан.')
    args=npc.body_args
    body_name=index.armors.get(npc.armor.casefold(),npc.body)
    source=index.find(body_name,('.mdm','.mdl'))
    if source is None:raise ValueError('Не найдена модель тела NPC: '+body_name)
    skeleton=index.find(npc.visual,('.mdh','.mdl'))
    matrices=hierarchy(skeleton.read_bytes()) if skeleton else {}
    body=read_npc_mesh(source.read_bytes(),matrices)
    def variant(mesh,texture,color,teeth=None):
        texture=catalog.integer(texture)
        color=catalog.integer(color)
        for i,name in enumerate(mesh.texture_names):
            number=catalog.integer(teeth) if teeth is not None and re.search(r'HUM_(MOUTH|TEETH)',name,re.I) else texture
            if number is not None and number>=0:name=re.sub(r'_V\d+',f'_V{number}',name,flags=re.I)
            if color is not None and color>=0:name=re.sub(r'_C\d+',f'_C{color}',name,flags=re.I)
            mesh.texture_names[i]=name
    if body_name==npc.body:variant(body,args[1],args[2])
    pieces=[load_model_preview(source,index.project,index.game,texture_entries=index.textures,
                               with_textures=textured,mesh=body)]
    if npc.head:
        head=index.find(npc.head,('.mmb','.mrm'))
        if head is None:raise ValueError('Не найдена модель головы NPC: '+npc.head)
        mesh=read_npc_mesh(head.read_bytes())
        variant(mesh,args[4],'0',args[5])
        matrix=matrices.get('BIP01 HEAD') or matrices.get('BIP01_HEAD')
        if matrix is None:raise ValueError('В скелете NPC не найден узел головы.')
        mesh.vertices=[transform(vertex,matrix) for vertex in mesh.vertices]
        pieces.append(load_model_preview(head,index.project,index.game,texture_entries=index.textures,
                                        with_textures=textured,mesh=mesh))
    textures,sources,missing={},{},[]
    for preview in pieces:
        textures.update(preview.textures)
        sources.update(preview.texture_sources)
        missing.extend(preview.missing)
    return ModelPreview(combine([piece.mesh for piece in pieces]),textures,list(dict.fromkeys(missing)),textured,sources)


def collect_npc_models(project):
    result={}
    files=AssetFiles(project)
    root=Path(project)/'Assets/NPC/Models'
    for source in sorted(root.glob('*')):
        files.checked(source)
        if not source.is_file() or source.suffix.lower() not in ('.mdm','.mmb'):
            raise ValueError('Неподдерживаемый ресурс NPC: '+str(source))
        data=source.read_bytes()
        validate_npc_model(data,source.suffix.lower())
        result['_work/data/Anims/_compiled/'+source.name]=data
    return result
