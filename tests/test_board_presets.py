"""Color-only palette contracts; all files and settings belong to temporary fixtures."""
from collections import Counter
from dataclasses import replace
import json
import tkinter as tk
import chess
from application_settings import ApplicationSettings
from theme_core.active import ActiveThemeService, DEFAULT_THEME
from theme_core.models import BoardColors
from theme_core.presets import BOARD_PRESETS, board_preset
from merlin_ui.theme_editor import ThemeEditor
from merlin_ui.view_shell import MerlinViewShell
from tests.test_theme_editor import ThemeFixture


def contrast(a, b):
    def luminance(color):
        values = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
        values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
        return sum(v * w for v, w in zip(values, (.2126, .7152, .0722)))
    l1, l2 = sorted((luminance(a), luminance(b)))
    return (l2 + .05) / (l1 + .05)


class BoardPresetTests(ThemeFixture):
    def test_catalog_default_and_square_contrast(self):
        self.assertEqual(Counter(p.group for p in BOARD_PRESETS), {'base':30, 'alternate':8, 'default':1})
        self.assertEqual(len({p.preset_id for p in BOARD_PRESETS}),39)
        self.assertEqual(len({p.name for p in BOARD_PRESETS}),39)
        self.assertEqual(board_preset('default').apply(BoardColors()),BoardColors())
        for preset in BOARD_PRESETS:
            with self.subTest(preset=preset.name):
                colors=preset.apply(BoardColors(frame='#123456',coordinate='#654321'))
                self.assertEqual((colors.frame,colors.coordinate),('#123456','#654321'))
                self.assertGreaterEqual(contrast(colors.light_square,colors.dark_square),2.8)
        with self.assertRaises(ValueError):board_preset('missing')

    def test_backward_compatible_load_no_write_and_no_analysis_identity(self):
        self.settings.path.write_text(json.dumps({'active_theme_id':'default','show_last_move':False,'review_moves_fraction':.6}))
        before=self.settings.path.read_bytes()
        service=ActiveThemeService(self.repo,self.settings)
        self.assertEqual(service.current.loaded,DEFAULT_THEME)
        self.assertEqual(service.current.board_preset_id,'custom')
        self.assertEqual(before,self.settings.path.read_bytes())
        for item in ApplicationSettings().schema():
            if item.setting_id.startswith('board_'):
                self.assertFalse(item.affects_result_currentness)
                self.assertFalse(item.affects_raw_cache_identity)

    def test_switch_restart_restore_custom_preserves_artwork_and_theme_bytes(self):
        saved=self.draft().save(self.repo)
        self.service.activate(saved.theme.theme_id)
        files={p:p.read_bytes() for p in self.repo.root.rglob('*') if p.is_file()}
        self.service.set_custom_board_colors('#eccdaa','#456789')
        for preset in BOARD_PRESETS:
            actual=self.service.activate_board_preset(preset.preset_id)
            expected=preset.apply(saved.theme.colors)
            self.assertEqual(actual.loaded.theme.colors,expected)
            self.assertEqual(actual.loaded.pieces,saved.pieces)
            self.assertEqual(actual.loaded.decorations,saved.decorations)
            restarted=ActiveThemeService(self.repo,self.settings)
            self.assertEqual(actual,restarted.current)
        self.service.activate_board_preset('custom')
        self.assertEqual(self.service.current.loaded.theme.colors.light_square,'#eccdaa')
        self.assertEqual(self.service.current.loaded.theme.colors.dark_square,'#456789')
        self.assertEqual(files,{p:p.read_bytes() for p in self.repo.root.rglob('*') if p.is_file()})
        self.service.activate(saved.theme.theme_id)
        self.assertEqual(self.service.current.loaded,saved)

    def test_idempotency_invalid_requests_and_paired_colors(self):
        self.service.activate_board_preset('lightning')
        before=self.settings.path.read_bytes();stamp=self.settings.path.stat().st_mtime_ns
        self.service.activate_board_preset('lightning')
        self.assertEqual(stamp,self.settings.path.stat().st_mtime_ns)
        for action in (lambda:self.service.activate_board_preset('unknown'),
                       lambda:self.service.set_custom_board_colors('blue','#334455'),
                       lambda:ApplicationSettings(board_custom_light='#334455')):
            with self.assertRaises(ValueError):action()
        self.assertEqual(before,self.settings.path.read_bytes())


