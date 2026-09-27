"""Branch-centered navigation and authoring context regressions, isolated from user data."""
from dataclasses import replace
from pathlib import Path
import json
import tkinter as tk
from tkinter import ttk
from unittest.mock import patch
import chess
import chess.engine
from opening_book_models import BookDetails, MoveDetails, SourceDetails
from opening_book_navigation import BranchNavigation, branch_paths
from opening_book_session import OpeningBookSession
from opening_book_service import OpeningBookService
from opening_book_repository import OpeningBookRepository
from tests.test_opening_book import LibraryFixture
from tests.test_game_analysis import TemporaryAnalysis
from tests.opening_book_fixtures import add_line


def french(service):
    bid=service.create_book(BookDetails("The French"))
    session=OpeningBookSession(service,bid)
    for line,name in (("e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3","Advance Variation"),
                      ("e4 e6 d4 d5 exd5 exd5 Nf3","Exchange Variation"),
                      ("e4 e6 d4 d5 Nd2 c5","Tarrasch Variation")):
        add_line(session,line)
        service.edit_move(bid,session.history[4],MoveDetails(variation_name=name))
        session.refresh()
    return bid


class BranchNavigationTests(LibraryFixture):
    def setup_french(self):
        self.bid=french(self.service)
        self.session=OpeningBookSession(self.service,self.bid)
        self.nav=BranchNavigation(self.session)
        return {b.label:b for b in self.nav.branches()}

    def test_exact_owner_sequence_bounds_and_no_writes(self):
        lines=self.setup_french();before=self.path.read_bytes()
        advance=lines['Advance Variation'];self.nav.activate(advance)
        self.assertEqual(self.session.board.peek().uci(),'e4e5')
        self.nav.step(1);self.assertEqual(self.session.board.peek().uci(),'c7c5')
        self.nav.step(1);self.assertEqual(self.session.board.peek().uci(),'c2c3')
        self.nav.step(-1);self.assertEqual(self.session.board.peek().uci(),'c7c5')
        self.nav.activate(advance,4);self.assertEqual(self.session.board.peek().uci(),'g1f3')
        last=self.session.board.fen();self.nav.step(1);self.assertEqual(last,self.session.board.fen())
        for _ in range(10):self.nav.step(-1)
        self.assertEqual(self.nav.index,0);self.assertEqual(self.session.board.peek().uci(),'e4e5')
        self.assertEqual(self.nav.active.anchor,advance.anchor)
        self.nav.activate(lines['Exchange Variation']);self.nav.step(1)
        self.assertEqual(self.session.board.peek().uci(),'e6d5')
        self.assertEqual(self.nav.active.label,'Exchange Variation')
        self.assertIn('move 2 of 3',self.nav.status())
        self.assertEqual(before,self.path.read_bytes())

    def test_trunk_root_named_boundary_and_choices(self):
        lines=self.setup_french();trunk=lines['Opening trunk']
        self.assertEqual(len(trunk.steps),4)
        self.nav.activate(trunk,2);self.assertEqual(self.session.board.peek().uci(),'d2d4')
        self.nav.activate(trunk,3);self.nav.step(1);self.assertEqual(self.nav.index,3)
        self.nav.root();self.assertIsNone(self.nav.active);self.assertEqual(self.session.cursor,0)
        add_line(self.session,'e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3 Qb6')
        self.service.edit_move(self.bid,self.session.history[-1],MoveDetails(variation_name='Queen pressure'))
        self.session.refresh()
        branches={b.label:b for b in branch_paths(self.session.snapshot)}
        self.assertEqual(len(branches['Advance Variation'].steps),5)
        self.assertEqual(branches['Queen pressure'].parent_path,branches['Advance Variation'].steps[-1].path)

    def test_transposition_retains_incoming_path_and_shared_choices_are_clickable(self):
        self.save('d4 Nf6 Nf3 d5 c4');self.save('d4 Nf6 Nf3 d5 e3');self.save('Nf3 Nf6 d4')
        nav=BranchNavigation(self.session)
        branches=nav.branches()
        second=next(b for b in branches if self.session.snapshot.moves[b.anchor[0]-1].san=='Nf3')
        nav.activate(second)
        for _ in range(10):nav.step(1)
        self.assertEqual(len(nav.active.steps),4)
        self.assertEqual(self.session.history[:3],second.steps[2].path)
        self.assertTrue(any(s.shared for s in second.steps))
        choices=[b for b in nav.branches() if b.parent_path==second.steps[-1].path]
        self.assertEqual({b.steps[0].label for b in choices},{'3. c4','3. e3'})
        nav.activate(choices[0]);self.assertIn(nav.active.anchor,{b.anchor for b in nav.branches()})
        self.assertEqual(self.session.history[:4],second.steps[-1].path)

    def test_cycles_stop_and_pending_move_blocks_stepping(self):
        snap=self.save('Nf3 Nf6 Ng1 Ng8');nav=BranchNavigation(self.session)
        line=nav.branches()[0];self.assertTrue(line.closes_cycle)
        nav.activate(line,3);nav.step(1);self.assertEqual(nav.index,3)
        self.assertEqual(len(nav.branches()),1)
        nav.activate(line,0);self.session.stage_notation('d5')
        with self.assertRaises(ValueError):nav.step(1)
        self.assertEqual(nav.index,0)


