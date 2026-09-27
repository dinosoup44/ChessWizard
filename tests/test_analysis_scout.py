import unittest
from unittest.mock import Mock, patch

import chess

from analysis_crawler import ANALYZERS, coverage_decision, is_light_fork_shape
from analysis_scout import ScoutEvidence, scout_fork, scout_mate


class ScoutTests(unittest.TestCase):
    def test_static_screen_keeps_two_minor_piece_forks(self):
        board = chess.Board("7k/8/2b3n1/8/8/5N2/8/K7 w - - 0 1")
        move = chess.Move.from_uci("f3e5")
        self.assertIn(move,board.legal_moves)
        self.assertTrue(is_light_fork_shape(board,move,chess.WHITE))

    def test_mate_requires_positive_player_score_within_three_moves(self):
        for distance, expected in ((-3,False),(0,False),(1,True),(3,True),(4,False)):
            evidence = Mock()
            evidence.for_player.return_value = {"score_type":"mate", "mate":distance}
            self.assertEqual(scout_mate({},evidence).send_to_heavy, expected)

    def test_black_pov_and_position_reuse(self):
        board = chess.Board()
        board.push_uci("e2e4")
        before = board.fen()
        board.push_uci("e7e5")
        row = {"color":"black", "fen_before":before, "fen_after":board.fen(), "uci_played":"e7e5"}
        result = {"score_type":"mate", "mate":-2, "score_pov":"white", "cache_hit":True}
        with patch("analysis_scout.get_or_analyze", return_value=result) as analyze:
            evidence = ScoutEvidence(None,None)
            self.assertTrue(scout_mate(row,evidence).send_to_heavy)
            self.assertEqual(evidence.for_player(row)["mate"],2)
            self.assertEqual(analyze.call_count,1)

    def test_fork_retains_saving_and_equalizing_opportunities(self):
        for before, after, expected in ((-200,-400,True),(0,-200,True),(300,100,True),(50,40,False)):
            evidence = Mock()
            evidence.for_player.side_effect = [
                {"score_type":"cp", "score_cp":before},
                {"score_type":"cp", "score_cp":after},
            ]
            self.assertEqual(scout_fork({},evidence).send_to_heavy,expected)

    def test_invalid_data_is_an_error(self):
        evidence = ScoutEvidence(None,None)
        with self.assertRaises(ValueError):
            evidence.for_player({"color":"purple"})
        with self.assertRaises(ValueError):
            evidence.for_player({"color":"white", "fen_before":chess.STARTING_FEN,
                                 "fen_after":chess.STARTING_FEN, "uci_played":"e2e5"})

    def test_coverage_errors_and_versions(self):
        definition = ANALYZERS["missed_fork"]
        coverage = {"coverage_status":"candidate", "screener_version":"0",
                    "scout_version":"0", "analyzer_version":"2", "scout_config":""}
        self.assertEqual(coverage_decision(definition,coverage),"current")
        coverage["coverage_status"] = "error"
        self.assertEqual(coverage_decision(definition,coverage),"retry")
        coverage.update(coverage_status="screened_out",screener_version=definition.screener_version)
        self.assertEqual(coverage_decision(definition,coverage),"current")
        coverage["scout_version"] = "old-scout"
        self.assertEqual(coverage_decision(definition,coverage),"current")
        coverage.update(coverage_status="analyzed_no_hit",scout_version="0")
        self.assertEqual(coverage_decision(definition,coverage),"needs_scout")
        coverage["scout_version"] = definition.scout_version
        coverage["scout_config"] = definition.scout_config()
        self.assertEqual(coverage_decision(definition,coverage),"current")
        coverage["analyzer_version"] = "1"
        self.assertEqual(coverage_decision(definition,coverage),"needs_reanalysis")


if __name__ == "__main__":
    unittest.main()
