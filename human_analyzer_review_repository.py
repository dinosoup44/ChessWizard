"""Atomic insert/update of a small JSONL QA file, independent of SQLite and engines."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from application_paths import resolve_review_path
from human_analyzer_reviews import HumanReviewCase, HumanReviewRecord, ReviewVerdict

DEFAULT_REVIEW_PATH = Path(__file__).parent / "reviews" / "human_analyzer_review.jsonl"
MAX_REVIEW_FILE_BYTES = 8 * 1024 * 1024


class ReviewStorageError(Exception):
    """The file could not be read or safely replaced; existing data is retained."""


class HumanReviewRepository:
    def __init__(self, path: Path | None = None, *, database_path=None):
        self.path = Path(path) if path is not None else resolve_review_path(database_path)

    def load(self) -> tuple[HumanReviewRecord, ...]:
        """Missing files are empty. Malformed files are never partially accepted."""
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_REVIEW_FILE_BYTES + 1)
            if len(raw) > MAX_REVIEW_FILE_BYTES:
                raise ValueError("Review file exceeds the local QA size limit")
            records = tuple(HumanReviewRecord.from_dict(json.loads(line))
                            for line in raw.decode("utf-8").splitlines() if line.strip())
            if len({r.case.identity for r in records}) != len(records):
                raise ValueError("Duplicate review identities in file")
            return records
        except FileNotFoundError:
            return ()
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
            raise ReviewStorageError(f"Cannot read human reviews: {exc}. File left unchanged.") from exc

    @staticmethod
    def _check_identity(record: HumanReviewRecord, case: HumanReviewCase) -> None:
        if (record.case.game_id, record.case.move_id, record.case.tactic_type) != (case.game_id, case.move_id, case.tactic_type):
            raise ReviewStorageError("Review identity conflicts with its saved game/move/tactic. File left unchanged.")

    def get(self, case: HumanReviewCase) -> HumanReviewRecord | None:
        """Reload the current judgment and verify its canonical move association."""
        record = next((r for r in self.load() if r.case.identity == case.identity), None)
        if record:
            self._check_identity(record, case)
        return record

    def save(self, case: HumanReviewCase, verdict: ReviewVerdict, note: str = "") -> HumanReviewRecord:
        """One current record per review target. Identical saves do not churn timestamps."""
        record = HumanReviewRecord(case, verdict, note.strip(), datetime.now(timezone.utc).isoformat())
        lock_path = self.path.with_name(self.path.name + ".lock")
        locked = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                lock = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError as exc:
                raise ReviewStorageError("Review file is busy. Retry after the other save finishes; a leftover lock requires inspection.") from exc
            locked = True
            os.close(lock)
            records = {r.case.identity: r for r in self.load()}
            old = records.get(case.identity)
            if old:
                self._check_identity(old, case)
                if old.case == case and old.verdict == verdict and old.note == record.note:
                    return old
            records[case.identity] = record
            payload = "".join(json.dumps(r.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
                              for _, r in sorted(records.items()))
            if len(payload.encode("utf-8")) > MAX_REVIEW_FILE_BYTES:
                raise ReviewStorageError("Review file would exceed the local QA size limit")
            self._replace(payload)
            return record
        except OSError as exc:
            raise ReviewStorageError(f"Could not save human review: {exc}") from exc
        finally:
            if locked:
                try:
                    lock_path.unlink(missing_ok=True)
                except OSError as exc:
                    raise ReviewStorageError("Review save may have completed, but its lock could not be removed. Reload and inspect the lock before retrying.") from exc

    def _replace(self, payload: str) -> None:
        # Same-directory replacement avoids a partially written current file.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                             dir=self.path.parent, prefix=self.path.name + ".", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
