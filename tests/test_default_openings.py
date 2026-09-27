"""Default opening content, entry semantics, editability and isolated first-run contracts."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
import chess
import chess.engine
from default_opening_source import load_source, parse_source_row, source_hierarchy
from default_opening_builder import generate_library
from default_opening_install import seed_default_openings, DEFAULT_LIBRARY_NAME
from opening_book_application import apply_book
from opening_book_models import BookDetails, MoveDetails, position_identity
from opening_book_reader import read_library
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService
from opening_intelligence_application import assess_game
from opening_intelligence_lookup import OpeningBookLookup
from opening_intelligence_service import matches_opening
from opening_intelligence_models import OpeningQuery
from opening_library_repository import OpeningLibraryRepository
from opening_library_service import OpeningLibraryService
from opening_library_package import inspect_package, semantic_identity, write_library_package
from opening_accuracy import opening_phase
from opening_workspace import opening_moments

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / 'assets/openings'
SOURCE = ROOT / 'data/default_openings/source'
CURATION = ROOT / 'data/default_openings/curation.json'


def ucis(san):
    board = chess.Board()
    for token in san.split():
        board.push_san(token)
    return tuple(m.uci() for m in board.move_stack)


TRUST = {
    'French Defense': ('e4 e6 d4 d5 e5', 'd4 d6', 'black'),
    'Caro-Kann Defense': ('e4 c6 d4 d5 e5', 'e4 e6', 'black'),
    'Sicilian Defense': ('e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6', 'c4 c5', 'black'),
    'Pirc Defense': ('e4 d6 d4 Nf6 Nc3 g6', 'd4 d6', 'black'),
    'Scandinavian Defense': ('e4 d5 exd5 Qxd5', 'd4 d5', 'black'),
    "King's Indian Defense": ('d4 Nf6 c4 g6 Nc3 Bg7 e4 d6', 'd4 Nf6 c4 g6 Nc3 d5', 'black'),
    "Queen's Gambit": ('d4 d5 c4', 'd4 Nf6 c4', 'both'),
    'Nimzo-Indian Defense': ('d4 Nf6 c4 e6 Nc3 Bb4', 'd4 Nf6 c4 e6 Nf3 Bb4+', 'black'),
    'English Opening': ('c4 e5', 'e4 c5', 'white'),
    'London System': ('d4 d5 Nf3 Nf6 Bf4', 'd4 d5 Nf3 Nf6 Bg5', 'white'),
    'Ruy Lopez': ('e4 e5 Nf3 Nc6 Bb5', 'e4 e5 Nf3 Nc6 Bc4', 'white'),
    'Italian Game': ('e4 e5 Nf3 Nc6 Bc4', 'e4 e5 Nf3 Nc6 Bb5', 'white'),
}


class DefaultOpeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshots = read_library(BUNDLE / f'{DEFAULT_LIBRARY_NAME}.cwbook')
        cls.books = {s.book.name:s for s in cls.snapshots}
        cls.lookups = {name:OpeningBookLookup(s) for name,s in cls.books.items()}
        cls.config = json.loads(CURATION.read_text(encoding='utf-8'))

    def setUp(self):
        guard = patch.object(chess.engine.SimpleEngine, 'popen_uci', side_effect=AssertionError('No automatic engine'))
        guard.start(); self.addCleanup(guard.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_official_rows_legal_and_hash_pinned(self):
        rows, rejected = load_source(SOURCE)
        self.assertGreater(len(rows), 3000)
        self.assertFalse(rejected)
        for row in rows:
            checked = parse_source_row(dict(eco=row.eco, name=row.name, pgn=row.pgn,
                uci=' '.join(row.uci), epd=row.epd), row.source)
            self.assertEqual(checked, row)

    def test_malformed_uci_epd_pgn_rejected(self):
        row = dict(eco='C00',name='French Defense',pgn='1. e4 e6')
        for changes in [dict(uci='e2e4 e7e5'),dict(epd=chess.Board().epd()),dict(pgn='1. e5'),
                        dict(pgn='1. e4 e6 garbage'),dict(eco='F99')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_source_row(dict(row,**changes),'fixture')

    def test_hierarchy_alias_and_promotion(self):
        self.assertEqual(source_hierarchy('Sicilian Defense: Najdorf Variation, English Attack',self.config),
                         ('Sicilian Defense',('Najdorf Variation','English Attack')))
        self.assertEqual(source_hierarchy("Queen's Pawn Game: London System",self.config),('London System',()))
        self.assertEqual(source_hierarchy('London System, with Bd3',self.config),('London System',('with Bd3',)))

    def test_twelve_family_entries_sides_and_nearby_nonmatches(self):
        for family,(yes,no,side) in TRUST.items():
            with self.subTest(family=family):
                lookup=self.lookups[family]
                self.assertEqual(lookup.snapshot.book.repertoire_side,side)
                result=assess_game(lookup,ucis(yes))
                self.assertTrue(result.entered_book)
                other=assess_game(lookup,ucis(no))
                self.assertFalse(other.entered_book)
                self.assertFalse(any(r.deviation for r in other.moves))
                self.assertFalse(opening_moments(other,None,None))

    def test_pirc_setup_is_not_entry_in_either_interface(self):
        for line in ('d4 d6','e4 d6','e4 d6 d4 Nf6'):
            result=assess_game(self.lookups['Pirc Defense'],ucis(line))
            self.assertFalse(result.entered_book)
            self.assertFalse(any(r.position_in_book or r.deviation for r in result.moves))
            self.assertIsNone(opening_phase(result))
            self.assertIsNone(apply_book(self.books['Pirc Defense'],ucis(line)).first_deviation_ply)

    def test_deviation_only_after_entry_and_accuracy_arithmetic_untouched(self):
        result=assess_game(self.lookups['Pirc Defense'],ucis('e4 d6 d4 Nf6 Nc3 g6 a3'))
        self.assertEqual(result.entry_ply,6)
        self.assertEqual(result.first_deviation_ply,7)
        self.assertEqual(opening_phase(result).start_ply,7)
        self.assertFalse(any(r.deviation for r in result.moves[:6]))

    def test_named_variation_not_before_defining_board(self):
        lookup=self.lookups['French Defense']
        self.assertNotEqual(assess_game(lookup,ucis('e4 e6 d4 d5')).final_named_variation,'Advance Variation')
        self.assertEqual(assess_game(lookup,ucis('e4 e6 d4 d5 e5')).final_named_variation,'Advance Variation')

    def test_transposed_entry_and_name_have_same_visible_identity(self):
        for family,a,b in [('French Defense','e4 e6 d4 d5 e5','d4 e6 e4 d5 e5'),
                           ('Pirc Defense','e4 d6 d4 Nf6 Nc3 g6','d4 d6 e4 Nf6 Nc3 g6'),
                           ('London System','d4 d5 Nf3 Nf6 Bf4','Nf3 d5 d4 Nf6 Bf4')]:
            with self.subTest(family=family):
                first=assess_game(self.lookups[family],ucis(a));second=assess_game(self.lookups[family],ucis(b))
                self.assertTrue(first.entered_book and second.entered_book)
                self.assertEqual(first.moves[-1].after_position_id,second.moves[-1].after_position_id)
                self.assertEqual(first.final_variation.paths,second.final_variation.paths)
                if second.final_named_variation:
                    self.assertTrue(matches_opening(second,OpeningQuery(variation_name=second.final_named_variation)))

    def test_hierarchy_preserved_and_named_ids_deduplicate_routes(self):
        r=assess_game(self.lookups['Sicilian Defense'],ucis('e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Be3'))
        self.assertEqual([n.name for n in r.final_variation.path],['Najdorf Variation','English Attack'])
        for snapshot in self.snapshots:
            keys=[(m.from_position_id,m.move_uci) for m in snapshot.moves]
            self.assertEqual(len(keys),len(set(keys)))
            self.assertTrue(all(m.weight==50 and not m.preferred for m in snapshot.moves))

    def test_entry_metadata_affects_currentness(self):
        original=self.books['French Defense'];meta=json.loads(original.book.metadata_json)
        meta['opening_entry']['positions']=meta['opening_entry']['positions'][1:]
        changed=replace(original,book=replace(original.book,metadata_json=json.dumps(meta)))
        self.assertNotEqual(OpeningBookLookup(original).provenance.membership_identity,
                            OpeningBookLookup(changed).provenance.membership_identity)

    def test_inactive_entry_path_cannot_activate(self):
        original=self.books['Pirc Defense']
        disabled=replace(original,moves=tuple(replace(m,active=False) for m in original.moves))
        self.assertFalse(assess_game(OpeningBookLookup(disabled),ucis('e4 d6 d4 Nf6 Nc3 g6')).entered_book)

    def test_reproducible_bytes_and_polyglot(self):
        result=generate_library(SOURCE,CURATION,self.root/'build')
        original=json.loads((BUNDLE/'manifest.json').read_text(encoding='utf8'))
        self.assertEqual(result['cwbook_sha256'],original['cwbook_sha256'])
        self.assertEqual(result['polyglot'],original['polyglot'])
        self.assertFalse(result['rejected_rows'])
        self.assertEqual(result['families'],96)

    def test_clean_copy_seed_restart_and_customization(self):
        repository=OpeningLibraryRepository(self.root/'opening_books')
        library=seed_default_openings(repository,BUNDLE)
        self.assertEqual(library.name,DEFAULT_LIBRARY_NAME)
        self.assertEqual(len(library.books),96)
        self.assertEqual(OpeningLibraryService(repository).authoring_library().library_id,library.library_id)
        repo=OpeningBookRepository.open(library.path)
        try:
            book=repo.books()[0]
            details=BookDetails('My customized opening',book.description,book.version,book.status,book.metadata_json)
            repo.update_book(book.book_id,details)
            service=OpeningBookService(repo)
            new=service.create_book(BookDetails('My new line'))
            service.save_move(new,chess.STARTING_FEN,'e2e4')
        finally:repo.close()
        before=library.path.read_bytes()
        self.assertIsNone(seed_default_openings(repository,BUNDLE))
        self.assertEqual(before,library.path.read_bytes())
        self.assertEqual(len(OpeningLibraryService(repository).list_books()),97)

    def test_existing_empty_catalog_and_existing_file_not_reseeded(self):
        repo=OpeningLibraryRepository(self.root/'existing')
        with repo.write():pass
        self.assertIsNone(seed_default_openings(repo,BUNDLE))
        other=OpeningLibraryRepository(self.root/'loose');other.root.mkdir()
        (other.root/'private.cwbook').write_bytes(b'owner placeholder')
        self.assertIsNone(seed_default_openings(other,BUNDLE))
        self.assertFalse(other.catalog.exists())

    def test_bad_seed_hash_fails_before_writes(self):
        bundle=self.root/'bad';bundle.mkdir()
        (bundle/'manifest.json').write_text(json.dumps(dict(cwbook_sha256='invalid')))
        (bundle/f'{DEFAULT_LIBRARY_NAME}.cwbook').write_bytes(b'invalid')
        repo=OpeningLibraryRepository(self.root/'target')
        with self.assertRaises(ValueError):seed_default_openings(repo,bundle)
        self.assertFalse(repo.root.exists())

    def test_load_save_roundtrip_and_authoring_stays_editable(self):
        path=self.root/'copy.cwbook';write_library_package(self.snapshots,path)
        loaded=inspect_package(path).books
        self.assertEqual([semantic_identity(s) for s in loaded],[semantic_identity(s) for s in self.snapshots])
        repo=OpeningBookRepository.open(path)
        try:
            french=next(s for s in loaded if s.book.name=='French Defense')
            move=next(m for m in french.moves if m.variation_name=='Advance Variation')
            service=OpeningBookService(repo)
            service.edit_move(french.book.book_id,move.move_id,MoveDetails(variation_name='My Advance'))
            updated=repo.snapshot(french.book.book_id)
            self.assertIn('My Advance',[m.variation_name for m in updated.moves])
            fen=french.position(move.to_position_id).canonical_fen
            existing={m.move_uci for m in french.branches(move.to_position_id)}
            addition=next(m.uci() for m in chess.Board(fen).legal_moves if m.uci() not in existing)
            service.save_move(french.book.book_id,fen,addition)
            repo.delete_branch(french.book.book_id,move.move_id)
            self.assertNotIn(move.move_id,[m.move_id for m in repo.snapshot(french.book.book_id).moves])
        finally:repo.close()

    def test_studio_does_not_repeat_variation_heading_along_one_route(self):
        from opening_book_navigation import branch_paths
        snapshot=self.books['French Defense']
        branches=branch_paths(snapshot)
        by_id={m.move_id:m for m in snapshot.moves}
        for branch in branches:
            if branch.label=='Advance Variation':
                earlier=[by_id[i].variation_name for i in branch.parent_path if by_id[i].variation_name]
                self.assertTrue(not earlier or earlier[-1]!='Advance Variation')
        self.assertTrue(any(b.label=='Advance Variation' for b in branches))

    def test_studio_loads_temporary_seed_without_engine_or_game_db(self):
        with patch.dict(os.environ,CHESSWIZARD_DATA_DIR=str(self.root)), \
             patch('theme_core.active._default_service',None):
            seed_default_openings(bundle=BUNDLE)
            from merlin_ui.opening_book_studio import OpeningBookStudio
            window=tk.Tk();window.withdraw()
            try:
                with patch('merlin_ui.opening_book_studio.messagebox.showerror',side_effect=AssertionError('Studio error')):
                    studio=OpeningBookStudio(window)
                    self.assertEqual(len(OpeningLibraryService().list_books()),96)
                    self.assertIsNotNone(studio.session)
                    self.assertFalse(studio.repository.read_only)
                    self.assertFalse((self.root/'merlin.db').exists())
            finally:
                if 'studio' in locals():studio.close()
                elif window.winfo_exists():window.destroy()
