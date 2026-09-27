"""Relationship truth boundary, frozen identities and isolated search integration."""
from contextlib import closing
from dataclasses import asdict, replace, FrozenInstanceError
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import chess
from game_search_models import GameSearchCriteria
from game_search_service import GameSearchService
from game_search_tactics import OccurrenceEvidenceSelection
from game_collection_models import CollectionDetails
from game_collection_service import GameCollectionService
from tactic_relationships import (
    AcceptedTactic, DecisionIdentity, RecordedDecision, TacticTruthScope, assess_relationship,
)
from tactic_relationship_repository import TacticRelationshipRepository, assess_legacy_row
from tests.test_game_search import SearchFixture
from tests.occurrence_migration_rehearsal import ScratchOccurrenceStore, migrate_legacy, LEGACY_SELECT
from tests.support.legacy_source import fixture_source
from tactic_occurrence_storage import OccurrenceEvidence

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = '00000000-0000-4000-8000-000000000001'


def facts(*, actor='white', user='white', motif='fork', played=True):
    board = chess.Board()
    if actor == 'black': board.push_uci('e2e4')
    decision = DecisionIdentity(1, 1, 'fixture', 'game-1', 1 if actor=='white' else 2, board.fen(), actor)
    actual = 'e2e4' if actor=='white' else 'e7e5'
    tactical = actual if played else ('d2d4' if actor=='white' else 'd7d5')
    return (AcceptedTactic(decision, motif, tactical, 'provider:accepted', True, True),
            RecordedDecision(decision, actual, user))


class RelationshipTests(unittest.TestCase):
    def test_all_motifs_both_sides_all_relations(self):
        # Motif truth is supplied; the starting board tests comparison, not tactics.
        for motif in ('fork', 'mate', 'pin', 'skewer', 'xray'):
            for actor in ('white','black'):
                for user in ('white','black'):
                    for played in (True,False):
                        with self.subTest(motif=motif,actor=actor,user=user,played=played):
                            result=assess_relationship(*facts(actor=actor,user=user,motif=motif,played=played))
                            expected=('played' if played else 'missed')+('_by_perspective' if actor==user else '_by_opponent')
                            self.assertEqual(result.relation,expected)

    def test_unknown_and_inactive_inputs_do_not_establish_truth(self):
        tactic,recorded=facts()
        cases=[(replace(tactic,active=False),recorded,'inactive_tactic'),
               (replace(tactic,accepted=False),recorded,'unaccepted_tactic_evidence'),
               (tactic,replace(recorded,user_color=None),'unknown_user_color'),
               (tactic,replace(recorded,user_color='guess'),'unknown_user_color'),
               (tactic,replace(recorded,actual_move=None),'missing_move_evidence'),
               (replace(tactic,tactical_move=None),recorded,'missing_move_evidence'),
               (replace(tactic,tactical_move='e2e5'),recorded,'invalid_decision_evidence'),
               (replace(tactic,scope=TacticTruthScope.LEGACY_MISSED),recorded,'legacy_missed_claim_requires_verified_played_evidence')]
        for claim,actual,reason in cases:
            with self.subTest(reason=reason):
                result=assess_relationship(claim,actual)
                self.assertFalse(result.known);self.assertEqual(result.reason,reason)

    def test_position_game_move_ply_source_side_exact_binding(self):
        tactic,recorded=facts()
        for field,value in [('game_id',2),('move_id',2),('ply',3),('source','other'),
                            ('source_game_id','other'),('actor','black'),('fen',chess.Board().fen().replace('0 1','1 1'))]:
            result=assess_relationship(replace(tactic,identity=replace(tactic.identity,**{field:value})),recorded)
            self.assertEqual(result.reason,'decision_identity_mismatch')
        wrong=replace(tactic.identity,actor='black')
        self.assertEqual(assess_relationship(replace(tactic,identity=wrong),replace(recorded,identity=wrong)).reason,
                         'actor_disagrees_with_decision_position')
        wrong=replace(tactic.identity,game_id=0)
        self.assertEqual(assess_relationship(replace(tactic,identity=wrong),replace(recorded,identity=wrong)).reason,'invalid_source_identity')

    def test_signed_source_references_are_not_abs_or_missing(self):
        tactic,recorded=facts(played=False)
        signed=replace(tactic.identity,game_id=-1,move_id=-1,source='dev',source_game_id='MERLIN_TEST_ROOK_FORK')
        self.assertTrue(assess_relationship(replace(tactic,identity=signed),replace(recorded,identity=signed)).known)
        self.assertFalse(assess_relationship(tactic,replace(recorded,identity=signed)).known)

    def test_mate_initiation_and_terminal_position_are_distinct(self):
        board=chess.Board()
        for move in ('f2f3','e7e5','g2g4'):board.push_uci(move)
        decision=DecisionIdentity(1,4,'fixture','mate',4,board.fen(),'black')
        claim=AcceptedTactic(decision,'mate','d8h4','accepted-mate',True,True)
        self.assertEqual(assess_relationship(claim,RecordedDecision(decision,'d8h4','white')).relation,'played_by_opponent')
        self.assertEqual(assess_relationship(claim,RecordedDecision(decision,'b8c6','white')).relation,'missed_by_opponent')
        board.push_uci('d8h4')
        terminal=replace(decision,fen=board.fen(),actor='white',ply=5,move_id=5)
        self.assertFalse(assess_relationship(replace(claim,identity=terminal),RecordedDecision(terminal,'a2a3','white')).known)

    def test_pure_immutable_no_engine_ui_database_imports(self):
        value=assess_relationship(*facts())
        with self.assertRaises(FrozenInstanceError):value.reason='other'
        code="import sys,tactic_relationships,tactic_relationship_repository; assert 'tkinter' not in sys.modules; assert 'chess.engine' not in sys.modules"
        subprocess.run([sys.executable,'-B','-c',code],check=True,cwd=ROOT)


