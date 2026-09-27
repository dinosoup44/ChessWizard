"""Copy-only migration regression tests using a three hand-authored legacy records."""
from contextlib import closing
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tactic_occurrence_storage import OccurrenceLine
from tests.occurrence_migration_rehearsal import (
    ScratchOccurrenceStore, migrate_legacy, table_fingerprints, OCCURRENCE_TABLES,
)
from tests.test_tactic_occurrence_storage import example_evidence


from tests.support.legacy_source import fixture_source

class TemporaryMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source=Path(self.temp.name)/'source.db'
        fixture_source(self.source)
        self.original_hash=hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.store=ScratchOccurrenceStore(self.source)
        self.addCleanup(self.store.close)
        self.legacy_before=table_fingerprints(self.store.connection)
        self.store.apply_schema()

    def migrate(self):
        return migrate_legacy(self.store)

    def test_all_synthetic_candidates_map_including_named_developer_source(self):
        result=self.migrate()
        self.assertEqual(result['attempted'],3)
        self.assertEqual(result['mapped'],3)
        self.assertEqual(result['relation_counts'],{'missed_by_perspective':2,'unknown':1})
        failures=[r for r in result['rows'] if not r['mapped']]
        self.assertEqual(failures,[])
        self.assertEqual(result['insert_counts'],{'occurrences':3,'evidence':3,'legacy_links':3})

    def test_source_opened_readonly_and_scratch_exclusively_created(self):
        connect=sqlite3.connect
        calls=[]
        def guarded(path,*args,**kwargs):
            calls.append(str(path))
            if str(path).startswith('file:'):
                self.assertTrue(str(path).endswith('?mode=ro'))
            else:
                self.assertNotEqual(Path(path).resolve(),self.source.resolve())
                self.assertTrue(Path(path).parent.name.startswith('chesswizard_occurrence_rehearsal_'))
            return connect(path,*args,**kwargs)
        with patch('sqlite3.connect',side_effect=guarded):
            s=ScratchOccurrenceStore(self.source)
            s.close()
        self.assertEqual(len(calls),2)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.original_hash)

    def test_schema_creation_exact_and_idempotent(self):
        self.store.validate_schema()
        before=self.store.path.read_bytes()
        self.assertFalse(self.store.apply_schema())
        self.assertEqual(self.store.path.read_bytes(),before)
        self.assertTrue(OCCURRENCE_TABLES <= {r[0] for r in self.store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")})

    def test_identical_rerun_zero_rows_bytes_ids_timestamps(self):
        first=self.migrate()
        before=self.store.path.read_bytes()
        changes=self.store.connection.total_changes
        second=self.migrate()
        self.assertEqual(first['rows'],second['rows'])
        self.assertEqual(second['insert_counts'],{'occurrences':0,'evidence':0,'legacy_links':0})
        self.assertEqual(self.store.connection.total_changes,changes)
        self.assertEqual(self.store.path.read_bytes(),before)

    def test_unknown_rejected_claims_not_promoted(self):
        result=self.migrate()
        for item in result['rows']:
            if item['source_status']=='rejected':
                self.assertEqual(item['relation'],'unknown')
                evidence=self.store.read_evidence(item['revision_id'])
                self.assertEqual(evidence.proof_status,'not_decoded')
                self.assertEqual(json.loads(evidence.payload_json)['legacy_candidate']['candidate_status'],'rejected')

    def test_legacy_training_and_review_resolution_includes_developer_puzzle(self):
        result=self.migrate()
        linked=next(r for r in result['rows'] if r['candidate_id']==4)
        with self.store.transaction():
            self.store.link_review('candidate:4',linked['occurrence_id'])
            self.store.link_review('occurrence:'+linked['occurrence_id'],linked['occurrence_id'],linked['revision_id'])
        rows=list(self.store.connection.execute('SELECT t.candidate_id,l.occurrence_id FROM training_attempts t LEFT JOIN tactic_occurrence_legacy_candidates l USING(candidate_id) ORDER BY training_attempt_id'))
        self.assertIsNotNone(rows[0]['occurrence_id'])
        self.assertEqual(rows[1]['occurrence_id'],linked['occurrence_id'])
        self.assertEqual(table_fingerprints(self.store.connection,self.legacy_before),self.legacy_before)

    def test_atomic_rollback_on_mid_batch_failure(self):
        original=self.store.add_evidence
        calls=0
        def fail_second(e):
            nonlocal calls
            calls+=1
            if calls==2: raise RuntimeError('injected crash')
            return original(e)
        with patch.object(self.store,'add_evidence',side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError,'injected'):
                self.migrate()
        for table in OCCURRENCE_TABLES:
            self.assertEqual(self.store.connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0],0)
        self.assertEqual(table_fingerprints(self.store.connection,self.legacy_before),self.legacy_before)

    def test_source_tables_reject_writes_and_schema_destruction(self):
        for sql in ("UPDATE tactic_candidates SET notes='bad'",'DELETE FROM training_attempts',
                    "INSERT INTO games VALUES (999999,'white','fake','fake')",'DROP TABLE moves'):
            with self.assertRaises(sqlite3.DatabaseError): self.store.connection.execute(sql)
        self.assertEqual(table_fingerprints(self.store.connection,self.legacy_before),self.legacy_before)

    def test_duplicate_link_and_anchor_conflicts(self):
        result=self.migrate()
        mapped=[r for r in result['rows'] if r['mapped']]
        with self.assertRaises(ValueError):
            with self.store.transaction():
                self.store.link_candidate(mapped[0]['candidate_id'],mapped[1]['occurrence_id'])
        record=self.store.query('fork')[0]
        with self.assertRaises(ValueError):
            with self.store.transaction():
                self.store.add_occurrence(replace(record,decision_ply=999))

    def test_played_missed_multimotif_distinct_instance_coexistence(self):
        self.migrate()
        base=next(r for r in self.store.query('fork') if r.key.kind=='missed' and r.game_id>0)
        played=replace(base,key=replace(base.key,kind='played',tactical_move_uci=base.actual_move_uci))
        pin=replace(played,key=replace(played.key,motif_type='pin'))
        distinct=replace(played,key=replace(played.key,instance_key='synthetic-instance'))
        # Hypothetical claims are rolled back; these are not additional tactic findings.
        with self.assertRaisesRegex(RuntimeError,'discard synthetic'):
            with self.store.transaction():
                for record in (played,pin,distinct): self.store.add_occurrence(record)
                self.assertEqual(len({base.occurrence_id,played.occurrence_id,pin.occurrence_id,distinct.occurrence_id}),4)
                raise RuntimeError('discard synthetic')
        self.assertEqual(self.store.connection.execute('SELECT count(*) FROM tactic_occurrences').fetchone()[0],3)

    def test_actual_proof_prefix_binding_and_foreign_keys(self):
        self.migrate()
        record=next(r for r in self.store.query('fork') if r.key.kind=='missed' and r.game_id>0)
        evidence=example_evidence(record)
        with self.store.transaction():
            self.store.add_evidence(evidence)
            for role,root in (('actual',record.actual_move_uci),('proof',record.key.tactical_move_uci)):
                self.store.add_line(OccurrenceLine(record.occurrence_id,evidence.revision_id,'root',role,'main',
                    (root,),'fixture','root_only'))
        self.assertEqual({r.line_type for r in self.store.read_lines(evidence.revision_id)},{'actual','proof'})
        with self.assertRaises(ValueError):
            with self.store.transaction():
                self.store.add_line(OccurrenceLine(record.occurrence_id,evidence.revision_id,'wrong','actual','main',
                    (record.key.tactical_move_uci,),'fixture','root_only'))
        self.assertEqual(list(self.store.connection.execute('PRAGMA foreign_key_check')),[])
        self.assertEqual(self.store.connection.execute('PRAGMA quick_check').fetchone()[0],'ok')

    def test_discard_only_owned_copy(self):
        source_bytes=self.source.read_bytes()
        path=self.store.path
        self.store.close()
        self.assertFalse(path.exists())
        self.assertEqual(self.source.read_bytes(),source_bytes)


if __name__=='__main__': unittest.main()
