"""The persisted developer puzzle is not a candidate-less training sentinel."""
import ast
from dataclasses import replace
import gzip
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID

from tactic_occurrence_storage import NamedOccurrenceKey, OccurrenceKey, LegacyDecisionReference
from tests.occurrence_migration_rehearsal import legacy_record, ScratchOccurrenceStore, migrate_legacy
from tests.support.legacy_source import fixture_source, synthetic_rows

ROOT=Path(__file__).resolve().parents[1]
NAMESPACE='00000000-0000-4000-8000-000000000001'


class NamedLegacySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=synthetic_rows()
        cls.dev=next(r for r in cls.rows if r['candidate_id']==-1)

    def test_seed_proves_a_real_persisted_puzzle(self):
        tree=ast.parse((ROOT/'seed_dev_test_puzzle.py').read_text(encoding='utf-8-sig'))
        constants={n.targets[0].id:ast.literal_eval(n.value) for n in tree.body
            if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)}
        self.assertEqual([constants[k] for k in ('TEST_GAME_ID','TEST_MOVE_ID','TEST_CANDIDATE_ID')],[-1,-1,-1])
        self.assertEqual(self.dev['source_game_id'],constants['TEST_SOURCE_GAME_ID'])
        self.assertEqual(self.dev['fen_before'],constants['FEN_BEFORE'])
        self.assertEqual(self.dev['solution_move_uci'],constants['SOLUTION_UCI'])
        self.assertTrue(json.loads(self.dev['metadata_json'])['developer_test'])

    def test_signed_reference_maps_to_uuid_not_negative_occurrence_identity(self):
        record,reason=legacy_record(self.dev,NAMESPACE)
        self.assertEqual(reason,'mapped_named_developer_puzzle')
        self.assertIsInstance(record.key,NamedOccurrenceKey)
        self.assertEqual(record.legacy_reference,LegacyDecisionReference(-1,-1))
        self.assertEqual(UUID(record.occurrence_id).version,5)
        self.assertNotIn(-1,json.loads(record.key.identity_json))
        self.assertEqual(record.relationship('white'),'missed_by_perspective')


    def test_normal_keys_still_forbid_negative_ids(self):
        for game,move in ((-1,1),(1,-1),(-2,-2)):
            with self.assertRaises(ValueError):
                OccurrenceKey(NAMESPACE,game,move,'missed','white','fork','e1e6')

    def test_unregistered_or_unproven_source_not_fabricated(self):
        for override in ({'source':'unknown'},{'source_game_id':'NO_CANDIDATE'},
                {'metadata_json':'{}'},{'candidate_id':0},{'solution_move_uci':self.dev['uci_played']}):
            record,_=legacy_record(dict(self.dev,**override),NAMESPACE)
            self.assertIsNone(record)

    def test_named_identity_independent_of_reference_version_and_wording(self):
        record,_=legacy_record(self.dev,NAMESPACE)
        changed=dict(self.dev,candidate_id=50,game_id=60,move_id=70,detector_version=1000,notes='different wording')
        same,_=legacy_record(changed,NAMESPACE)
        self.assertEqual(record.occurrence_id,same.occurrence_id)
        self.assertNotEqual(record.legacy_reference,same.legacy_reference)
        self.assertEqual(record.occurrence_id,replace(record).occurrence_id)
        self.assertNotEqual(record.relationship('white'),record.relationship('black'))

    def test_named_local_motif_and_kind_families_do_not_collide(self):
        record,_=legacy_record(self.dev,NAMESPACE)
        normal=OccurrenceKey(NAMESPACE,1,1,'missed','white','fork','e1e6')
        self.assertEqual(len({record.occurrence_id,normal.occurrence_id,
            replace(record.key,kind='played').occurrence_id,
            replace(record.key,motif_type='pin').occurrence_id}),4)

    def test_repository_rejects_nonexistent_and_mismatched_source_references(self):
        with TemporaryDirectory() as temp:
            source=Path(temp)/'source.db';fixture_source(source)
            store=ScratchOccurrenceStore(source)
            try:
                store.apply_schema()
                record,_=legacy_record(self.dev,store.namespace)
                for bad in (replace(record,legacy_reference=LegacyDecisionReference(-2,-2)),
                        replace(record,key=replace(record.key,source_game_id='UNKNOWN'))):
                    with self.assertRaises(ValueError):
                        with store.transaction(): store.add_occurrence(bad)
                result=migrate_legacy(store)
                link=store.connection.execute('SELECT occurrence_id FROM tactic_occurrence_legacy_candidates WHERE candidate_id=-1').fetchone()[0]
                self.assertEqual(link,record.occurrence_id)
                loaded=next(r for r in store.query('fork') if r.game_id==-1)
                self.assertEqual(loaded,record)
                self.assertEqual(result['mapped'],3)
            finally: store.close()

    def test_unknown_rejected_claims_remain_unknown(self):
        rejected=[r for r in self.rows if r['candidate_status']=='rejected']
        self.assertEqual(len(rejected),1)
        for row in rejected:
            record,_=legacy_record(row,NAMESPACE)
            self.assertEqual(record.relationship(row['user_color']),'unknown')


if __name__=='__main__': unittest.main()