class BoardPresetWidgetTests(ThemeFixture):
    def setUp(self):
        super().setUp()
        self.root=tk.Tk();self.root.withdraw();self.addCleanup(self.root.destroy)
        self.view=ThemeEditor(self.root,self.service)
        self.other=tk.Toplevel(self.root);self.other.withdraw()
        self.shell=MerlinViewShell(self.other,theme_service=self.service)

    def test_immediate_apply_manual_custom_restart_and_explicit_saved_theme(self):
        view=self.view
        self.assertEqual(len(view.board_selector['values']),40)
        view.board_choice.set('Lightning');self.assertTrue(view.select_board_preset())
        for board in (view.board_widget,self.shell.board_widget):
            self.assertEqual(board.board_style['light_square'],board_preset('lightning').light_square)
            self.assertEqual(board.board_style['dark_square'],board_preset('lightning').dark_square)
        view.color_vars['light_square'].set('#efdbb7');self.assertTrue(view.apply_colors())
        self.assertEqual(view.board_choice.get(),'Custom')
        self.assertEqual(self.shell.board_widget.board_style['light_square'],'#efdbb7')
        view.board_choice.set('Showtime');view.select_board_preset()
        view.board_choice.set('Custom');view.select_board_preset()
        self.assertEqual(view.draft.colors.light_square,'#efdbb7')
        fresh=tk.Toplevel(self.root);fresh.withdraw()
        restarted=ThemeEditor(fresh,ActiveThemeService(self.repo,self.settings))
        self.assertEqual(restarted.draft.colors,view.draft.colors)
        self.assertEqual(restarted.board_choice.get(),'Custom');fresh.destroy()
        view.board_choice.set('ChessWizard Default');view.select_board_preset()
        self.assertEqual(view.draft.colors,BoardColors())
        self.assertEqual(self.shell.board_widget.theme_images.loaded,DEFAULT_THEME)

    def test_all_presets_keep_board_position_overlays_and_ui_style(self):
        board=self.shell.board_widget
        board.set_position(chess.Board());board.selected_square=chess.E2
        board.legal_moves=[chess.Move.from_uci('e2e3'),chess.Move.from_uci('e2e4')]
        board.set_last_move(chess.Move.from_uci('g8f6'));board.set_arrows([{'from':chess.G1,'to':chess.F3}])
        state=(board.board.fen(),board.selected_square,board.last_move,tuple(board.legal_moves))
        style={k:v for k,v in board.board_style.items() if k not in ('light_square','dark_square')}
        for preset in BOARD_PRESETS:
            self.service.activate_board_preset(preset.preset_id)
            board._layout(650,650);board.redraw()
            self.assertEqual(state,(board.board.fen(),board.selected_square,board.last_move,tuple(board.legal_moves)))
            self.assertEqual(style,{k:v for k,v in board.board_style.items() if k not in ('light_square','dark_square')})
            self.assertTrue(board.find_withtag('selected_square'))
            self.assertTrue(board.find_withtag('last_move'))
            self.assertEqual(len(board.arrows),1)
            self.assertEqual(len(board.find_withtag('piece_contrast_edge')),128)
            self.assertEqual(len(board.find_withtag('legal_move_indicator')),2)
            self.assertTrue(board.find_withtag('overlay_contrast_edge'))
            for marker in board.find_withtag('legal_move_indicator'):
                self.assertGreater(contrast(board.itemcget(marker,'fill'),board.itemcget(marker,'outline')),4)

    def test_palette_layout_at_three_tk_scales_and_restart(self):
        view=self.view
        original_scale=self.root.tk.call('tk','scaling')
        self.addCleanup(lambda:self.root.tk.call('tk','scaling',original_scale))
        for percent in (100,125,150):
            self.root.tk.call('tk','scaling',percent/100*96/72)
            self.root.deiconify();self.root.geometry('1360x860+20000+20000');self.root.update()
            self.assertGreaterEqual(view.board_selector.winfo_width(),200)
            self.assertLess(view.board_selector.winfo_rootx()+view.board_selector.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())
            view.board_choice.set('Vice Nights');view.select_board_preset()
            self.assertEqual(view.board_choice.get(),'Vice Nights')
        fresh=tk.Toplevel(self.root);fresh.withdraw()
        restarted=ThemeEditor(fresh,ActiveThemeService(self.repo,self.settings))
        self.assertEqual(restarted.board_choice.get(),'Vice Nights')
        self.assertEqual(restarted.draft.colors,view.draft.colors)
        fresh.destroy()

    def test_using_saved_theme_clears_preset_and_refreshes_editor(self):
        view=self.view
        view.board_choice.set('Lightning');view.select_board_preset()
        self.assertTrue(view.activate_selected())
        self.assertEqual(view.board_choice.get(),'Custom')
        self.assertEqual(view.draft.colors,BoardColors())
        self.assertEqual(view.draft.colors,self.service.current.loaded.theme.colors)

    def test_fallback_piece_bounds_do_not_grow_with_tk_scale(self):
        board=self.shell.board_widget
        original=self.root.tk.call('tk','scaling')
        self.addCleanup(lambda:self.root.tk.call('tk','scaling',original))
        bounds=[]
        for scale in (96/72,120/72,144/72):
            self.root.tk.call('tk','scaling',scale)
            board._layout(640,640);board.redraw()
            glyphs=[i for i in board.find_all() if board.type(i)=='text'
                and board.itemcget(i,'font').startswith('{Segoe UI Symbol}')]
            bounds.append([board.bbox(i) for i in glyphs])
            self.assertEqual(len(glyphs),160)
        self.assertEqual(bounds[0],bounds[1])
        self.assertEqual(bounds[1],bounds[2])
