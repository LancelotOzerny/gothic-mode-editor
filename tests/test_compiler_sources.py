import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gothic_editor.core.compiler_sources import prepare_compiler_sources
from gothic_editor.core.daedalus_merge import normalize_compiler_whitespace
from gothic_editor.core.potion_components import PotionComponents
from gothic_editor.core.project_tools import ProjectTools
from gothic_editor.core.scripts import parse_items


class CompilerSourceTests(unittest.TestCase):
    def test_utf8_cyrillic_scripts_are_converted_to_cp1251_only_in_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            original=root/'original.d'
            text='INSTANCE ItSc_Test(C_Item) {name="Свиток разработчика";};\n'
            original.write_text(text,encoding='utf-8-sig')
            original_bytes=original.read_bytes()
            staging=root/'staging'
            staging.mkdir()
            target=staging/'Scroll.d'
            shutil.copy2(original,target)
            prepare_compiler_sources(staging,lambda _:None)
            self.assertEqual(target.read_bytes(),text.replace('\n','\r\n').encode('cp1251'))
            self.assertEqual(original.read_bytes(),original_bytes)

    @unittest.skipUnless(os.environ.get('GOTHIC_TEST_COMPILER'),'Optional real GDC')
    def test_compiled_dat_contains_russian_title_in_game_encoding(self):
        from gothic_editor.core.compiler_runner import run_compiler
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            title='Свиток разработчика'
            code='class C_Item { var string name; };\nINSTANCE ItSc_Test(C_Item) { name="'+title+'"; };\n'
            (root/'Scroll.d').write_text(code,encoding='utf-8')
            manifest=root/'Gothic.src'
            manifest.write_text('Scroll.d\n')
            prepare_compiler_sources(root,lambda _:None)
            output=root/'Gothic.dat'
            log=root/'compiler.log'
            result=run_compiler([os.environ['GOTHIC_TEST_COMPILER'],str(manifest),'--output-dat',str(output)],root,log)
            self.assertEqual(result.returncode,0,log.read_text('utf-8'))
            self.assertIn(title.encode('cp1251'),output.read_bytes())
            self.assertNotIn(title.encode('utf-8'),output.read_bytes())

    def test_mixed_newlines_are_crlf_without_changing_encoding_or_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'Mixed.D'
            raw = '// Зелье\nconst int A=1;\r\nconst int B=2;\r'.encode('cp1251')
            script.write_bytes(raw)
            manifest = root / 'Gothic.SRC'
            manifest.write_bytes(b'Mixed.D\nOther.d\r\n')
            prepare_compiler_sources(root, lambda _: None)
            expected = raw.replace(b'\r\n', b'\n').replace(b'\r', b'\n').replace(b'\n', b'\r\n')
            self.assertEqual(script.read_bytes(), expected)
            self.assertEqual(manifest.read_bytes(), b'Mixed.D\r\nOther.d\r\n')
            prepare_compiler_sources(root, lambda _: None)
            self.assertEqual(script.read_bytes(), expected)

    def test_form_feed_is_replaced_only_outside_strings_and_comments(self):
        text=('func void Test() {\r\n\f Print("keep\f \\\" quote");\r\n'
              '// comment\f\r\n/* block\f */\r\n};')
        normalized,count=normalize_compiler_whitespace(text)
        self.assertEqual(count,1)
        self.assertEqual(normalized,text.replace('\r\n\f Print','\r\n  Print',1))
        self.assertEqual(normalized.count('\r\n'),text.count('\r\n'))
        self.assertEqual(normalized.count('\f'),3)

    def test_cp1251_and_unchanged_files_are_preserved_in_compiler_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            original=root/'original'
            original.mkdir()
            source=original/'Vatras.D'
            raw='// Кириллица\r\nfunc void Test(){\r\n\f return;\r\n};'.encode('cp1251')
            source.write_bytes(raw)
            (original/'Other.d').write_bytes(b'// unchanged\r\n')
            staging=root/'staging'
            shutil.copytree(original,staging)
            messages=[]
            prepare_compiler_sources(staging,messages.append)
            self.assertEqual((staging/'Vatras.D').read_bytes(),raw.replace(b'\x0c',b' '))
            self.assertEqual(source.read_bytes(),raw)
            self.assertEqual((staging/'Other.d').read_bytes(),b'// unchanged\r\n')
            self.assertEqual(len(messages),1)

    def test_compile_normalizes_staging_without_modifying_game_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            project,game=root/'project',root/'game'
            (project/'Scripts/Content').mkdir(parents=True)
            content=game/'_work/Data/Scripts/Content'
            script=content/'Story/Dialoge/Vatras.D'
            script.parent.mkdir(parents=True)
            original=b'func void Test() {\r\n\x0c Print("literal\x0c");\r\n};'
            script.write_bytes(original)
            (content/'Gothic.src').write_bytes(b'Story\\Dialoge\\Vatras.D\r\n')
            compiler=root/'DaedalusCompiler.dll'
            compiler.write_bytes(b'compiler')

            def compile_command(command,**kwargs):
                prepared=Path(command[2]).parent/'Story/Dialoge/Vatras.D'
                self.assertEqual(prepared.read_bytes(),original.replace(b'\x0c Print',b'  Print'))
                Path(command[4]).write_bytes(b'compiled DAT')
                return subprocess.CompletedProcess(command,0)

            with patch('gothic_editor.core.project_tools.shutil.which',return_value='dotnet'), \
                    patch('gothic_editor.core.compiler_runner.subprocess.run',side_effect=compile_command):
                result=ProjectTools(project,game,str(compiler)).compile()
            from gothic_editor.core.mod_archive import read_mod
            self.assertEqual(read_mod(result.output)['_work/data/scripts/_compiled/gothic.dat'],b'compiled DAT')
            self.assertEqual(script.read_bytes(),original)

    def test_json_escaped_newlines_decode_into_real_daedalus_newlines(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            source=root/'Potion.d'
            source.write_bytes('INSTANCE Potion(C_Item)\r\n{\r\n name = "Зелье";\r\n};'.encode('cp1251'))
            item=parse_items(source,'game')[0]
            store=PotionComponents(root/'project')
            folder=store.import_item(item)
            raw=(folder/'item.json').read_text('utf-8')
            self.assertIn(r'\r\n',raw)
            data=json.loads(raw)
            self.assertEqual(data['template'],item.text)
            rendered=store.render_instance(data)
            self.assertIn('\r\n{\r\n',rendered)
            self.assertNotIn(r'\r\n',rendered)


if __name__=='__main__':
    unittest.main()
