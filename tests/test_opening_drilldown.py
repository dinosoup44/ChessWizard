"""Opening Review drill-down acceptance using isolated nine-game authoring fixtures."""
from tests.opening_ui_wait import wait_for_opening
from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from tkinter import ttk
import chess
from opening_book_models import MoveDetails
from opening_book_session import OpeningBookSession
from opening_workspace import opening_moments
from opening_review_navigation import affected_games, OpeningOccurrence
from merlin_ui.information_panel import style_information_tree
from tests.test_opening_workspace import OpeningWorkspaceFixture
from tests.opening_book_fixtures import add_line
from tests.opening_intelligence_fixtures import pgn


class OpeningDrilldownTests(OpeningWorkspaceFixture):
    def snapshot(self):
        return (self.view.current_game['game_id'], self.view.current_step,
                self.view.board_widget.board.fen(), self.view.evaluation_values,
                self.view.board_identity['text'], self.view.actual_moves.get('1.0','end'),
                tuple(self.view.actual_moves.tag_ranges('current')))

    def test_nine_bd7_games_exact_1066_then_1671_only_moments_navigate(self):
        session=OpeningBookSession(self.author,self.bid)
        add_line(session,'e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3 Qb6')
        self.author.edit_move(self.bid,session.history[-1],MoveDetails(preferred=True))
        with closing(self.connect()) as db:
            db.execute("UPDATE sqlite_sequence SET seq=1065 WHERE name='games'");db.commit()
        for i in range(8):
            self.import_fixture(pgn('e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3 Bd7','bd7-'+str(i)))
        with closing(self.connect()) as db:
            db.execute("UPDATE sqlite_sequence SET seq=1670 WHERE name='games'");db.commit()
        self.import_fixture(pgn('e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3 Bd7','bd7-last'))
        with closing(self.connect()) as db:
            db.execute("UPDATE games SET user_color='black' WHERE game_id>=1066")
            db.execute("UPDATE games SET white_username='Opponent1066' WHERE game_id=1066")
            db.execute("UPDATE games SET white_username='Opponent1671' WHERE game_id=1671");db.commit()
        self.picker.refresh(force=True);wait_for_opening(self.view)
        before_db=self.digest();before_book=self.repo.path.read_bytes()
        self.analyze();self.space.tabs.select(self.space.deviations.master);self.root.update()
        original=self.snapshot()
        key=next(k for k in self.space.deviations.get_children() if 'Bd7' in self.space.deviations.set(k,'move'))
        self.assertIn('Qb6',self.space.deviations.set(key,'opening'))
        self.space.deviations.selection_set(key);self.root.update()
        self.assertEqual(self.snapshot(),original)
        self.assertEqual(len(self.space.affected.tree.get_children()),9)
        selected_opening=self.picker.selected_id
        previous=original
        event_keys=[]
        for gid in (1066,1671):
            self.space.affected.tree.selection_set(str(gid));self.root.update()
            self.assertEqual(self.snapshot(),previous)
            self.assertIn(f'Selected game: {gid}',self.space.selected_game_label['text'])
            self.assertEqual(len(self.panel.moments),1)
            moment=self.panel.moments[0];event_keys.append(moment.key)
            self.assertEqual((moment.book.game_id,moment.book.ply,moment.book.played_san),(gid,10,'Bd7'))
            self.assertEqual(moment.book.provenance,self.space.result.matching_set.provenance)
            self.assertFalse(self.panel.studio_button.instate(['disabled']))
            self.panel.events.selection_set(moment.key);self.root.update();wait_for_opening(self.view)
            self.assertEqual((self.view.current_game['game_id'],self.view.current_step),(gid,9))
            self.assertEqual(self.view.opening_anchor_ply,10)
            self.assertEqual(self.view.board_widget.board.fen(),self.view.moves[9]['fen_before'])
            self.assertTrue(all(v.position.game_id==gid for v in self.view.evaluation_values))
            self.assertEqual(self.view.eval_timeline.values,self.view.evaluation_values)
            self.assertTrue(self.view.actual_moves.tag_ranges('current'))
            self.assertIn('Bd7',self.view.actual_moves.get(*self.view.actual_moves.tag_ranges('current')))
            self.assertIn(f'Game {gid} · vs Opponent{gid} · 5...Bd7',self.view.board_identity['text'])
            self.assertEqual(self.picker.selected_id,selected_opening)
            self.assertEqual(self.space.tabs.select(),str(self.space.deviations.master))
            self.assertEqual(self.view.workspace_tabs.select(),str(self.space))
            self.assertFalse(self.panel.studio_button.instate(['disabled']))
            self.view.next_move();self.view.open_opening_context()
            handoff=self.view.opening_book_studio.staged_review.handoff
            self.assertEqual(handoff.source_game_id,gid)
            self.assertEqual(handoff.source_ply,10)
            self.assertEqual(handoff.candidate_moves,('c8d7',))
            self.view.opening_book_studio.staged_review.cancel()
            previous=self.snapshot()
        self.assertNotEqual(*event_keys)
        self.assertEqual(before_db,self.digest());self.assertEqual(before_book,self.repo.path.read_bytes())

    def test_gap_combines_tags_and_repeated_plies_keep_distinct_identity(self):
        result=self.analyze();game=next(g for g in result.games if g.context.game_id==2)
        moments=opening_moments(game.book,game,result)
        gap=[m for m in moments if m.book.ply==5]
        self.assertEqual(len(gap),1)
        self.assertEqual(gap[0].kind,'Opponent left opening · Opening gap')
        self.assertEqual(gap[0].tags,('Opponent left opening','Opening gap'))
        repeated=replace(gap[0].book,ply=9,move_id=9999)
        book=replace(game.book,moves=(*game.book.moves,repeated))
        events=opening_moments(book,game,result)
        matching=[m for m in events if 'Opening gap' in m.tags]
        self.assertEqual([m.book.ply for m in matching],[5,9])
        self.assertEqual(len({m.key for m in matching}),2)
        selected=affected_games((OpeningOccurrence(game,gap[0].book),OpeningOccurrence(game,repeated)))
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0].plies,(5,9))
        self.assertIsNotNone(gap[0].quality)

    def test_background_refresh_does_not_navigate_or_mix_quality(self):
        self.analyze();self.panel.select_moment(6)
        before=self.snapshot()
        self.space.games_grid.selection_set('2');self.root.update()
        self.assertEqual(self.panel.accuracy,next(g for g in self.space.result.games if g.context.game_id==2).accuracy)
        self.picker._refresh_all();wait_for_opening(self.view);self.pump(lambda:not self.space.busy)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.panel.assessment.game_id,2)
        self.assertFalse(self.panel.studio_button.instate(['disabled']))
        self.view.refresh_all();self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.panel.assessment.game_id,2)

    def test_summary_change_clears_old_moments_without_moving_display(self):
        self.analyze();self.space.tabs.select(self.space.deviations.master);self.root.update()
        keys=self.space.deviations.get_children()
        self.space.deviations.selection_set(keys[0]);self.root.update()
        gid=self.space.affected.tree.get_children()[0]
        self.space.affected.tree.selection_set(gid);self.root.update()
        self.panel.select_moment(self.panel.moments[0].book.ply)
        wait_for_opening(self.view)
        before=self.snapshot()
        self.space.deviations.selection_set(keys[1]);self.root.update()
        self.assertEqual(self.panel.events.get_children(),())
        self.assertIsNone(self.panel.assessment)
        self.assertEqual(self.snapshot(),before)
        self.assertFalse(self.panel.studio_button.instate(['disabled']))

    def test_pane_minimums_drag_and_settle_at_common_dpi(self):
        self.analyze();self.root.deiconify();self.root.geometry('1280x1100')
        for scale in (1,1.25,1.5):
            self.root.tk.call('tk','scaling',scale*96/72)
            for tree in (self.space.deviations,self.space.gaps,self.space.variations):
                style_information_tree(tree);style_information_tree(self.space.affected.tree)
                self.space.tabs.select(tree.master);self.root.update()
                tree.selection_set(tree.get_children()[0]);self.root.update()
                split=self.space.summary_splitter
                self.pump(lambda: self.space.affected.tree.winfo_height()>50)
                rowheight=int(ttk.Style(self.root).lookup('MerlinInformation.Treeview','rowheight'))
                for grid in (tree,self.space.affected.tree):
                    self.assertGreaterEqual(grid.winfo_height(),4*rowheight)
                usable=split.winfo_height()-split.sash_size
                self.assertLess(abs(split.sash_coord(0)[1]/usable-.5),.09)
                x,y=split.sash_coord(0)
                split._start_drag(SimpleNamespace(x=x+4,y=y+1))
                self.assertTrue(split._dragging)
                split._move_drag(SimpleNamespace(y=y+25))
                split.sash_place(0,0,y+25)
                split._finish_drag(SimpleNamespace())
                self.root.update()
                self.assertGreater(split.fraction,.5)
                final=split.sash_coord(0)
                for _ in range(5):self.root.update();self.assertEqual(split.sash_coord(0),final)
                self.assertFalse(self.space._automatic_size_guard.blocked)
                split.fraction=.5;split._schedule_layout();self.root.update()
        self.assertFalse(self.view.position_info.frame.winfo_manager())
        self.view.position_toggle.invoke();self.root.update()
        self.assertTrue(self.view.position_info.frame.winfo_manager())
        self.view.position_toggle.invoke();self.root.update()
        self.assertFalse(self.view.position_info.frame.winfo_manager())

    def test_multiple_authored_choices_use_small_moment_menu(self):
        self.analyze();self.panel.select_moment(5)
        row=self.panel.assessment.moves[4]
        # Suppress only the fixture preference to exercise the menu presentation.
        assessment=replace(self.panel.assessment,moves=tuple(replace(m,preferred_move=None) if m.ply==5 else m for m in self.panel.assessment.moves))
        self.panel.assessment=assessment
        with patch.object(self.panel.line_choices,'tk_popup') as popup:
            self.panel.show_line();popup.assert_called_once()
        self.assertEqual(self.panel.line_choices.index('end')+1,len(row.available_moves))
        self.panel.line_choices.invoke(0)
        self.assertEqual(self.view.opening_exploration.line[0].move_id,row.available_moves[0].move_id)
        self.assertEqual(self.view.current_step,4)

    def test_no_games_clears_displayed_game_banner(self):
        self.assertIn('Game 1',self.view.board_identity['text'])
        with patch.object(self.view.repository,'games',return_value=[]):
            self.view.load_games()
        self.assertEqual(self.view.board_identity['text'],'No game loaded')
        self.assertIsNone(self.view.current_game)
