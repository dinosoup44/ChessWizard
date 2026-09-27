"""Disposable-db contracts for conservative receipts; no engine searches."""
from contextlib import closing
from dataclasses import asdict, replace
import json
import sqlite3
import threading
from unittest.mock import patch
import chess
import engine_cache
from analysis_control import AnalysisCancelled
from analysis_crawler import load_user_moves
from analysis_deferred_repository import DeferredCheckRepository
from analysis_deferred_schema import create_deferred_schema, deferred_schema_available
from analysis_preflight import PreflightContext
from analysis_registry import ANALYZERS
from analysis_scout import ScoutResult
from existing_position_evidence import ExistingPositionEvidence
from solution_ownership import SolutionOwnershipService
from xray_geometry import xray_moves
from xray_preflight import POLICY
from tests.test_game_analysis import TemporaryAnalysis, position_pgn
from pathlib import Path

def case_named(name):
    data=json.loads((Path(__file__).parent/'fixtures/xray_v1_gold.json').read_text(encoding='utf-8'))
    return next(c for c in data['cases'] if c['case_id']==name)


class DeferredLedgerTests(TemporaryAnalysis):
    def setUp(self):
        super().setUp()
        case=case_named('queen_exchanged_blocker');board=chess.Board(case['fen'])
        self.assertTrue(board.turn)
        self.import_fixture(position_pgn(case['fen'],board.san(chess.Move.from_uci(case['played_uci']))))
        self.db=self.connect();self.addCleanup(self.db.close)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('BEGIN IMMEDIATE');create_deferred_schema(self.db);self.db.commit()
        self.row=load_user_moves(self.db,[1])[0]
        self.definition=ANALYZERS['missed_xray']
        self.keys={(self.row['move_id'],'missed_xray')}
        self.choices=tuple(xray_moves(chess.Board(self.row['fen_before']),self.row['uci_played']))
        self.repo=DeferredCheckRepository(self.db)
        self.all_fail()
        for target in ('engine_cache.get_or_analyze','chess.engine.SimpleEngine.popen_uci'):
            guard=patch(target,side_effect=AssertionError('Ledger must not use an engine'));guard.start();self.addCleanup(guard.stop)

    def cache(self,fen,cp=0,**extra):
        row=dict(fen=fen,engine_name=engine_cache.ENGINE_NAME,engine_version=engine_cache.ENGINE_VERSION,
            analysis_profile='tactic_quick_v1',**engine_cache.get_profile('tactic_quick_v1'),
            side_to_move='white' if chess.Board(fen).turn else 'black',score_type='cp',score_cp=cp,mate=None,score_pov='white')
        row.update(extra)
        self.db.execute('DELETE FROM engine_position_cache WHERE fen=?',(fen,))
        self.db.execute('INSERT INTO engine_position_cache ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
        self.db.commit()

    def all_fail(self):
        self.cache(self.row['fen_before'],300);self.cache(self.row['fen_after'],0)
        for choice in self.choices:self.cache(choice.fen_after,-1000)

    def record(self,definition=None):
        definition=definition or self.definition
        context=PreflightContext(definition.analysis_type,definition.analyzer_version,ExistingPositionEvidence(self.db),SolutionOwnershipService(self.db))
        return {'move_id':self.row['move_id'],'analysis_type':definition.analysis_type,
                **asdict(definition.preflight_existing_evidence(self.row,context))}

    def save(self,record=None,definition=None,**kwargs):
        return self.repo.save(definition or self.definition,self.row,record or self.record(),self.keys,**kwargs)

    def test_schema_is_explicit_additive_idempotent_and_transactional(self):
        schema=self.db.execute("SELECT name,sql FROM sqlite_master WHERE name<> 'analysis_deferred_checks' AND name NOT LIKE '%analysis_deferred_checks%'").fetchall()
        with self.assertRaises(ValueError):create_deferred_schema(self.db)
        self.db.execute('BEGIN IMMEDIATE');self.assertFalse(create_deferred_schema(self.db));self.db.rollback()
        self.assertEqual(schema,self.db.execute("SELECT name,sql FROM sqlite_master WHERE name<> 'analysis_deferred_checks' AND name NOT LIKE '%analysis_deferred_checks%'").fetchall())
        self.assertTrue(deferred_schema_available(self.db))
        self.db.execute('BEGIN IMMEDIATE');self.db.execute('DROP TABLE analysis_deferred_checks');create_deferred_schema(self.db);self.db.rollback()
        self.assertTrue(deferred_schema_available(self.db))

    def test_cached_quick_receipt_survives_restart_without_replaying_preflight(self):
        self.assertEqual(self.record()['disposition'],'cached_quick_rejected')
        self.assertEqual(self.save().action,'inserted')
        self.assertTrue(self.repo.is_current(self.definition,self.row))
        guarded=replace(self.definition,preflight_existing_evidence=lambda *args:(_ for _ in ()).throw(AssertionError('No preflight on reuse')))
        self.assertTrue(DeferredCheckRepository(self.db).is_current(guarded,self.row))
        self.assertEqual(self.count('analysis_coverage'),0);self.assertEqual(self.count('tactic_candidates'),0)

    def test_second_save_has_no_inserts_updates_timestamp_or_id_churn(self):
        record=self.record();self.save(record)
        rows=[tuple(r) for r in self.db.execute('SELECT rowid,* FROM analysis_deferred_checks')]
        changes=self.db.total_changes;before=self.digest()
        self.assertEqual(self.save(record).action,'unchanged')
        self.assertEqual(changes,self.db.total_changes)
        self.assertEqual(before,self.digest())
        self.assertEqual(rows,[tuple(r) for r in self.db.execute('SELECT rowid,* FROM analysis_deferred_checks')])

    def test_mate_defer_is_durable_without_mate_tactic_claim(self):
        self.cache(self.row['fen_before'],score_type='mate',score_cp=None,mate=-3)
        self.assertEqual(self.record()['disposition'],'mate_deferred');self.save()
        self.assertTrue(self.repo.is_current(self.definition,self.row))
        self.assertEqual(self.count('tactic_candidates'),0);self.assertEqual(self.count('analysis_coverage'),0)

    def test_played_checkmate_requires_no_cached_scores(self):
        self.import_fixture(position_pgn('7k/5Q2/6K1/8/8/8/8/8 w - - 0 1','Qg7#',identity='terminal'))
        self.row=load_user_moves(self.db,[2])[0];self.keys={(self.row['move_id'],'missed_xray')}
        record=self.record();self.assertEqual(record['disposition'],'played_checkmate')
        self.assertFalse(record['provenance']['evidence']);self.save(record)
        self.assertTrue(self.repo.is_current(self.definition,self.row))

    def test_missing_mixed_and_unknown_outcomes_are_not_persisted(self):
        self.db.execute('DELETE FROM engine_position_cache WHERE fen=?',(self.choices[0].fen_after,));self.db.commit()
        record=self.record();self.assertEqual(record['disposition'],'heavy_required')
        self.assertEqual(self.save(record).action,'ineligible')
        self.assertEqual(self.save({**record,'disposition':'mate_deferred','reason':'unclassified'}).action,'ineligible')
        forged={**record,'disposition':'cached_quick_rejected','reason':'every_geometric_alternative_fails_current_cached_quick_policy'}
        with self.assertRaises(ValueError):self.save(forged)
        self.assertEqual(self.count('analysis_deferred_checks'),0)

    def test_changed_evidence_between_plan_and_save_rolls_back(self):
        record=self.record();self.cache(self.choices[0].fen_after,500)
        with self.assertRaises(ValueError):self.save(record)
        self.assertEqual(self.count('analysis_deferred_checks'),0)

    def test_cancel_before_during_and_after_insert_never_leaves_receipt(self):
        record=self.record();cancel=threading.Event();cancel.set()
        with self.assertRaises(AnalysisCancelled):self.save(record,cancel=cancel)
        cancel.clear();original=self.definition.preflight_existing_evidence
        def interrupted(*args):
            result=original(*args);cancel.set();return result
        with self.assertRaises(AnalysisCancelled):self.save(record,definition=replace(self.definition,preflight_existing_evidence=interrupted),cancel=cancel)
        cancel.clear()
        self.db.set_trace_callback(lambda sql:cancel.set() if sql.lstrip().startswith('INSERT INTO analysis_deferred_checks') else None)
        try:
            with self.assertRaises(AnalysisCancelled):self.save(record,cancel=cancel)
        finally:self.db.set_trace_callback(None)
        self.assertEqual(self.count('analysis_deferred_checks'),0)

    def test_outer_interruption_rolls_back_provisional_receipts(self):
        self.db.execute('BEGIN IMMEDIATE');self.save();self.db.rollback()
        self.assertEqual(self.count('analysis_deferred_checks'),0)

    def test_scope_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):self.repo.save(self.definition,self.row,self.record(),set())
        with self.assertRaises(ValueError):self.save({**self.record(),'move_id':999})

    def test_version_scout_profile_policy_and_engine_options_invalidate(self):
        self.save()
        for field,value in (('analyzer_version','99'),('screener_version','99'),('scout_version','99'),('scout_config',lambda:'changed')):
            self.assertFalse(self.repo.is_current(replace(self.definition,**{field:value}),self.row),field)
        with patch('xray_preflight.POLICY',replace(POLICY,quick_gain_cp=POLICY.quick_gain_cp+1)):
            self.assertFalse(self.repo.is_current(self.definition,self.row))
        with patch('xray_preflight.PREFLIGHT_VERSION','new'):
            self.assertFalse(self.repo.is_current(self.definition,self.row))
        with patch.dict(engine_cache.PROFILES['tactic_quick_v1'],limit_value=11):
            self.assertFalse(self.repo.is_current(self.definition,self.row))
        with patch.dict('existing_position_evidence.SCOUT_ENGINE_OPTIONS',Threads=2):
            self.assertFalse(self.repo.is_current(self.definition,self.row))
        with patch('engine_cache.ENGINE_VERSION','new'):
            self.assertFalse(self.repo.is_current(self.definition,self.row))
        self.assertTrue(self.repo.is_current(self.definition,self.row))

    def test_same_key_changed_score_pv_pov_and_missing_cache_invalidate(self):
        self.save()
        for assignment in ('score_cp=score_cp+1',"principal_variation='changed'","score_pov='black'"):
            self.db.execute('SAVEPOINT evidence')
            self.db.execute('UPDATE engine_position_cache SET '+assignment+' WHERE fen=?',(self.choices[0].fen_after,))
            self.assertFalse(self.repo.is_current(self.definition,self.row),assignment)
            self.db.execute('ROLLBACK TO evidence');self.db.execute('RELEASE evidence')
        self.db.execute('DELETE FROM engine_position_cache WHERE fen=?',(self.choices[0].fen_after,));self.db.commit()
        self.assertFalse(self.repo.is_current(self.definition,self.row))

    def test_move_game_and_receipt_mutation_invalidate(self):
        self.save()
        for sql in ("UPDATE moves SET uci_played='a1a2'", "UPDATE games SET source_game_id='different'", "UPDATE analysis_deferred_checks SET details_json='{}'", "UPDATE analysis_deferred_checks SET reason_code='other'"):
            self.db.execute('SAVEPOINT changed');self.db.execute(sql)
            self.assertFalse(self.repo.is_current(self.definition,self.row),sql)
            self.db.execute('ROLLBACK TO changed');self.db.execute('RELEASE changed')

    def test_all_owned_receipt_tracks_each_live_owner(self):
        self.db.execute('DELETE FROM engine_position_cache')
        for index,choice in enumerate(self.choices):
            self.db.execute('INSERT INTO tactic_candidates(move_id,tactic_type,solution_move_uci) VALUES(?,?,?)',(self.row['move_id'],f'owner_{index}',choice.move_uci))
        self.db.commit();record=self.record();self.assertEqual(record['disposition'],'already_owned')
        self.save(record);self.assertTrue(self.repo.is_current(self.definition,self.row))
        self.db.execute("UPDATE tactic_candidates SET candidate_status='rejected' WHERE tactic_type='owner_0'");self.db.commit()
        self.assertFalse(self.repo.is_current(self.definition,self.row))

    def test_canonical_and_heavy_coverage_are_protected(self):
        self.db.execute("INSERT INTO tactic_candidates(move_id,tactic_type) VALUES(?,'missed_xray')",(self.row['move_id'],));self.db.commit()
        before=[tuple(r) for r in self.db.execute('SELECT * FROM tactic_candidates')]
        self.assertEqual(self.save().action,'protected')
        self.assertEqual(before,[tuple(r) for r in self.db.execute('SELECT * FROM tactic_candidates')])
        self.assertEqual(self.count('analysis_deferred_checks'),0)

    def test_complete_game_skips_scout_preflight_and_engine_on_second_run(self):
        definition=replace(self.definition,screener=lambda row:True,scout=lambda row,evidence:ScoutResult(True,'fixture'))
        service=self.service(definition);first=service.run()
        self.assertEqual((first.games_completed,first.games_remaining,first.completed_deferred_checks,first.games_completed_with_deferrals),(1,0,1,1))
        before=self.digest()
        guarded=replace(definition,screener=lambda row:(_ for _ in ()).throw(AssertionError('No screen')),
            scout=lambda *a:(_ for _ in ()).throw(AssertionError('No scout')),
            preflight_existing_evidence=lambda *a:(_ for _ in ()).throw(AssertionError('No preflight')))
        second=self.service(guarded).run()
        self.assertEqual((second.games_skipped,second.checks_processed,second.engine_searches,second.database_changes),(1,0,0,0))
        self.assertEqual(before,self.digest())

    def test_optional_ledger_is_owned_by_safe_delete_preview(self):
        self.save()
        from data_management_repository import DataManagementRepository
        repo=DataManagementRepository(self.path);plan=repo.plan_game_deletion((1,))
        self.assertEqual(dict(plan.counts)['analysis_deferred_checks'],1)
        repo.execute_game_deletion(plan)
        self.assertEqual(self.count('analysis_deferred_checks'),0);self.assertEqual(self.count('games'),0)
        self.assert_integrity()

    def test_recent_actionable_scope_excludes_current_receipt_before_limit(self):
        from game_analysis_models import AnalysisScopeKind, GameAnalysisScope
        from game_analysis_repository import select_actionable_scope
        self.save();self.db.commit();before=self.digest()
        for kind in (AnalysisScopeKind.RECENT_50,AnalysisScopeKind.RECENT_100):
            selected=select_actionable_scope(self.db,[self.definition],GameAnalysisScope(kind))
            self.assertEqual(selected.game_ids,())
            changed=replace(self.definition,analyzer_version=str(int(self.definition.analyzer_version)+1))
            selected=select_actionable_scope(self.db,[changed],GameAnalysisScope(kind))
            self.assertEqual(selected.game_ids,(1,))
        self.assertEqual(before,self.digest())
