"""Portable collection API with explicit paths, atomic metadata writes and no engines."""
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
from data_activity import exclusive_data_activity
from game_collection_models import CollectionDetails, valid_id
from game_collection_repository import GameCollectionRepository
from game_collection_schema import available


class GameCollectionService:
    def __init__(self, database_path):
        self.path = Path(database_path).resolve()

    def _connect(self, writable=False):
        db = sqlite3.connect(self.path.as_uri() + ("?mode=rw" if writable else "?mode=ro"), uri=True)
        db.execute("PRAGMA foreign_keys=ON")
        if not writable:
            db.execute("PRAGMA query_only=ON")
        return db

    @contextmanager
    def _write(self):
        with exclusive_data_activity(self.path), closing(self._connect(True)) as db:
            try:
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    yield GameCollectionRepository(db)
            except sqlite3.IntegrityError as error:
                raise ValueError("Collection name is already in use, or a referenced game no longer exists.") from error

    def available(self):
        with closing(self._connect()) as db:
            return available(db)

    def list_collections(self):
        with closing(self._connect()) as db:
            return GameCollectionRepository(db).list_collections()

    def members(self, collection_id):
        with closing(self._connect()) as db:
            db.execute("BEGIN")
            return GameCollectionRepository(db).members(valid_id(collection_id))

    def create(self, details: CollectionDetails) -> int:
        with self._write() as repo:
            return repo.create(details)

    def edit(self, collection_id, details: CollectionDetails):
        valid_id(collection_id)
        with self._write() as repo:
            return repo.edit(collection_id, details)

    def delete(self, collection_id):
        valid_id(collection_id)
        with self._write() as repo:
            repo.delete(collection_id)

    def _change_members(self, collection_id, game_ids, *, add):
        valid_id(collection_id)
        ids = tuple(dict.fromkeys(valid_id(game_id) for game_id in game_ids))
        with self._write() as repo:
            return repo.change_members(collection_id, ids, add=add)

    def add_games(self, collection_id, game_ids):
        return self._change_members(collection_id, game_ids, add=True)

    def remove_games(self, collection_id, game_ids):
        return self._change_members(collection_id, game_ids, add=False)