class RelationshipSearchTests(SearchFixture):
    def test_populated_all_motifs_relationships_and_collections(self):
        revisions=[]
        for gid,kind in ((1,'played'),(2,'played'),(3,'missed'),(5,'missed')):
            for motif in ('fork','mate','pin','skewer','xray'):
                rev,_=self.occurrence(gid,kind=kind,motif=motif,ply=2 if gid==5 else 1)
                revisions.append(rev)
        selection=OccurrenceEvidenceSelection(frozenset(revisions))
        self.service=GameSearchService(self.path,occurrence_selection=selection)
        collections=GameCollectionService(self.path)
        cid=collections.create(CollectionDetails('relationship fixture'))
        collections.add_games(cid,(1,2,3))
        before=self.digest()
        for motif in ('fork','mate','pin','skewer','xray'):
            for relation,gid in [('played_by_perspective',1),('played_by_opponent',2),('missed_by_perspective',3),('missed_by_opponent',5)]:
                self.assertEqual(self.ids(motifs=(motif,),relationships=(relation,)),[gid])
                self.assertEqual(self.ids(motifs=(motif,),relationships=(relation,),collection_id=cid),[] if gid==5 else [gid])
        self.assertEqual(len(self.ids(relationships=('played_by_perspective','missed_by_perspective'))),2)
        self.assertEqual(self.service.search(GameSearchCriteria(game_id=1)).games[0].tactic_count,5)
        self.assertEqual(self.digest(),before)

    def test_motif_and_relation_cannot_cross_occurrences(self):
        first,_=self.occurrence(1,kind='played',motif='fork')
        second,_=self.occurrence(1,kind='missed',motif='pin',ply=2)
        self.service=GameSearchService(self.path,occurrence_selection=OccurrenceEvidenceSelection(frozenset((first,second))))
        self.assertEqual(self.ids(motifs=('fork',),relationships=('missed_by_opponent',)),[])
        self.assertEqual(self.ids(motifs=('pin',),relationships=('missed_by_opponent',)),[1])

    def test_selected_rejected_or_unverified_archive_is_not_a_current_claim(self):
        rev,oid=self.occurrence(1)
        self.service=GameSearchService(self.path,occurrence_selection=OccurrenceEvidenceSelection(frozenset((rev,))))
        for admission,proof in (('rejected','verified'),('accepted','ambiguous'),('accepted','not_decoded')):
            with closing(self.connect()) as db:
                db.execute('UPDATE tactic_occurrence_evidence SET admission_status=?,proof_status=? WHERE revision_id=?',(admission,proof,rev))
                db.commit()
            self.assertEqual(self.ids(motifs=('fork',)),[])

    def test_standalone_actor_and_uuid_tampering_are_not_projected(self):
        rev,oid=self.occurrence(1)
        self.service=GameSearchService(self.path,occurrence_selection=OccurrenceEvidenceSelection(frozenset((rev,))))
        with closing(self.connect()) as db:
            db.execute("UPDATE tactic_occurrences SET actor_color='black' WHERE occurrence_id=?",(oid,));db.commit()
        self.assertEqual(self.ids(motifs=('fork',)),[])

    def test_rejected_legacy_cannot_be_revived(self):
        self.candidate(1,rejected=True)
        self.candidate(2,status='rejected')
        with closing(self.connect()) as db:
            self.assertEqual(TacticRelationshipRepository(db).candidates(),())
        self.assertEqual(self.ids(motifs=('fork',)),[])

    def test_replay_mapping_is_insert_once_and_no_candidate_churn(self):
        cid=self.candidate(1)
        before=self.digest()
        store=ScratchOccurrenceStore(self.path)
        self.addCleanup(store.close)
        store.namespace=NAMESPACE
        store.connection.set_authorizer(store._authorize)
        repo=TacticRelationshipRepository(store.connection)
        item=repo.candidates()[0];plan=repo.plan(item,NAMESPACE)
        self.assertEqual(plan.action,'insert')
        with store.transaction():
            self.assertTrue(store.add_occurrence(plan.record))
            self.assertTrue(store.link_candidate(cid,plan.record.occurrence_id))
        changes=store.connection.total_changes
        self.assertEqual(repo.plan(item,NAMESPACE).action,'unchanged')
        with store.transaction():
            self.assertFalse(store.add_occurrence(plan.record))
            self.assertFalse(store.link_candidate(cid,plan.record.occurrence_id))
        self.assertEqual(store.connection.total_changes,changes)
        self.assertEqual(self.digest(),before)
        other=replace(item,tactical_move='c2c4')
        self.assertEqual(repo.plan(other,NAMESPACE).action,'conflict')

    def test_signed_existing_uuid_preserved(self):
        source=Path(self.temporary.name)/'signed.db' if hasattr(self,'temporary') else self.path.parent/'signed.db'
        fixture_source(source)
        store=ScratchOccurrenceStore(source);self.addCleanup(store.close)
        store.apply_schema();migrate_legacy(store)
        repo=TacticRelationshipRepository(store.connection)
        row=next(dict(r) for r in store.connection.execute(LEGACY_SELECT) if r['candidate_id']==-1)
        item=assess_legacy_row(row,row['user_color'])
        plan=repo.plan(item,store.namespace)
        self.assertEqual(plan.action,'unchanged')
        self.assertEqual(plan.record.key.identity_version,2)
        self.assertEqual(plan.record.game_id,-1)
        self.assertEqual(plan.record.occurrence_id,repo.plan(item,store.namespace).record.occurrence_id)


if __name__=='__main__':unittest.main()
