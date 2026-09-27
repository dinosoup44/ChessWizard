"""Recovery replacement must preserve unrelated data and verified previous copies."""
from pathlib import Path
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from backup_recovery import manifest, mirror_verified_backup
from backup_verification import database_state, snapshot_profile, write_verification
from backup_merlin import DEFAULT_BACKUP_ROOT

class RecoveryBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'backup';self.source.mkdir()
        self.drive = self.root/'drive';self.drive.mkdir()
        (self.source/'data.txt').write_text('original')
        write_verification(self.source,'FULL',{})

    def test_default_backup_follows_project_parent(self):
        self.assertEqual(DEFAULT_BACKUP_ROOT,Path(__file__).resolve().parents[2]/'Merlin_Backups')

    def test_absent_drive_does_not_block_local_backup(self):
        missing = self.root/'absent'
        result = mirror_verified_backup(self.source,missing,'FULL')
        self.assertEqual(result['status'],'unavailable')
        self.assertFalse(missing.exists())

    def test_exact_copy_and_latest_only_replacement(self):
        (self.drive/'unrelated.txt').write_text('keep')
        result = mirror_verified_backup(self.source,self.drive,'FULL')
        target = Path(result['path'])
        self.assertEqual((target/'data.txt').read_text(),'original')
        (self.source/'data.txt').write_text('new')
        (self.source/'FILE_HASHES.json').unlink();(self.source/'VERIFICATION.json').unlink()
        write_verification(self.source,'FULL',{})
        mirror_verified_backup(self.source,self.drive,'FULL')
        self.assertEqual((target/'data.txt').read_text(),'new')
        self.assertEqual(sorted(p.name for p in self.drive.iterdir()),['ChessWizard_LATEST_FULL','unrelated.txt'])

    def test_unknown_target_is_preserved(self):
        target=self.drive/'ChessWizard_LATEST_FULL';target.mkdir()
        (target/'owner.txt').write_text('keep')
        before=manifest(target)
        with self.assertRaises((ValueError,FileNotFoundError)):
            mirror_verified_backup(self.source,self.drive,'FULL')
        self.assertEqual(manifest(target),before)

    def test_changed_backup_cannot_replace_previous(self):
        result=mirror_verified_backup(self.source,self.drive,'FULL');target=Path(result['path'])
        before=manifest(target)
        (self.source/'data.txt').write_text('unverified')
        with self.assertRaises(ValueError):mirror_verified_backup(self.source,self.drive,'FULL')
        self.assertEqual(manifest(target),before)

    def test_copy_failure_keeps_previous(self):
        target=Path(mirror_verified_backup(self.source,self.drive,'FULL')['path']);before=manifest(target)
        with patch('backup_recovery.shutil.copytree',side_effect=OSError('media removed')):
            with self.assertRaises(OSError):mirror_verified_backup(self.source,self.drive,'FULL')
        self.assertEqual(manifest(target),before)

    def test_low_space_keeps_previous(self):
        target=Path(mirror_verified_backup(self.source,self.drive,'FULL')['path']);before=manifest(target)
        with patch('backup_recovery.shutil.disk_usage') as usage:
            usage.return_value.free=0
            with self.assertRaises(OSError):mirror_verified_backup(self.source,self.drive,'FULL')
        self.assertEqual(manifest(target),before)

    def test_nested_mirror_and_wrong_mode_rejected(self):
        child=self.source/'child';child.mkdir()
        with self.assertRaises(ValueError):mirror_verified_backup(self.source,child,'FULL')
        with self.assertRaises(ValueError):mirror_verified_backup(self.source,self.drive,'QUICK')

    def test_profile_database_and_book_are_logically_verified(self):
        profile=self.root/'profile';profile.mkdir()
        for name in ('merlin.db','book.cwbook'):
            with closing(sqlite3.connect(profile/name)) as db:
                db.execute('CREATE TABLE sample(id INTEGER PRIMARY KEY,value TEXT)')
                db.execute("INSERT INTO sample VALUES(1,'protected')")
                db.commit()
        (profile/'settings.json').write_text('{"theme":"default"}')
        before=manifest(profile)
        records=snapshot_profile(profile,self.root/'profile-backup')
        self.assertEqual(len(records),3)
        self.assertEqual(manifest(profile),before)
        self.assertEqual(database_state(profile/'merlin.db'),database_state(self.root/'profile-backup/merlin.db'))

    def test_corrupted_staged_copy_does_not_replace_previous(self):
        import shutil
        target=Path(mirror_verified_backup(self.source,self.drive,'FULL')['path']);before=manifest(target)
        original=shutil.copytree
        def corrupt(source,dest):
            original(source,dest);(dest/'data.txt').write_text('corrupted')
        with patch('backup_recovery.shutil.copytree',side_effect=corrupt):
            with self.assertRaises(ValueError):mirror_verified_backup(self.source,self.drive,'FULL')
        self.assertEqual(manifest(target),before)
