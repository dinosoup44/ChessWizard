"""ID-preserving conservative outcome storage, separate from tactic conclusions."""
from collections.abc import Mapping
from dataclasses import asdict, dataclass
import json
import sqlite3
from threading import Event
from typing import Any, TYPE_CHECKING
from analysis_completion import CompletionState, assess_preflight_completion
from analysis_control import check_cancelled
from analysis_deferred_schema import deferred_schema_available
from analysis_deferred_evidence import canonical_json, deferred_dependencies, fingerprint
from analysis_preflight import PreflightContext
from existing_position_evidence import ExistingPositionEvidence
from solution_ownership import SolutionOwnershipService
from sqlite_transaction import SqliteTransaction
if TYPE_CHECKING:
    from analysis_registry import AnalyzerDefinition

CONTRACT_VERSION = 1


@dataclass(frozen=True)
class DeferredWrite:
    """Describe ledger persistence without claiming a tactic result.

    Args:
        action: inserted, updated, unchanged, unavailable, ineligible or protected.
        completed: Whether this exact obligation has a durable receipt.
    """
    action: str
    completed: bool = False


class DeferredCheckRepository:
    """Read and persist proven stable receipts through explicit registry opt-in.

    Args:
        connection: Caller-owned connection; no schema is created here.
    """
    def __init__(self, connection: sqlite3.Connection) -> None:
        """Bind an optional ledger without migrations or engine access.

        Args:
            connection: Connection used by the caller's scoped transaction.
        """
        self.connection = connection
        self.available = deferred_schema_available(connection)

    def _contract(self, definition: 'AnalyzerDefinition') -> dict[str, Any]:
        if definition.deferred_contract is None or definition.preflight_existing_evidence is None:
            raise ValueError('Analyzer has not opted into durable preflight completion')
        return {'version':CONTRACT_VERSION, 'analysis_type':definition.analysis_type,
                'screener_version':definition.screener_version, 'scout_version':definition.scout_version,
                'scout_config':definition.scout_config(), 'analyzer_version':definition.analyzer_version,
                'preflight':definition.deferred_contract()}

    def _protected(self, move_id: int, analysis_type: str) -> bool:
        db = self.connection
        return bool(db.execute('SELECT 1 FROM tactic_candidates WHERE move_id=? AND tactic_type=?',
                               (move_id, analysis_type)).fetchone() or db.execute(
            "SELECT 1 FROM analysis_coverage WHERE move_id=? AND analysis_type=? AND "
            "(candidate_id IS NOT NULL OR coverage_status IN ('candidate','rejected','analyzed_no_hit'))",
            (move_id, analysis_type)).fetchone())

    def _row(self, move_id: int, analysis_type: str) -> sqlite3.Row | None:
        cursor = self.connection.cursor()
        cursor.row_factory = sqlite3.Row
        return cursor.execute('SELECT * FROM analysis_deferred_checks WHERE move_id=? AND analysis_type=?',
                              (move_id, analysis_type)).fetchone()

    def is_current(self, definition: 'AnalyzerDefinition', move: Mapping[str, Any] | sqlite3.Row) -> bool:
        """Check a receipt against current policy and raw dependencies only.

        Args:
            definition: Current opt-in analyzer contract.
            move: Exact stored move being considered.

        Returns:
            True for a valid current conservative receipt; False for absent,
            stale, corrupt, unregistered or protected obligations. No proof runs.

        Raises:
            sqlite3.Error: Database reads failed; unsafe failures are not hidden.
        """
        if not self.available or definition.deferred_contract is None:
            return False
        row = self._row(move['move_id'], definition.analysis_type)
        if row is None or self._protected(move['move_id'], definition.analysis_type):
            return False
        try:
            contract = json.loads(row['contract_json'])
            dependencies = json.loads(row['dependency_json'])
            record = json.loads(row['details_json'])
            if (row['contract_version'] != CONTRACT_VERSION or row['completion_state'] != 'complete_deferred'
                    or contract != self._contract(definition)
                    or row['disposition'] != record['disposition'] or row['reason_code'] != record['reason']
                    or record['move_id'] != move['move_id'] or record['analysis_type'] != definition.analysis_type
                    or assess_preflight_completion(record['disposition'], record['reason']).state != CompletionState.COMPLETE_DEFERRED):
                return False
            return (row['receipt_sha256'] == fingerprint([contract, dependencies, record])
                    and dependencies == deferred_dependencies(self.connection, move, record))
        except (ValueError, KeyError, TypeError, IndexError):
            return False

    def save(self, definition: 'AnalyzerDefinition', move: Mapping[str, Any] | sqlite3.Row,
             record: Mapping[str, Any], allowed_keys: set[tuple[int, str]], *,
             cancel: Event | None = None) -> DeferredWrite:
        """Persist only a successfully rechecked stable predicate, atomically.

        Args:
            definition: Explicitly registered durable-completion contract.
            move: Specific authorized stored user move.
            record: Full preflight disposition, exact reason and provenance.
            allowed_keys: Authorized move/analyzer scope.
            cancel: Stop signal; checked before writing and before committing.

        Returns:
            Insert/update/reuse outcome, or a non-writing eligibility decision.

        Raises:
            ValueError: Scope, provenance or input identity changed.
            AnalysisCancelled: Stop was requested; this unit is rolled back.
            sqlite3.Error: Persistence failed; the active transaction rolls back.
        """
        check_cancelled(cancel)
        key = (move['move_id'], definition.analysis_type)
        if key not in allowed_keys:
            raise ValueError('Deferred check is outside the authorized scope')
        if not self.available:
            return DeferredWrite('unavailable')
        if (definition.deferred_contract is None or assess_preflight_completion(
                record.get('disposition', ''), record.get('reason', '')).state != CompletionState.COMPLETE_DEFERRED):
            return DeferredWrite('ineligible')
        if (record.get('move_id'), record.get('analysis_type')) != key:
            raise ValueError('Deferred record identity does not match the obligation')
        with SqliteTransaction(self.connection, cancel):
            if self._protected(*key):
                return DeferredWrite('protected')
            if self.is_current(definition, move):
                return DeferredWrite('unchanged', True)
            contract = self._contract(definition)
            # Recheck the complete approved predicate under the write transaction.
            # A label or an interrupted/provisional planner result is insufficient.
            result = definition.preflight_existing_evidence(move, PreflightContext(
                definition.analysis_type, definition.analyzer_version, ExistingPositionEvidence(self.connection),
                SolutionOwnershipService(self.connection)))
            fresh = {'move_id':key[0], 'analysis_type':key[1], **asdict(result)}
            if fresh != record or self._contract(definition) != contract:
                raise ValueError('Deferred predicate or policy changed before persistence')
            dependencies = deferred_dependencies(self.connection, move, record)
            check_cancelled(cancel)
            previous = self._row(*key)
            self.connection.execute("""INSERT INTO analysis_deferred_checks
                (move_id,analysis_type,completion_state,disposition,reason_code,contract_version,
                 contract_json,dependency_json,details_json,receipt_sha256)
                VALUES(?,?,'complete_deferred',?,?,?,?,?,?,?)
                ON CONFLICT(move_id,analysis_type) DO UPDATE SET
                  completion_state=excluded.completion_state, disposition=excluded.disposition,
                  reason_code=excluded.reason_code, contract_version=excluded.contract_version,
                  contract_json=excluded.contract_json, dependency_json=excluded.dependency_json,
                  details_json=excluded.details_json, receipt_sha256=excluded.receipt_sha256,
                  checked_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP""",
                (*key, record['disposition'], record['reason'], CONTRACT_VERSION,
                 canonical_json(contract), canonical_json(dependencies), canonical_json(record),
                 fingerprint([contract, dependencies, record])))
            check_cancelled(cancel)
            return DeferredWrite('updated' if previous else 'inserted', True)