class BranchStudioTests(TemporaryAnalysis):
    def setUp(self):
        super().setUp()
        from merlin_ui.opening_book_studio import OpeningBookStudio
        self.root=tk.Tk();self.root.withdraw()
        self.studio=OpeningBookStudio(self.root,game_database_path=self.path)
        self.library=Path(self.temp.name)/'branches.cwbook'
        repo=OpeningBookRepository.create(self.library)
        self.bid=french(OpeningBookService(repo));self.studio.use_repository(repo)
        self.root.update()
        self.addCleanup(self.cleanup_studio)
        guard=patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=AssertionError('No engine'))
        guard.start();self.addCleanup(guard.stop)

    def cleanup_studio(self):
        self.studio.discard();self.studio.close()

    def node(self,name,index=None):
        return next(k for k,(b,i) in self.studio.branch_nodes.items()
                    if b.label==name and (k.startswith('b') if index is None else k.startswith('m') and i==index))

    def test_direct_click_steps_highlight_and_removed_controls(self):
        s=self.studio;before=self.library.read_bytes()
        s.activate_node(self.node('Advance Variation'));s.step_branch(1);s.step_branch(1)
        self.assertEqual(s.selected_move,s.session.history[-1])
        active=next(k for k,(b,i) in s.branch_nodes.items() if k.startswith('b') and b.label=='Advance Variation')
        self.assertIn('active_branch',s.tree.item(active,'tags'))
        self.assertIn('move 3 of 5',s.position_label.cget('text'))
        s.activate_node(self.node('Advance Variation',4));s.step_branch(1)
        self.assertEqual(s.navigation.index,4)
        self.assertEqual([s.tabs.tab(t,'text') for t in s.tabs.tabs()],['Branch Browser','Stockfish Lines','How To'])
        self.assertFalse(hasattr(s,'branches'));self.assertFalse(hasattr(s,'follow_selected'))
        self.assertNotIn('metadata_json',s.fields)
        self.assertEqual(before,self.library.read_bytes())

    def test_edit_cancel_save_pending_and_safe_metadata(self):
        s=self.studio;s.activate_node(self.node('Advance Variation'))
        before=self.library.read_bytes();move_id=s.selected_move
        self.assertEqual(s.editor.winfo_manager(),'')
        self.assertIn('VIEWING',s.editor.cget('text'));self.assertEqual(s.fields['move_note'].cget('state'),'disabled')
        s.edit_move();self.assertEqual(s.editor.winfo_manager(),'grid');self.assertEqual(s.save_button.cget('text'),'Save Changes')
        s.fields['move_note'].insert('1.0','Unsaved');self.root.update()
        s.discard();self.assertEqual(before,self.library.read_bytes())
        s.edit_move();s.fields['move_note'].insert('1.0','Original note');s.save_editor()
        self.assertEqual(s.selected_move,move_id);self.assertEqual(s.current_move().move_note,'Original note')
        s.edit_move();current=s.metadata_json
        with patch('merlin_ui.opening_book_studio.edit_fields',return_value={'metadata_json':'{bad'}),patch('merlin_ui.opening_book_studio.messagebox.showerror') as error:
            snapshot=self.library.read_bytes();s.advanced_metadata();self.assertTrue(error.called)
            self.assertEqual(s.metadata_json,current);self.assertEqual(snapshot,self.library.read_bytes())
        payload={'extension':'__import__("os").system("never run")','tags':['original']}
        with patch('merlin_ui.opening_book_studio.edit_fields',return_value={'metadata_json':json.dumps(payload)}):s.advanced_metadata()
        s.save_editor();self.assertEqual(json.loads(s.current_move().metadata_json),payload)
        s.stage('a6');self.assertEqual(s.save_button.cget('text'),'Save Move');self.assertEqual(s.cancel_button.cget('text'),'Cancel Move')
        count=len(s.session.snapshot.moves);s.save_editor();self.assertEqual(len(s.session.snapshot.moves),count+1)
        self.assertIn('VIEWING',s.editor.cget('text'))

    def test_move_source_uses_starting_position_and_position_note_keeps_metadata(self):
        s=self.studio;s.activate_node(self.node('Advance Variation'))
        move=s.current_move()
        with patch('merlin_ui.opening_book_studio.SourceReferenceDialog') as dialog,patch.object(self.root,'wait_window'):
            s.sources(True)
            self.assertEqual(dialog.call_args.args[3:5],(move.from_position_id,move.move_id))
        s.repository.set_position_note(s.session.book_id,s.session.position_id,'before','{"retain":true}')
        s.session.refresh()
        with patch('merlin_ui.opening_book_studio.edit_fields',return_value={'position_note':'after'}):s.position_note()
        pos=s.session.snapshot.position(s.session.position_id)
        self.assertEqual(pos.metadata_json,'{"retain":true}');self.assertEqual(pos.position_note,'after')

    def test_delete_selected_branch_and_cancel_pending_navigation(self):
        s=self.studio;s.activate_node(self.node('Advance Variation'))
        parent=s.session.history[:s.session.cursor-1]
        plan=s.service.preview_deletion(s.session.book_id,s.selected_move,subtree=True)
        with patch('merlin_ui.opening_book_studio.choose_deletion',return_value=plan):s.delete_branch()
        self.assertEqual(s.session.history,parent)
        self.assertIn('Exchange Variation',{b.label for b in s.navigation.branches()})
        s.stage('e5');s.fields['move_note'].insert('1.0','pending');self.root.update()
        preview=s.board_widget.board.fen()
        with patch('merlin_ui.opening_studio_workflow.choose_action',return_value='cancel'):s.activate_node(self.node('Exchange Variation'))
        self.assertEqual(s.board_widget.board.fen(),preview);self.assertEqual(s.session.pending,'e4e5')

    def test_mouse_click_and_arrows_hidden_on_how_to(self):
        s=self.studio;self.root.deiconify();self.root.update()
        key=self.node('Advance Variation',2);s.tree.see(key);self.root.update()
        s.tree.yview_scroll(2,'units');self.root.update()
        x,y,w,h=s.tree.bbox(key)
        for event in ('<ButtonPress-1>','<ButtonRelease-1>'):s.tree.event_generate(event,x=x+100,y=min(y+h//2,s.tree.winfo_height()-4),time=10000)
        self.root.update();self.assertEqual(s.navigation.index,2)
        path=s.session.history
        for event in ('<ButtonPress-1>','<ButtonRelease-1>'):s.tree.event_generate(event,x=x+100,y=min(y+h//2,s.tree.winfo_height()-4),time=10100)
        self.root.update();self.assertEqual(s.session.history,path)
        self.assertTrue(s.step_controls.winfo_ismapped())
        s.tabs.select(1);self.root.update();self.assertFalse(s.step_controls.winfo_ismapped())
        s.tabs.select(0);self.root.update();self.assertTrue(s.step_controls.winfo_ismapped())
