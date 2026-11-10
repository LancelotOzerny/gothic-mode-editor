"""Small SpreadsheetML table reader/writer using only the Python standard library."""
from pathlib import Path, PurePosixPath
import posixpath
import re
import tempfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile

NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PACKAGE='http://schemas.openxmlformats.org/package/2006/relationships'
MAX_ROWS=100000
MAX_CELLS=2000000


def column_name(index):
    name=''
    while index:
        index,remainder=divmod(index-1,26)
        name=chr(65+remainder)+name
    return name


def write_table(destination,rows,on_progress=lambda *_:None):
    destination=Path(destination)
    if destination.suffix.lower()!='.xlsx':raise ValueError('Выберите файл .xlsx')
    if len(rows)>MAX_ROWS:raise ValueError('Слишком много строк для экспорта')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(prefix='.xlsx-',suffix='.tmp',dir=destination.parent,delete=False) as stream:
            temporary=Path(stream.name)
        with ZipFile(temporary,'w',ZIP_DEFLATED) as archive:
            archive.writestr('[Content_Types].xml',
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                '</Types>')
            archive.writestr('_rels/.rels',f'<Relationships xmlns="{PACKAGE}"><Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
            archive.writestr('xl/workbook.xml',f'<workbook xmlns="{NS}" xmlns:r="{REL}"><bookViews><workbookView/></bookViews><sheets><sheet name="Предметы" sheetId="1" r:id="rId1"/></sheets></workbook>')
            archive.writestr('xl/_rels/workbook.xml.rels',f'<Relationships xmlns="{PACKAGE}"><Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
            with archive.open('xl/worksheets/sheet1.xml','w') as sheet:
                sheet.write((f'<worksheet xmlns="{NS}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/><selection pane="bottomLeft" activeCell="A2" sqref="A2"/></sheetView></sheetViews><sheetFormatPr defaultColWidth="24" defaultRowHeight="15"/><sheetData>').encode())
                count=0
                for row_index,row in enumerate(rows,1):
                    if len(row)>16384:raise ValueError('Слишком много колонок XLSX')
                    count+=len(row)
                    if count>MAX_CELLS:raise ValueError('Слишком много ячеек XLSX')
                    cells=[]
                    for column,value in enumerate(row,1):
                        value=str(value)
                        if len(value)>32767:raise ValueError(f'{column_name(column)}{row_index}: текст длиннее 32767 символов')
                        if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]',value):
                            raise ValueError(f'{column_name(column)}{row_index}: недопустимый символ XML')
                        if value:
                            value=re.sub(r'_x[0-9a-fA-F]{4}_',lambda match:'_x005F_'+match[0][1:],value)
                            value=escape(value).replace('\r','&#13;')
                            cells.append(f'<c r="{column_name(column)}{row_index}" t="inlineStr"><is><t xml:space="preserve">{value}</t></is></c>')
                    sheet.write((f'<row r="{row_index}">'+''.join(cells)+'</row>').encode('utf-8'))
                    if row_index%100==0:on_progress(row_index,len(rows),'Экспорт предметов')
                sheet.write(b'</sheetData>')
                if rows and rows[0]:sheet.write(f'<autoFilter ref="A1:{column_name(len(rows[0]))}{len(rows)}"/>'.encode())
                sheet.write(b'</worksheet>')
        temporary.replace(destination)
        on_progress(len(rows),len(rows),'Экспорт завершён')
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


def _tag(element):return element.tag.rsplit('}',1)[-1]


def _part(base,target):
    name=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(base),target))
    if name.startswith('../') or '\\' in name or PurePosixPath(name).is_absolute():raise ValueError('Некорректный путь внутри XLSX')
    return name


def _xml(archive,name):
    data=archive.read(name)
    if b'<!DOCTYPE' in data or b'<!ENTITY' in data:raise ValueError('Неподдерживаемое объявление XML')
    return ET.fromstring(data)


