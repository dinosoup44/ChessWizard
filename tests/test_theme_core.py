"""Data-only theme contracts, including adversarial inputs and additive storage."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
from PIL import Image, PngImagePlugin
from theme_core import Theme, BoardColors, PIECE_ROLES, DECORATION_SLOTS, ThemeRepository
from theme_core.assets import decode_png, load_png, reject_links, MAX_FILE_BYTES, MAX_THEME_BYTES
from theme_core.editor import ThemeDraft
from theme_core.repository import unique_object
from theme_core.preview_states import PREVIEW_STATES
import chess


def png_bytes(size=(40,60)):
    image=Image.new("RGBA",size,(30,90,160,128));stream=BytesIO()
    image.save(stream,format="PNG");return stream.getvalue()


class ThemeModelTests(unittest.TestCase):
    def complete(self):
        return Theme("test","Test",pieces={r:f"pieces/{r}.png" for r in PIECE_ROLES})

    def test_complete_roundtrip_and_immutable_mapping(self):
        theme=self.complete()
        self.assertTrue(theme.complete)
        self.assertEqual(Theme.from_data(json.loads(json.dumps(theme.to_data()))),theme)
        with self.assertRaises(TypeError):theme.pieces['white_king']='other.png'

    def test_missing_roles_are_draft_not_complete(self):
        t=Theme("draft","Draft",pieces={'white_king':'pieces/white_king.png'})
        self.assertFalse(t.complete);self.assertEqual(len(t.missing_roles),11)

    def test_invalid_colors_and_missing_required_colors(self):
        for value in ('red','#12345','#gg0000','',None):
            with self.subTest(value=value),self.assertRaises(ValueError):BoardColors(light_square=value)
        data=self.complete().to_data();del data['colors']['light_square']
        with self.assertRaises(ValueError):Theme.from_data(data)

    def test_unknown_and_duplicate_roles_or_fields(self):
        with self.assertRaises(ValueError):Theme("a","A",pieces={'white_dragon':'pieces/white_dragon.png'})
        for text in ('{"white_king":1,"white_king":2}','{"name":"a","name":"b"}'):
            with self.assertRaises(ValueError):json.loads(text,object_pairs_hook=unique_object)

    def test_traversal_absolute_paths_and_unsupported_schema(self):
        for path in ('../x.png','/x.png','C:/x.png','pieces/../x.png','pieces\\x.png','pieces/white_king.exe'):
            with self.subTest(path=path),self.assertRaises(ValueError):Theme('a','A',pieces={'white_king':path})
        with self.assertRaises(ValueError):replace(self.complete(),version=2)
        with self.assertRaises(ValueError):replace(self.complete(),theme_id='../bad')


class ThemeAssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.file=self.root/'input.png';self.file.write_bytes(png_bytes())

    def test_png_alpha_and_metadata_canonicalization(self):
        metadata=PngImagePlugin.PngInfo();metadata.add_text('ignored','data only')
        image=Image.open(BytesIO(png_bytes()));stream=BytesIO();image.save(stream,format='PNG',pnginfo=metadata)
        asset=decode_png(stream.getvalue())
        self.assertEqual((asset.width,asset.height),(40,60));self.assertTrue(asset.transparent)
        self.assertEqual(asset.image().info,{})

    def test_executable_archive_and_unknown_extensions_rejected(self):
        for ext in ('.exe','.dll','.py','.js','.bat','.cmd','.ps1','.zip','.jpg','.txt'):
            path=self.file.with_suffix(ext);path.write_bytes(png_bytes())
            with self.subTest(ext=ext),self.assertRaises(ValueError):load_png(path)

    def test_invalid_or_disguised_image_rejected(self):
        for data in (b'not a png',png_bytes()[:35],b'MZ'+png_bytes()):
            self.file.write_bytes(data)
            with self.assertRaises(ValueError):load_png(self.file)
        stream=BytesIO();Image.new('RGB',(5,5)).save(stream,format='JPEG')
        with self.assertRaises(ValueError):decode_png(stream.getvalue())

    def test_size_and_dimension_limits(self):
        with self.assertRaises(ValueError):decode_png(b'0'*(MAX_FILE_BYTES+1))
        with self.assertRaises(ValueError):decode_png(png_bytes((2049,1)))

    def test_animation_rejected(self):
        stream=BytesIO();a=Image.new('RGBA',(5,5),'red');b=Image.new('RGBA',(5,5),'blue')
        a.save(stream,format='PNG',save_all=True,append_images=[b],duration=10)
        with self.assertRaises(ValueError):decode_png(stream.getvalue())

    def test_symlink_and_reparse_point_rejected(self):
        with patch.object(Path,'is_symlink',return_value=True),self.assertRaises(ValueError):reject_links(self.file)
        info=self.file.stat()
        class LinkedStat:
            st_file_attributes=0x400
        with patch.object(Path,'lstat',return_value=LinkedStat()),self.assertRaises(ValueError):reject_links(self.file)

    def test_failed_assignment_preserves_previous_valid_image(self):
        d=ThemeDraft();asset=d.assign('white_king',self.file)
        self.file.write_bytes(b'invalid')
        with self.assertRaises(ValueError):d.assign('white_king',self.file)
        self.assertIs(d.pieces['white_king'],asset)
        d.clear('white_king');self.assertEqual(len(d.missing_roles),12)

    def test_save_load_independent_copies_and_prior_snapshots_unchanged(self):
        repo=ThemeRepository(self.root/'themes');d=ThemeDraft(name='Artist / Set')
        for role in PIECE_ROLES:d.assign(role,self.file)
        d.assign('corner_top_left',self.file)
        saved=d.save(repo);snapshot={p.relative_to(repo.root):p.read_bytes() for p in repo.root.rglob('*') if p.is_file()}
        self.file.unlink()
        loaded=repo.load(saved.theme.theme_id)
        self.assertTrue(loaded.theme.complete);self.assertEqual(len(loaded.pieces),12)
        newer=d.save(repo);self.assertNotEqual(saved.theme.theme_id,newer.theme.theme_id)
        self.assertEqual(len(repo.list_themes()),2)
        for path,data in snapshot.items():self.assertEqual((repo.root/path).read_bytes(),data)

    def test_incomplete_theme_saves_as_draft_and_no_active_setting(self):
        repo=ThemeRepository(self.root/'themes');loaded=ThemeDraft(name='Draft').save(repo)
        self.assertFalse(loaded.theme.complete)
        self.assertEqual(set(p.name for p in repo.root.iterdir()),{loaded.theme.theme_id})
        self.assertFalse(repo.load(loaded.theme.theme_id).theme.complete)

    def test_every_package_file_is_checked(self):
        repo=ThemeRepository(self.root/'themes');saved=ThemeDraft(name='Test').save(repo)
        folder=repo.root/saved.theme.theme_id
        for name in ('script.py','archive.zip','unlisted.png','config.json'):
            path=folder/name;path.write_bytes(png_bytes())
            with self.subTest(name=name),self.assertRaises(ValueError):repo.load(saved.theme.theme_id)
            path.unlink()

    def test_missing_referenced_asset_and_traversal_id_rejected(self):
        repo=ThemeRepository(self.root/'themes');d=ThemeDraft(name='Test');d.assign('white_king',self.file)
        saved=d.save(repo);(repo.root/saved.theme.theme_id/'pieces/white_king.png').unlink()
        with self.assertRaises(ValueError):repo.load(saved.theme.theme_id)
        with self.assertRaises(ValueError):repo.load('../elsewhere')

    def test_invalid_draft_name_cannot_install_a_set(self):
        repo=ThemeRepository(self.root/'themes')
        with self.assertRaises(ValueError):ThemeDraft().save(repo)
        self.assertFalse(repo.root.exists())


class ThemePortabilityTests(unittest.TestCase):
    def test_core_imports_without_desktop_database_or_analyzers(self):
        code="""
