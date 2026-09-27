"""Relationship classification never proves a tactic or turns analysis into history."""
import builtins
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tactic_occurrences import OccurrenceKind, TacticColor, TacticOccurrence, TacticOccurrenceRelation
from tactic_occurrence_adapters import occurrence_from_legacy_candidate
from tactical_opportunities import TacticalOpportunity, TacticalMotif, opportunity_to_dict

FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def event(kind=OccurrenceKind.PLAYED, **changes):
    values = dict(motif_type="fork", source_identity="fixture:claim", kind=kind,
                  actor_color=TacticColor.WHITE, perspective_color=TacticColor.WHITE,
                  source_position=FEN, actual_move="e2e4",
                  tactical_move="e2e4" if kind == OccurrenceKind.PLAYED else "d2d4",
                  actual_game_line=("e2e4", "e7e5"),
                  counterfactual_line=None if kind == OccurrenceKind.PLAYED else ("d2d4", "d7d5"),
                  source_verdict="supplied_fixture_claim")
    return TacticOccurrence(**(values | changes))


def legacy_row():
    # These are structural fixtures, not claims that opening pawn moves are forks.
    return dict(candidate_id=42, move_id=7, game_id=3, tactic_type="missed_fork",
                candidate_status="candidate", detector_version=3, fen_before=FEN,
                color="white", uci_played="e2e4", solution_move_uci="d2d4",
                solution_line="1. d4 d5", metadata_json='{"untouched": true}')


