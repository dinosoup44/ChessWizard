"""New moves use the proven backbone without inventing existing candidate IDs."""
from dataclasses import replace
from collections import Counter
from unittest.mock import patch
from types import SimpleNamespace
import json,sqlite3,unittest
import chess
from analysis_registry import ANALYZERS
from analysis_crawler import coverage_decision
from analysis_results import HeavyResult
from discovery_registry import fork_v31
from discovery_scope import build_scope,validate_scope
from fork_discovery import analyze_single_move
from analyze_forks_v31 import analyze_position,analyze_existing_candidate
from test_fork_multiline import FixtureService,selected_two_ply_proof
from test_forks_v3 import candidate
from test_heavy_services import candidate_payload
import test_heavy_services as repo_fixtures


def proof(*args):
    result=selected_two_ply_proof(*args)
    return replace(result,final_evidence={"score_type":"cp","score_pov":"white","score_cp":400})


class ForkDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.existing=candidate("r3k3/7p/8/3N4/8/8/7P/4K3 w - - 0 1");self.row={k:v for k,v in self.existing.items() if k not in
            {"candidate_id","candidate_status","detector_version","solution_move_uci","solution_move_san","solution_line","metadata_json"}}

    def test_new_move_reaches_backbone_gate_proof_scale_and_opportunity(self):
        service=FixtureService(self.existing)
        with patch("analyze_forks_v3_multiline.verify_bounded_line",side_effect=proof),patch("analyze_forks_v2.analyze_single_move",side_effect=AssertionError("Legacy discovery forbidden")):
            result=analyze_single_move(self.row,service)
        self.assertEqual(result.state,"candidate",result.details)
        self.assertEqual(result.candidate["detector_version"],"3.1")
        proposal=next(p for p in result.details["proposals"] if p["move_uci"]=="d5c7")
        detail=proposal["result"]["details"]
        self.assertIsNone(detail["candidate_id"])
        self.assertEqual(detail["classification"],"verified")
        self.assertTrue(detail["root_move_passes_gate"])
        self.assertTrue(detail["root_scale"])
        self.assertTrue(detail["backbone_provenance"])
        self.assertTrue(detail["branches"][0]["settlement_evidence"])
        self.assertNotIn("lines",detail["root_admission"]["root"])

    def test_existing_candidate_entry_still_requires_existing_candidate(self):
        with self.assertRaises(ValueError): analyze_existing_candidate(self.row,FixtureService(self.existing))

    def test_rank_two_and_three_are_not_filtered_by_discovery(self):
        for choices in ([('Kf1',420),('Nc7+',400)],[('Kf1',450),('Kd1',425),('Nc7+',400)]):
            with patch("analyze_forks_v3_multiline.verify_bounded_line",side_effect=proof):
                result=analyze_single_move(self.row,FixtureService(self.existing,choices))
            self.assertEqual(result.state,"candidate")
            p=next(p for p in result.details["proposals"] if p["move_uci"]=="d5c7")
            self.assertEqual(p["root_diagnostic"]["native_rank"],len(choices))

    def test_failed_gate_does_not_run_proof(self):
        with patch("analyze_forks_v3_multiline.verify_bounded_line") as prove:
            result=analyze_position(self.row,'d5c7',FixtureService(self.existing,[('Kf1',800),('Nc7+',0)]))
        prove.assert_not_called();self.assertEqual(result.classification,"rejected")

    def test_registry_is_explicit_and_does_not_activate_pin_or_default_fork(self):
        before=dict(ANALYZERS);definition,profile,target=fork_v31()
        self.assertEqual(ANALYZERS,before)
        self.assertEqual(definition.analyzer_version,"3.1")
        self.assertEqual(profile.generator.candidate_line_count,3)
        self.assertEqual(ANALYZERS['missed_fork'].analyzer_version,'2')


class DiscoveryPersistenceTests(unittest.TestCase):
    setUp=repo_fixtures.RepositoryTests.setUp
    save=repo_fixtures.RepositoryTests.save
    seed_old_candidate=repo_fixtures.RepositoryTests.seed_old_candidate

    def test_discovery_cannot_update_existing_canonical_without_coverage(self):
        self.seed_old_candidate()
        before=[tuple(r) for r in self.c.execute('SELECT * FROM tactic_candidates')]
        result=self.save(HeavyResult('candidate',candidate_payload()),preserve_existing=True)
        self.assertEqual(result['action'],'protected')
        self.assertEqual(before,[tuple(r) for r in self.c.execute('SELECT * FROM tactic_candidates')])

    def test_identical_retryable_ambiguity_does_not_churn_coverage(self):
        result=HeavyResult('error',details={'classification':'ambiguous','reason':'bounded_proof_unsettled'})
        self.save(result);changes=self.c.total_changes
        first=dict(self.c.execute('SELECT * FROM analysis_coverage').fetchone())
        self.assertEqual(self.save(result)['action'],'unchanged')
        self.assertEqual(self.c.total_changes,changes)
        self.assertEqual(dict(self.c.execute('SELECT * FROM analysis_coverage').fetchone()),first)
        self.assertEqual(coverage_decision(self.definition,first),'retry')


class CohortSelectionTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:");self.addCleanup(self.db.close);self.db.row_factory=sqlite3.Row
        self.db.executescript("""CREATE TABLE games(game_id,source,source_game_id,played_at,account_id,variant,raw_pgn);
            CREATE TABLE moves(move_id,game_id,is_user_move,fen_before,ply_number);
            CREATE TABLE analysis_coverage(move_id,analysis_type,coverage_status,screener_version,scout_version,scout_config,analyzer_version,details_json);""")
        self.definition,self.profile,self.target=fork_v31()
        for gid,date in ((1,'2026.01.01'),(2,'2026.03.01'),(3,'2026.02.01'),(4,'2026.04.01')):
            self.db.execute('INSERT INTO games VALUES(?,?,?,?,?,?,?)',(gid,'chesscom',str(gid),date,1,None,'[Event "Live Chess"]'))
            self.db.execute('INSERT INTO moves VALUES(?,?,?,?,?)',(gid,gid,1,chess.STARTING_FEN,1))

    def test_dates_and_provenance_win_over_id_order(self):
        scope=build_scope(self.db,self.definition,self.target,{4},count=2)
        self.assertEqual(scope['game_ids'],[2,3]);self.assertEqual(scope['overlap'],0)

    def test_version_and_policy_currentness_exclude_fully_processed_game(self):
        d=self.definition
        self.db.execute('INSERT INTO analysis_coverage VALUES(?,?,?,?,?,?,?,?)',(4,d.analysis_type,'analyzed_no_hit',d.screener_version,d.scout_version,d.scout_config(),d.analyzer_version,json.dumps({'discovery_identity':self.target})))
        scope=build_scope(self.db,d,self.target,set(),count=2)
        self.assertEqual(scope['game_ids'],[2,3]);self.assertEqual(scope['exclusions']['fully_current_target_workflow'],1)
        self.db.execute("UPDATE analysis_coverage SET analyzer_version='2'")
        self.assertEqual(build_scope(self.db,d,self.target,set(),count=2)['game_ids'],[4,2])

    def test_never_silently_shrink_requested_scope(self):
        with self.assertRaises(ValueError): build_scope(self.db,self.definition,self.target,set(),count=500)