def read_table(source,on_progress=lambda *_:None):
    """Read the first worksheet, including Excel shared strings and sparse cells."""
    if Path(source).suffix.lower()!='.xlsx':raise ValueError('Выберите файл .xlsx')
    try:
        with ZipFile(source) as archive:
            if sum(info.file_size for info in archive.infolist())>128*1024*1024:
                raise ValueError('Распакованный XLSX превышает 128 МБ')
            relations=_xml(archive,'_rels/.rels')
            workbook_relation=next((rel for rel in relations if rel.get('Type','').endswith('/officeDocument')),None)
            if workbook_relation is None or workbook_relation.get('TargetMode')=='External':raise ValueError('В XLSX нет книги')
            workbook_path=_part('',workbook_relation.get('Target',''))
            workbook=_xml(archive,workbook_path)
            sheet=next((node for node in workbook.iter() if _tag(node)=='sheet'),None)
            if sheet is None:raise ValueError('В XLSX нет листов')
            relation_id=next((value for key,value in sheet.attrib.items() if key.endswith('}id')),None)
            relation_path=posixpath.join(posixpath.dirname(workbook_path),'_rels',posixpath.basename(workbook_path)+'.rels')
            rels=_xml(archive,relation_path)
            relation=next((rel for rel in rels if rel.get('Id')==relation_id),None)
            if relation is None or relation.get('TargetMode')=='External' or not relation.get('Type','').endswith('/worksheet'):
                raise ValueError('Первый лист XLSX должен быть таблицей')
            shared=[]
            shared_relation=next((rel for rel in rels if rel.get('Type','').endswith('/sharedStrings')),None)
            if shared_relation is not None:
                if shared_relation.get('TargetMode')=='External':raise ValueError('Внешние строки XLSX не поддерживаются')
                shared=[''.join(node.text or '' for node in entry.iter() if _tag(node)=='t')
                        for entry in _xml(archive,_part(workbook_path,shared_relation.get('Target','')))]
            worksheet=_xml(archive,_part(workbook_path,relation.get('Target','')))
            rows=[]
            cells_count=0
            previous=0
            for row in (node for node in worksheet.iter() if _tag(node)=='row'):
                number=int(row.get('r',previous+1))
                if number<=previous or number>MAX_ROWS:raise ValueError('Некорректный номер строки XLSX')
                rows.extend([] for _ in range(number-previous-1))
                values={}
                last_column=0
                for cell in row:
                    if _tag(cell)!='c':continue
                    cells_count+=1
                    if cells_count>MAX_CELLS:raise ValueError('Слишком много ячеек XLSX')
                    reference=cell.get('r',f'{column_name(last_column+1)}{number}')
                    match=re.fullmatch(r'([A-Z]+)([1-9]\d*)',reference)
                    if match is None or int(match[2])!=number:raise ValueError('Некорректный адрес ячейки XLSX')
                    column=0
                    for char in match[1]:column=column*26+ord(char)-64
                    if column>16384 or column in values:raise ValueError('Некорректная колонка XLSX')
                    last_column=column
                    children={_tag(node):node for node in cell}
                    if 'f' in children:raise ValueError(f'{reference}: замените формулу её значением перед импортом')
                    kind=cell.get('t','n')
                    value=children['v'].text or '' if 'v' in children else ''
                    if kind=='s':
                        index=int(value)
                        if index<0 or index>=len(shared):raise ValueError('Некорректная ссылка на строку XLSX')
                        value=shared[index]
                    elif kind=='inlineStr':value=''.join(node.text or '' for node in cell.iter() if _tag(node)=='t')
                    elif kind=='e':raise ValueError(f'{reference}: ошибка Excel {value}')
                    if len(value)>32767:raise ValueError(f'{reference}: слишком длинное значение')
                    values[column]=re.sub(r'_x([0-9a-fA-F]{4})_',lambda match:chr(int(match[1],16)),value)
                cells_count+=max(values,default=0)-len(values)
                if cells_count>MAX_CELLS:raise ValueError('Слишком много ячеек XLSX')
                rows.append([values.get(column,'') for column in range(1,max(values,default=0)+1)])
                previous=number
                if number%100==0:on_progress(number,MAX_ROWS,'Чтение XLSX')
            return rows
    except (BadZipFile,ET.ParseError,KeyError,OverflowError) as exc:
        raise ValueError(f'Не удалось прочитать XLSX: {exc}') from exc
