"""Isolated authoring graph, export and membership contracts; no live engine/data writes."""
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
import chess
import chess.engine
import chess.polyglot
from opening_book_models import (BookDetails,MoveDetails,SourceDetails,position_identity)
from opening_book_repository import OpeningBookRepository
from opening_book_service import OpeningBookService,branch_browser
from opening_book_session import OpeningBookSession
from opening_book_polyglot import export_polyglot,verify_polyglot,export_entries
from opening_book_application import apply_book,apply_stored_game
from tests.opening_book_fixtures import author_proof_book,add_line
from tests.test_game_analysis import TemporaryAnalysis
from tests.test_game_import import pgn

CASTLE="r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
PROMOTION="7k/P7/8/8/8/8/8/7K w - - 0 1"


def ucis(line,fen=chess.STARTING_FEN):
    board=chess.Board(fen);result=[]
    for notation in line.split():
        move=board.parse_san(notation);result.append(move.uci());board.push(move)
    return tuple(result)


class LibraryFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"library.cwbook"
        self.repo=OpeningBookRepository.create(self.path)
        self.addCleanup(lambda:self.repo.close())
        self.service=OpeningBookService(self.repo)
        self.bid=self.service.create_book(BookDetails("Test"))
        self.session=OpeningBookSession(self.service,self.bid)
        guard=patch.object(chess.engine.SimpleEngine,"popen_uci",side_effect=AssertionError("No engine"))
        guard.start();self.addCleanup(guard.stop)

    def save(self,line):
        add_line(self.session,line)
        return self.repo.snapshot(self.bid)


