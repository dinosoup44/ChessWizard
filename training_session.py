"""Reusable lifetime guard for an active training attempt."""
from dataclasses import dataclass
from typing import Any
from data_activity import exclusive_data_activity
from training_history import start_attempt


class RemovedTrainingCandidate(ValueError):
    pass


@dataclass
class TrainingSession:
    attempt_id: int
    _activity: Any

    def close(self):
        if self._activity is not None:
            self._activity.__exit__(None, None, None)
            self._activity = None


def begin_training_session(connection, database_path, candidate_id, tactic_type, episode_id=None):
    """Lock before rechecking the candidate; no orphan attempt after another window deletes it."""
    activity = exclusive_data_activity(database_path)
    activity.__enter__()
    try:
        if not connection.execute("SELECT 1 FROM tactic_candidates WHERE candidate_id=?", (candidate_id,)).fetchone():
            raise RemovedTrainingCandidate("Puzzle was removed. Training refreshed.")
        connection.execute("PRAGMA foreign_keys=ON")
        attempt = start_attempt(connection, candidate_id, tactic_type, episode_id)
        return TrainingSession(attempt, activity)
    except Exception:
        activity.__exit__(None, None, None)
        raise
