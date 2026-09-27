from dataclasses import FrozenInstanceError, replace
import sqlite3
import unittest

import chess
from analysis_settings import load_profile
from candidate_line_request import request_identity
from candidate_line_repository import CandidateLineRepository, insert_only_authorizer
from candidate_line_engine import CandidateLineGenerator
from candidate_line_service import CandidateLineService
from candidate_lines import CandidateLineSet, LineScore
from migrate_candidate_line_cache import CREATE_TABLE, migrate, validate_schema
from test_candidate_lines import FakeEngine, make_lines


class CandidateLineLiveSafetyTests(unittest.TestCase):
    def test_exact_schema_rejects_missing_check_or_unique_and_rolls_back(self):
        for sql in (CREATE_TABLE.replace(' CHECK(schema_version = 1)', ''),
                    CREATE_TABLE.replace(',\n    UNIQUE(fen, engine_identity)', '')):
            with sqlite3.connect(':memory:') as connection:
                connection.execute('BEGIN IMMEDIATE')
                connection.execute(sql)
                with self.assertRaises(ValueError):
                    validate_schema(connection)
                connection.rollback()
                self.assertEqual(connection.execute('SELECT name FROM sqlite_master').fetchall(), [])
        with sqlite3.connect(':memory:') as connection:
            connection.row_factory = sqlite3.Row
            migrate(connection)
            validate_schema(connection)

    def test_insert_only_boundary_and_zero_work_read_through(self):
        with sqlite3.connect(':memory:') as connection:
            connection.execute('CREATE TABLE tactic_candidates(candidate_id INTEGER PRIMARY KEY)')
            connection.execute('INSERT INTO tactic_candidates VALUES(1828)')
            migrate(connection)
            connection.commit()
            connection.set_authorizer(insert_only_authorizer)
            repository = CandidateLineRepository(connection)
            service = CandidateLineService(CandidateLineGenerator(FakeEngine()), write_store=repository)
            first = service.candidate_lines(chess.STARTING_FEN)
            connection.commit()
            snapshot = connection.execute('SELECT * FROM engine_candidate_line_cache').fetchall()
            changes = connection.total_changes
            self.assertEqual(service.candidate_lines(chess.STARTING_FEN), first)
            self.assertFalse(repository.put(first))
            self.assertEqual(connection.total_changes, changes)
            self.assertEqual(connection.execute('SELECT * FROM engine_candidate_line_cache').fetchall(), snapshot)
            self.assertEqual(service.stats['engine_searches'], 1)
            for sql in ('DELETE FROM engine_candidate_line_cache',
                        "UPDATE engine_candidate_line_cache SET created_at='changed'",
                        'INSERT INTO tactic_candidates VALUES(1830)', 'DELETE FROM tactic_candidates',
                        'CREATE TABLE unexpected(id)', 'PRAGMA user_version=7', 'PRAGMA optimize'):
                with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                    connection.execute(sql)
            self.assertEqual(connection.execute('SELECT * FROM tactic_candidates').fetchall(), [(1828,)])

    def test_raw_identity_matrix_and_policy_currentness(self):
        profile = load_profile('normal')
        generator = profile.generator
        base = request_identity(generator)
        variants = [replace(generator, candidate_line_count=1), replace(generator, analysis_version=2)]
        for key, value in {'engine_name': 'Other', 'engine_version': '19', 'profile_id': 'other_family',
                           'depth': 16, 'nodes': 1000, 'time_seconds': 0.1, 'threads': 2, 'hash_mb': 128}.items():
            variants.append(replace(generator, engine=replace(generator.engine, **{key: value})))
        hashes = [base, *(request_identity(value) for value in variants), request_identity(generator, ('e2e4',))]
        self.assertEqual(len(hashes), len(set(hashes)))
        self.assertEqual(request_identity(generator, ('d2d4', 'e2e4', 'd2d4')),
                         request_identity(generator, ('e2e4', 'd2d4')))
        for policy in (replace(profile, quality_gate=replace(profile.quality_gate, absolute_tolerance_cp=90)),
                       replace(profile, scale=replace(profile.scale, base_interest=11))):
            self.assertEqual(profile.engine_identity, policy.engine_identity)
            self.assertNotEqual(profile.currentness_identity, policy.currentness_identity)

    def test_readback_mate_immutability_and_schema_fail_closed(self):
        with sqlite3.connect(':memory:') as connection:
            migrate(connection)
            repo = CandidateLineRepository(connection)
            original = make_lines([LineScore(mate_score=2)], metadata={'nested': [1, 2]})
            repo.put(original)
            cached = repo.get(original.fen, original.engine_identity)
            self.assertEqual(cached, original)
            self.assertEqual(CandidateLineSet.from_json(cached.to_json()), cached)
            self.assertEqual(cached.lines[0].score.mate_winner, 'white')
            with self.assertRaises(FrozenInstanceError): cached.requested_line_count = 9
            with self.assertRaises(TypeError): cached.lines[0].metadata['nested'][0] = 9
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('UPDATE engine_candidate_line_cache SET schema_version=2')
            connection.execute("UPDATE engine_candidate_line_cache SET payload_json=replace(payload_json, '\"schema_version\":1', '\"schema_version\":2')")
            with self.assertRaises(ValueError): repo.get(original.fen, original.engine_identity)

    def test_fen_is_part_of_composite_key(self):
        with sqlite3.connect(':memory:') as connection:
            migrate(connection)
            repo = CandidateLineRepository(connection)
            first = make_lines([100])
            board = chess.Board()
            board.push_san('e4')
            second = make_lines([-100], fen=board.fen())
            self.assertEqual(first.engine_identity, second.engine_identity)
            repo.put(first)
            repo.put(second)
            self.assertEqual(repo.get(first.fen, first.engine_identity), first)
            self.assertEqual(repo.get(second.fen, second.engine_identity), second)
            self.assertEqual(connection.execute('SELECT count(*) FROM engine_candidate_line_cache').fetchone()[0], 2)