class IdentityTests(unittest.TestCase):
    def test_start_key_and_clock_independence(self):
        initial=position_identity(chess.STARTING_FEN)
        self.assertEqual(initial.polyglot_key,"463b96181691fc9c")
        self.assertEqual(initial,position_identity(chess.STARTING_FEN.replace("0 1","20 45")))

    def test_transposition_and_irrelevant_ep(self):
        a=chess.Board();b=chess.Board()
        for uci in ucis("d4 Nf6 Nf3"):a.push_uci(uci)
        for uci in ucis("Nf3 Nf6 d4"):b.push_uci(uci)
        self.assertEqual(position_identity(a),position_identity(b))
        self.assertIsNotNone(b.ep_square)
        self.assertEqual(position_identity(b).canonical_fen.split()[3],"-")

    def test_pinned_ep_preserved_castling_and_turn_distinct(self):
        board=chess.Board("k3r3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        self.assertFalse(board.has_legal_en_passant())
        self.assertTrue(board.has_pseudo_legal_en_passant())
        self.assertEqual(position_identity(board).canonical_fen.split()[3],"d6")
        without=board.copy();without.ep_square=None
        self.assertNotEqual(position_identity(board),position_identity(without))
        a=position_identity(CASTLE)
        self.assertNotEqual(a,position_identity(CASTLE.replace("KQkq","-")))
        self.assertNotEqual(a,position_identity(CASTLE.replace(" w "," b ")))

    def test_invalid_and_variant_rejected(self):
        for value in ("8/8/8/8/8/8/8/8 w - - 0 1",chess.Board(chess960=True)):
            with self.assertRaises(ValueError):position_identity(value)


class AuthoringTests(LibraryFixture):
    def test_create_update_multi_book_notes_isolated_and_reopen(self):
        second=self.service.create_book(BookDetails("Other",version="2",status="active",metadata_json='{"tags":["repertoire"]}'))
        a=self.repo.snapshot(self.bid);b=self.repo.snapshot(second)
        self.assertEqual(a.book.root_position_id,b.book.root_position_id)
        self.repo.set_position_note(self.bid,a.book.root_position_id,"Original position text.")
        self.assertEqual(self.repo.snapshot(second).positions[0].position_note,"")
        self.repo.update_book(self.bid,BookDetails("Renamed",version="0.2",status="archived"))
        self.repo.close();self.repo=OpeningBookRepository.open(self.path)
        self.assertEqual(self.repo.books()[0].version,"0.2")
        self.assertEqual(self.repo.books()[0].status,"archived")
        self.assertEqual(len(self.repo.books()),2)

    def test_pending_not_saved_until_explicit_save(self):
        before=self.path.read_bytes()
        self.session.stage("e2e4")
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(len(self.repo.snapshot(self.bid).moves),0)
        self.assertEqual(self.session.board.fen(),chess.STARTING_FEN)
        with self.assertRaises(ValueError):self.session.back()
        self.session.discard()
        self.session.stage_notation("e4");self.session.save()
        self.assertEqual(len(self.repo.snapshot(self.bid).moves),1)
        self.assertEqual(self.session.cursor,1)

    def test_illegal_save_and_invalid_weights_leave_library_unchanged(self):
        before=self.path.read_bytes()
        for move in ("e2e5","0000"):
            with self.assertRaises(ValueError):self.service.save_move(self.bid,chess.STARTING_FEN,move)
            with self.assertRaises(ValueError):self.session.stage(move)
        with self.assertRaises(ValueError):self.session.stage_notation("--")
        for weight in (0,101,True,1.5):
            with self.assertRaises(ValueError):MoveDetails(weight=weight)
        with self.assertRaises(ValueError):MoveDetails(active=False,preferred=True)
        with self.assertRaises(ValueError):BookDetails("X",metadata_json='{"x":NaN}')
        self.assertEqual(self.path.read_bytes(),before)

    def test_branch_case_navigation_siblings_and_reload(self):
        for line in ("e4 e5","e4 c5 Nf3","e4 c5 Nc3","e4 c6","d4"):self.save(line)
        self.session.root()
        self.assertEqual({m.san for m in self.session.snapshot.branches(self.session.position_id)},{"e4","d4"})
        e4=next(m for m in self.session.snapshot.branches(self.session.position_id) if m.san=="e4")
        self.session.follow(e4.move_id)
        self.assertEqual({m.san for m in self.session.snapshot.branches(self.session.position_id)},{"e5","c5","c6"})
        c5=next(m for m in self.session.snapshot.branches(self.session.position_id) if m.san=="c5")
        self.session.follow(c5.move_id)
        position=self.session.position_id
        self.assertEqual({m.san for m in self.session.snapshot.branches(position)},{"Nf3","Nc3"})
        self.session.back();self.session.forward();self.assertEqual(self.session.position_id,position)
        self.repo.close();self.repo=OpeningBookRepository.open(self.path)
        reopened=self.repo.snapshot(self.bid)
        self.assertEqual(len(reopened.moves),7)
        out=Path(self.temp.name)/"branches.bin"
        export_polyglot(reopened,out)
        self.assertEqual(len(verify_polyglot(out,reopened)),7)

    def test_transposition_shared_outgoing_and_finite_cycle_browser(self):
        self.save("d4 Nf6 Nf3 d5")
        target=self.session.history[2]
        dest=next(m for m in self.session.snapshot.moves if m.move_id==target).to_position_id
        self.save("Nf3 Nf6 d4")
        self.assertEqual(self.session.position_id,dest)
        self.assertEqual([m.san for m in self.session.snapshot.branches(dest)],["d5"])
        self.assertTrue(any(e.reference for e in branch_browser(self.session.snapshot)))
        cycle=self.service.create_book(BookDetails("Cycle"))
        s=OpeningBookSession(self.service,cycle);add_line(s,"Nf3 Nf6 Ng1 Ng8")
        self.assertEqual(s.position_id,s.snapshot.book.root_position_id)
        entries=branch_browser(s.snapshot)
        self.assertEqual(len(entries),4);self.assertTrue(entries[-1].reference)
        self.assertEqual(len(export_entries(s.snapshot)),4)

    def test_preferred_unique_edit_in_place_and_disable(self):
        self.save("e4");self.save("d4")
        snapshot=self.repo.snapshot(self.bid);a,b=snapshot.moves
        self.service.edit_move(self.bid,a.move_id,MoveDetails(90,True))
        self.service.edit_move(self.bid,b.move_id,MoveDetails(80,True))
        snapshot=self.repo.snapshot(self.bid)
        self.assertEqual([m.move_id for m in snapshot.moves if m.preferred],[b.move_id])
        self.assertEqual([m.move_id for m in snapshot.moves],[a.move_id,b.move_id])
        self.service.edit_move(self.bid,b.move_id,MoveDetails(80,False,False))
        self.assertEqual(len(export_entries(self.repo.snapshot(self.bid))),1)

    def test_delete_preserves_shared_descendants_and_attached_source_scope(self):
        self.save("d4 Nf6 Nf3 d5")
        self.save("Nf3 Nf6 d4")
        snap=self.repo.snapshot(self.bid)
        root=snap.book.root_position_id
        d4=next(m for m in snap.branches(root) if m.san=="d4")
        source=self.repo.save_source(self.bid,root,d4.move_id,SourceDetails("Original","Owner","2026","Intro","1","Private original note"))
        pos_source=self.repo.save_source(self.bid,root,None,SourceDetails(title="General provenance"))
        self.repo.delete_branch(self.bid,d4.move_id)
        after=self.repo.snapshot(self.bid)
        self.assertEqual(len(after.positions),len(snap.positions))
        self.assertEqual([s.source_ref_id for s in after.sources],[pos_source])
        self.assertIn("d5",[m.san for m in after.moves if m.from_position_id in after.reachable()])
        self.assertNotIn(source,[s.source_ref_id for s in after.sources])

    def test_notes_sources_and_versioned_application_identity(self):
        snap=self.save("e4");edge=snap.moves[0];root=snap.book.root_position_id
        self.service.edit_move(self.bid,edge.move_id,MoveDetails(75,False,True,"Develop centrally.","Original exercise.",'{"tags":["study"]}'))
        rid=self.repo.save_source(self.bid,root,edge.move_id,SourceDetails(title="Owner notes"))
        before=self.repo.snapshot(self.bid)
        self.repo.save_source(self.bid,root,edge.move_id,SourceDetails(title="Owner notes",page="2"),rid)
        after=self.repo.snapshot(self.bid)
        self.assertNotEqual(before.identity,after.identity)
        self.assertEqual(after.sources[0].page,"2")
        self.assertEqual(after.moves[0].instructional_note,"Original exercise.")
        other=self.service.create_book(BookDetails("Other"))
        with self.assertRaises(ValueError):self.repo.save_source(other,root,edge.move_id,SourceDetails(title="Wrong"))
        self.repo.delete_source(self.bid,rid)
        self.assertEqual(self.repo.snapshot(self.bid).sources,())

    def test_disconnected_theory_retained_but_not_exported(self):
        snap=self.save("e4 e5 Nf3")
        first=snap.moves[0]
        self.service.edit_move(self.bid,first.move_id,MoveDetails(active=False))
        after=self.repo.snapshot(self.bid)
        self.assertEqual(len(after.moves),3)
        self.assertEqual(export_entries(after),())
        receipt=export_polyglot(after,Path(self.temp.name)/"empty.bin")
        self.assertEqual(receipt.entry_count,0)

    def test_foreign_database_rejected_read_only_and_exclusive_create(self):
        bad=Path(self.temp.name)/"game.db"
        with closing(sqlite3.connect(bad)) as db:db.execute("CREATE TABLE games(game_id INTEGER)")
        before=bad.read_bytes()
        with self.assertRaises(ValueError):OpeningBookRepository.open(bad)
        with self.assertRaises(ValueError):OpeningBookRepository.create(bad)
        self.assertEqual(bad.read_bytes(),before)
        original=self.path.read_bytes()
        with self.assertRaises(FileExistsError):OpeningBookRepository.create(self.path)
        self.assertEqual(self.path.read_bytes(),original)

    def test_proof_book_size_branches_reopen_export_and_no_engine(self):
        bid=author_proof_book(self.service)
        snap=self.repo.snapshot(bid)
        self.assertGreaterEqual(len(snap.moves),20);self.assertLessEqual(len(snap.moves),30)
        a=export_polyglot(snap,Path(self.temp.name)/"one.bin")
        b=export_polyglot(snap,Path(self.temp.name)/"two.bin")
        self.assertEqual(a.sha256,b.sha256)
        self.assertEqual(a.byte_count,16*len(snap.moves))
        self.assertEqual(a.entry_count,len(snap.moves))
        self.assertTrue(any(e.reference for e in branch_browser(snap)))


class PolyglotTests(LibraryFixture):
    def test_castling_and_all_promotions_roundtrip(self):
        for name,fen,line in (("Castling",CASTLE,("O-O","O-O-O")),
                             ("Promotion",PROMOTION,("a8=Q+","a8=R+","a8=B","a8=N"))):
            bid=self.service.create_book(BookDetails(name),fen)
            for notation in line:
                move=chess.Board(fen).parse_san(notation)
                self.service.save_move(bid,fen,move.uci(),MoveDetails(80))
            snap=self.repo.snapshot(bid);path=Path(self.temp.name)/(name+".bin")
            export_polyglot(snap,path)
            with chess.polyglot.open_reader(str(path)) as reader:
                self.assertEqual({e.move.uci() for e in reader.find_all(chess.Board(fen))},
                                 {chess.Board(fen).parse_san(n).uci() for n in line})
                if name=="Castling":
                    self.assertEqual({e.raw_move & 63 for e in reader},{chess.H1,chess.A1})

    def test_en_passant_roundtrip_and_no_overwrite(self):
        fen="4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"
        bid=self.service.create_book(BookDetails("EP"),fen)
        self.service.save_move(bid,fen,"e5d6",MoveDetails(100))
        snap=self.repo.snapshot(bid);path=Path(self.temp.name)/"ep.bin"
        export_polyglot(snap,path);before=path.read_bytes()
        with self.assertRaises(FileExistsError):export_polyglot(snap,path)
        self.assertEqual(path.read_bytes(),before)
        with chess.polyglot.open_reader(str(path)) as reader:
            self.assertEqual(reader.find(chess.Board(fen)).move.uci(),"e5d6")

    def test_corruption_and_hash_mismatch_rejected(self):
        snap=self.save("e4 e5")
        path=Path(self.temp.name)/"good.bin";export_polyglot(snap,path)
        path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(ValueError):verify_polyglot(path,snap)
        positions=tuple(replace(p,polyglot_key="0000000000000000") for p in snap.positions)
        with self.assertRaises(ValueError):export_entries(replace(snap,positions=positions))

    def test_failed_roundtrip_removes_only_new_output(self):
        snap=self.save("e4");path=Path(self.temp.name)/"failed.bin"
        with patch("opening_book_polyglot.verify_polyglot",side_effect=ValueError("bad")):
            with self.assertRaises(ValueError):export_polyglot(snap,path)
        self.assertFalse(path.exists())


class ApplicationTests(LibraryFixture):
    def setUp(self):
        super().setUp()
        self.proof=author_proof_book(self.service)
        self.snapshot=self.repo.snapshot(self.proof)

    def apply(self,line,user="white"):
        return apply_book(self.snapshot,ucis(line),user_color=user)

    def test_entirely_book_and_alternative(self):
        a=self.apply("e4 e5 Nf3 Nc6")
        self.assertEqual((a.in_book_move_count,a.known_position_count),(4,5))
        self.assertIsNone(a.first_deviation_ply)
        self.assertEqual(a.moves[0].preferred_move,"e2e4")
        self.assertEqual(a.moves[0].weight,100)
        b=self.apply("e4 c5 Nc3 Nc6")
        self.assertEqual(b.in_book_move_count,4);self.assertIsNone(b.first_deviation_ply)

    def test_user_and_opponent_deviation(self):
        for line,ply,side,relation in (("e4 e5 f4",3,"white","user"),("e4 d5",2,"black","opponent")):
            value=self.apply(line)
            self.assertEqual((value.first_deviation_ply,value.deviating_side,value.deviation_relation),(ply,side,relation))

    def test_transposition_reentry_after_unknown_positions(self):
        result=self.apply("d4 d5 Nf3 Nf6 c4")
        self.assertEqual(result.first_deviation_ply,2)
        self.assertEqual(result.moves[2].state,"position_not_in_book")
        self.assertTrue(result.moves[4].in_book)
        self.assertEqual(result.in_book_move_count,2)
        self.assertEqual(result.last_known_position_ply,5)

    def test_leaf_exhaustion_and_legal_nonbook_move(self):
        result=self.apply("e4 e5 Nf3 Nc6 Bb5 a6 Ba4")
        self.assertEqual(result.first_deviation_ply,7)
        self.assertEqual(result.moves[6].state,"continuation_not_authored")
        self.assertEqual(result.last_known_position_ply,6)
        other=self.apply("b3 e5")
        self.assertEqual(other.first_deviation_ply,1)
        self.assertEqual(other.moves[1].state,"position_not_in_book")
        # Hashes can contain "bad"; assert the factual state contract instead.
        self.assertEqual(tuple(row.state for row in other.moves),("move_not_authored","position_not_in_book"))

    def test_invalid_replay_and_uncovered_start(self):
        for move in ("e2e5","0000"):
            with self.assertRaises(ValueError):apply_book(self.snapshot,(move,))
        value=apply_book(self.snapshot,("a7a8q",),initial_fen=PROMOTION)
        self.assertEqual(value.known_position_count,0)
        self.assertIsNone(value.first_deviation_ply)

    def test_lookup_is_read_only_and_results_immutable(self):
        before=self.path.read_bytes()
        result=self.apply("e4 e5")
        self.assertEqual(self.path.read_bytes(),before)
        with self.assertRaises(FrozenInstanceError):result.book_version="other"


class StoredApplicationTests(TemporaryAnalysis):
    def test_stored_fixture_application_and_no_game_writes(self):
        self.import_fixture(pgn(moves="1. e4 e5 2. Nf3 Nc6 1-0"))
        repo=OpeningBookRepository.create(Path(self.temp.name)/"book.cwbook")
        try:
            bid=author_proof_book(OpeningBookService(repo));snap=repo.snapshot(bid)
            before=self.digest()
            with patch.object(chess.engine.SimpleEngine,"popen_uci",side_effect=AssertionError("No engine")):
                result=apply_stored_game(self.path,1,snap)
                with self.assertRaises(ValueError):apply_stored_game(self.path,999991,snap)
            self.assertEqual(result.in_book_move_count,4)
            self.assertEqual(self.digest(),before)
        finally:repo.close()


class StudioTests(TemporaryAnalysis):
    def test_manual_pending_save_back_sibling_reopen_and_editor(self):
        from merlin_ui.opening_book_studio import OpeningBookStudio
        root=tk.Tk();root.withdraw()
        studio=OpeningBookStudio(root,game_database_path=self.path)
        repo=OpeningBookRepository.create(Path(self.temp.name)/"studio.cwbook")
        bid=OpeningBookService(repo).create_book(BookDetails("UI proof"))
        studio.use_repository(repo);root.update()
        try:
            studio.stage_board_move(chess.Move.from_uci("e2e4"));root.update()
            self.assertEqual(len(repo.snapshot(bid).moves),0)
            self.assertIn("PENDING",studio.shell.status_var.get())
            studio.save_pending();root.update()
            self.assertEqual(len(repo.snapshot(bid).moves),1)
            studio.book_start();studio.stage("d4");studio.save_pending();root.update()
            studio.book_start()
            self.assertEqual(len(studio.navigation.branches()),2)
            edge=repo.snapshot(bid).moves[0]
            studio.activate_node(next(k for k,p in studio.paths.items() if p==(edge.move_id,)));root.update()
            studio.edit_move()
            studio.weight.set("80");studio.preferred.set(True)
            studio.update_selected();root.update()
            self.assertEqual(repo.snapshot(bid).moves[0].weight,80)
            self.assertTrue(repo.snapshot(bid).moves[0].preferred)
            studio.book_start();studio.stage("Nf3")
            with patch("merlin_ui.opening_studio_workflow.choose_action",return_value="cancel"):
                studio.book_start()
                self.assertEqual(studio.session.pending,"g1f3")
            studio.discard()
        finally:
            studio.dirty=False;studio.session.discard();studio.close()

    def test_cancel_book_switch_preserves_pending_preview_and_edits(self):
        from merlin_ui.opening_book_studio import OpeningBookStudio
        root=tk.Tk();root.withdraw()
        studio=OpeningBookStudio(root,game_database_path=self.path)
        repo=OpeningBookRepository.create(Path(self.temp.name)/"cancel.cwbook")
        service=OpeningBookService(repo)
        first=service.create_book(BookDetails("First"));service.create_book(BookDetails("Second"))
        studio.use_repository(repo)
        try:
            studio.stage("e4");studio.weight.set("75")
            preview=studio.board_widget.board.fen()
            studio.book_picker.current(1)
            with patch("merlin_ui.opening_studio_workflow.choose_action",return_value="cancel"):
                studio.select_book()
            self.assertEqual(studio.session.book_id,first)
            self.assertEqual(studio.session.pending,"e2e4")
            self.assertEqual(studio.weight.get(),"75")
            self.assertEqual(studio.board_widget.board.fen(),preview)
            self.assertEqual(studio.book_picker.current(),0)
        finally:
            studio.discard();studio.close()

    def test_core_portability_and_no_engine_dependency(self):
        import ast
        for path in Path(".").glob("opening_book_*.py"):
            tree=ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom):
                    self.assertFalse((node.module or "").startswith(("tkinter","merlin_ui","chess.engine")))
                if isinstance(node,ast.Import):
                    self.assertFalse(any(n.name.startswith(("tkinter","merlin_ui","chess.engine")) for n in node.names))

