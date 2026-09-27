from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from tests.support.checkpoint_verifier import compare_database_files, integrity, digest, verify_project_files


class CheckpointVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source, self.backup = root / "source.db", root / "backup.db"
        with closing(sqlite3.connect(self.source)) as connection:
            connection.executescript("CREATE TABLE one(x); CREATE TABLE two(y); INSERT INTO one VALUES (17);")
            with closing(sqlite3.connect(self.backup)) as target:
                connection.backup(target)

    def test_actual_sqlite_backup_metadata_is_accepted(self):
        result = compare_database_files(self.source, self.backup, destination_schema_before=0)
        self.assertEqual(result["unexplained_differences"], 0)
        self.assertEqual(result["fields"][1]["backup"], 1)
        self.assertEqual(integrity(self.backup)["foreign_key_check"], [])

    def test_arbitrary_header_and_page_changes_are_rejected(self):
        original = self.backup.read_bytes()
        for offset in (16, 28, 44, 60, 68, 99, 100, len(original)-1):
            with self.subTest(offset=offset):
                damaged = bytearray(original); damaged[offset] ^= 1; self.backup.write_bytes(damaged)
                with self.assertRaises(ValueError):
                    compare_database_files(self.source, self.backup)
        self.backup.write_bytes(original)

    def test_size_mismatch_rejected(self):
        with self.backup.open("ab") as file: file.write(b"x")
        with self.assertRaisesRegex(ValueError, "size"):
            compare_database_files(self.source, self.backup)

    def test_expected_cookie_and_counter_coherence_are_enforced(self):
        with self.assertRaisesRegex(ValueError, "cookie"):
            compare_database_files(self.source, self.backup, destination_schema_before=10)
        data = bytearray(self.backup.read_bytes()); data[95] ^= 1; self.backup.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "Incoherent"):
            compare_database_files(self.source, self.backup)

    def test_project_hash_mismatch_rejected(self):
        root = self.source.parent; a, b = root / "a", root / "b"; a.mkdir(); b.mkdir()
        (a / "test.txt").write_text("good"); (b / "test.txt").write_text("good")
        expected = {"test.txt": digest(a / "test.txt")}
        self.assertEqual(verify_project_files(a,b,expected)["verified_files"],1)
        (b / "test.txt").write_text("evil")
        with self.assertRaisesRegex(ValueError,"Project file mismatch"):
            verify_project_files(a,b,expected)

    def test_integrity_detects_foreign_key_violation(self):
        with closing(sqlite3.connect(self.backup)) as c:
            c.executescript("CREATE TABLE parent(id PRIMARY KEY); CREATE TABLE child(pid REFERENCES parent(id)); INSERT INTO child VALUES(7);")
        with self.assertRaisesRegex(ValueError,"integrity"):
            integrity(self.backup)