import builtins
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.startswith(('tkinter','sqlite3','analyze_','analysis_','candidate_line','quality_gate','proof_escalation','the_scale')):
        raise AssertionError(name)
    return original(name,*args,**kwargs)
builtins.__import__=guarded
import theme_core
from theme_core import editor, preview_states, board_geometry
assert len(preview_states.PREVIEW_STATES)==10
"""
        result=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_launcher_import_has_no_database_or_analyzer_dependency(self):
        code="""
import builtins
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.startswith(('sqlite3','database','analyze_','analysis_','candidate_line','quality_gate','proof_escalation','the_scale')):
        raise AssertionError(name)
    return original(name,*args,**kwargs)
builtins.__import__=guarded
import run_art_tester
"""
        result=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_all_fens_parse_and_role_specific_samples_match(self):
        self.assertEqual(len(PREVIEW_STATES),10)
        for sample in PREVIEW_STATES:chess.Board(sample.fen)
        for name,kind in (('Pawns only',chess.PAWN),('Knights only',chess.KNIGHT),('Bishops only',chess.BISHOP),('Rooks only',chess.ROOK)):
            b=chess.Board(next(s.fen for s in PREVIEW_STATES if s.name==name))
            self.assertEqual({p.piece_type for p in b.piece_map().values()},{kind})
            self.assertEqual({p.color for p in b.piece_map().values()},{True,False})
