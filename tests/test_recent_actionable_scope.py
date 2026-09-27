"""Recent scopes count actionable games after unchanged readiness, not before it."""
from contextlib import closing
from unittest.mock import patch
import chess.engine
from game_analysis_models import AnalysisScopeKind, GameAnalysisScope
from game_analysis_repository import select_actionable_scope, iter_game_readiness
from tests.test_game_analysis import TemporaryAnalysis, negative_definition
from tests.test_game_import import pgn


class RecentActionableTests(TemporaryAnalysis):
    def test_recent_fifty_and_hundred_exclude_complete_empty_invalid_before_limit(self):
        self.import_fixture(''.join(pgn(identity=str(i),moves='1. e4 1-0') for i in range(1,131)))
        with closing(self.connect()) as db:
            db.execute('DELETE FROM moves WHERE game_id=130')
            db.execute("UPDATE moves SET fen_after='invalid' WHERE game_id=129")
            db.commit()
        service=self.service()
        with patch.object(chess.engine.SimpleEngine,'popen_uci',side_effect=AssertionError('No engine')):
            complete=service.run(GameAnalysisScope(AnalysisScopeKind.SELECTED,tuple(range(119,129))))
            self.assertEqual(complete.games_completed,10)
            before=self.digest()
            with closing(self.connect()) as db:
                for kind,count,last in ((AnalysisScopeKind.RECENT_50,50,69),(AnalysisScopeKind.RECENT_100,100,19)):
                    scope=GameAnalysisScope(kind)
                    selection=select_actionable_scope(db,[negative_definition()],scope)
                    self.assertEqual(selection.game_ids,tuple(range(118,last-1,-1)))
                    direct=tuple(iter_game_readiness(db,[negative_definition()],scope))
                    self.assertEqual(len(direct),count)
                    self.assertTrue(all(g.needs_work and not g.readiness_error for g in direct))
                    preview=service.preview(scope)
                    self.assertEqual(preview.eligible_games,count)
                    self.assertEqual([g.game_id for g in preview.queued],list(range(118,68,-1)))
            self.assertEqual(before,self.digest())
            run=service.run(GameAnalysisScope(AnalysisScopeKind.RECENT_50))
            self.assertEqual((run.scope_total,run.games_completed,run.errors,run.engine_searches),(50,50,0,0))
            with closing(self.connect()) as db:
                written={r[0] for r in db.execute('SELECT DISTINCT game_id FROM moves JOIN analysis_coverage USING(move_id)')}
            self.assertEqual(written,set(range(69,129)))
            next_scope=service.preview(GameAnalysisScope(AnalysisScopeKind.RECENT_50))
            self.assertEqual([g.game_id for g in next_scope.queued],list(range(68,18,-1)))
        self.assert_integrity()