class TacticOccurrenceTests(unittest.TestCase):
    def test_all_four_relations_and_explicit_perspective(self):
        for kind, own, opponent in (
            (OccurrenceKind.PLAYED, TacticOccurrenceRelation.PLAYED_BY_PERSPECTIVE, TacticOccurrenceRelation.PLAYED_BY_OPPONENT),
            (OccurrenceKind.MISSED, TacticOccurrenceRelation.MISSED_BY_PERSPECTIVE, TacticOccurrenceRelation.MISSED_BY_OPPONENT),
        ):
            original = event(kind)
            self.assertEqual(original.relation, own)
            reversed_view = replace(original, perspective_color=TacticColor.BLACK)
            self.assertEqual(reversed_view.relation, opponent)
            self.assertEqual(reversed_view.source_identity, original.source_identity)
            self.assertEqual(reversed_view.actual_game_line, original.actual_game_line)
            self.assertEqual(reversed_view.actor_color, TacticColor.WHITE)

    def test_unknown_does_not_guess_kind_or_perspective(self):
        self.assertEqual(TacticOccurrence("fork", "unclassified:1").relation, TacticOccurrenceRelation.UNKNOWN)
        self.assertIsNone(TacticOccurrence("fork", "unclassified:1").actual_move_matches_tactical_move)
        self.assertEqual(event(perspective_color=None).relation, TacticOccurrenceRelation.UNKNOWN)
        self.assertEqual(event(OccurrenceKind.UNKNOWN).relation, TacticOccurrenceRelation.UNKNOWN)
        self.assertEqual(event(perspective_color=None).kind, OccurrenceKind.PLAYED)

    def test_move_equality_and_line_roots_are_contracts(self):
        self.assertTrue(event().actual_move_matches_tactical_move)
        self.assertFalse(event(OccurrenceKind.MISSED).actual_move_matches_tactical_move)
        for changes in ({"tactical_move": "d2d4"}, {"actual_game_line": None},
                        {"actor_color": None}, {"source_position": None},
                        {"actual_game_line": ("d2d4",)}, {"actual_game_line": ()}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                event(**changes)
        for changes in ({"tactical_move": "e2e4"}, {"counterfactual_line": None},
                        {"counterfactual_line": ("e2e4",)}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                event(OccurrenceKind.MISSED, **changes)

    def test_played_root_does_not_make_engine_continuation_historical(self):
        occurrence = event(counterfactual_line=("e2e4", "c7c5"))
        self.assertEqual(occurrence.actual_game_line, ("e2e4", "e7e5"))
        self.assertEqual(occurrence.counterfactual_line, ("e2e4", "c7c5"))
        self.assertEqual(occurrence.kind, OccurrenceKind.PLAYED)

    def test_immutable_validated_models_and_open_motif_vocabulary(self):
        self.assertEqual(event(motif_type="future_motif").motif_type, "future_motif")
        for changes in ({"motif_type": "missed_fork"}, {"perspective_color": "user"},
                        {"actual_game_line": ["e2e4"]}, {"actual_move": "0000"},
                        {"provenance": (("bad", []),)}, {"candidate_id": True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                event(**changes)
        with self.assertRaises(FrozenInstanceError):
            event().kind = OccurrenceKind.MISSED
        self.assertEqual(json.loads(json.dumps(asdict(event())))['kind'], 'played')

    def test_no_io_engines_or_tactic_truth_mutation(self):
        row = legacy_row()
        opportunity = TacticalOpportunity(motifs=(TacticalMotif("fork", primary=True),))
        before_row, before_truth = deepcopy(row), opportunity_to_dict(opportunity)
        with patch('sqlite3.connect', side_effect=AssertionError('No DB')), \
             patch('subprocess.Popen', side_effect=AssertionError('No engine')), \
             patch.object(builtins, 'open', side_effect=AssertionError('No file IO')):
            result = occurrence_from_legacy_candidate(row, perspective_color=TacticColor.WHITE)
            self.assertEqual(result.occurrence.source_verdict, row['candidate_status'])
            event()
        self.assertEqual(row, before_row)
        self.assertEqual(opportunity_to_dict(opportunity), before_truth)

    def test_no_tk_database_or_analyzer_dependencies(self):
        code = "import tactic_occurrences, tactic_occurrence_adapters, sys; assert not any(m == 'tkinter' or m == 'sqlite3' or m == 'chess.engine' or m.startswith('analyze_') for m in sys.modules)"
        subprocess.run([sys.executable, '-B', '-c', code], check=True, capture_output=True)


class LegacyOccurrenceTests(unittest.TestCase):
    def test_existing_missed_fork_maps_without_identity_or_proof_churn(self):
        row = legacy_row()
        result = occurrence_from_legacy_candidate(row, perspective_color=TacticColor.WHITE)
        self.assertEqual(result.reason, 'mapped_legacy_missed_claim')
        occurrence = result.occurrence
        self.assertEqual(occurrence.motif_type, 'fork')
        self.assertEqual(occurrence.relation, TacticOccurrenceRelation.MISSED_BY_PERSPECTIVE)
        self.assertEqual(occurrence.source_identity, 'candidate:42')
        self.assertEqual(occurrence.candidate_id, 42)
        self.assertEqual(occurrence.actual_game_line, ('e2e4',))
        self.assertEqual(occurrence.counterfactual_line, ('d2d4',))
        self.assertEqual(occurrence.proof_source_identity, 'candidate:42/solution_line')
        self.assertEqual(row['solution_line'], '1. d4 d5')
        opposite = occurrence_from_legacy_candidate(row, perspective_color=TacticColor.BLACK).occurrence
        self.assertEqual(opposite.relation, TacticOccurrenceRelation.MISSED_BY_OPPONENT)
        self.assertEqual(opposite.candidate_id, occurrence.candidate_id)

    def test_all_supported_legacy_motifs_and_unknown_perspective(self):
        for motif in ('fork', 'pin', 'skewer', 'xray', 'mate'):
            result = occurrence_from_legacy_candidate(legacy_row() | {'tactic_type':'missed_'+motif}, perspective_color=None)
            self.assertEqual(result.occurrence.motif_type, motif)
            self.assertEqual(result.occurrence.relation, TacticOccurrenceRelation.UNKNOWN)
            self.assertEqual(result.occurrence.kind, OccurrenceKind.MISSED)

    def test_unknown_missing_or_contradictory_legacy_fails_safely(self):
        for changes in ({'tactic_type':'missed_future'}, {'candidate_status':'rejected'},
                        {'candidate_id':None}, {'game_id':True}, {'color':None},
                        {'fen_before':'bad FEN'}, {'uci_played':'a1a8'}, {'solution_move_uci':'e2e4'},
                        {'solution_move_uci':'a8a1'}, {'color':'black'}):
            row = legacy_row() | changes
            before = deepcopy(row)
            with self.subTest(changes=changes):
                result = occurrence_from_legacy_candidate(row, perspective_color=None)
                self.assertIsNone(result.occurrence)
                self.assertEqual(row, before)
