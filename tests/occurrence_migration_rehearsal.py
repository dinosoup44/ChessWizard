"""Scratch-only rehearsal support; deliberately not a production migration API."""
from collections import Counter
from contextlib import closing, contextmanager
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

from position_range_evidence import LegalReplay
from tactic_occurrence_adapters import occurrence_from_legacy_candidate
from tactic_occurrence_storage import OccurrenceEvidence, OccurrenceKey, NamedOccurrenceKey, LegacyDecisionReference, TacticOccurrenceRecord, canonical_json
from tactic_occurrences import OccurrenceKind, TacticColor
from tests.occurrence_storage_prototype import MemoryOccurrenceStore, SCHEMA


OCCURRENCE_TABLES = frozenset(("tactic_occurrences", "tactic_occurrence_evidence",
    "tactic_occurrence_lines", "tactic_occurrence_legacy_candidates", "tactic_occurrence_review_links"))
LEGACY_SELECT = """SELECT tc.*,m.game_id,m.ply_number,m.fen_before,m.color,m.uci_played,
    m.is_user_move,g.user_color,g.source,g.source_game_id
    FROM tactic_candidates tc LEFT JOIN moves m ON m.move_id=tc.move_id
    LEFT JOIN games g ON g.game_id=m.game_id ORDER BY tc.candidate_id"""


def table_fingerprints(connection, tables=None):
    """Logical content fingerprints for unchanged copied tables, including row IDs."""
    names = tables if tables is not None else [r[0] for r in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    result = {}
    for name in names:
        quoted = '"' + name.replace('"', '""') + '"'
        digest = hashlib.sha256()
        count = 0
        for row in connection.execute(f"SELECT * FROM {quoted}"):
            encoded = [dict(blob_hex=x.hex()) if isinstance(x, bytes) else x for x in row]
            digest.update((canonical_json(encoded)+'\n').encode())
            count += 1
        result[name] = dict(count=count, sha256=digest.hexdigest())
    return result


class ScratchOccurrenceStore(MemoryOccurrenceStore):
    """Always copies a read-only source into an owned TemporaryDirectory.

    No caller can supply a write destination or an existing writable connection.
    After schema creation an authorizer allows inserts only into the five new
    tables. Source tables are never altered, even in scratch.
    """
    def __init__(self, source: Path):
        self.source = Path(source).resolve(strict=True)
        self._temporary = TemporaryDirectory(prefix="chesswizard_occurrence_rehearsal_")
        self.path = Path(self._temporary.name) / "rehearsal.db"
        self.namespace = str(uuid4())
        self._history = {}
        self.timings = {}
        self.connection = None
        try:
            self.connection = sqlite3.connect(self.path)
            start = perf_counter()
            with closing(sqlite3.connect(self.source.as_uri()+"?mode=ro", uri=True)) as original:
                original.execute("PRAGMA query_only=ON")
                original.backup(self.connection)
            self.timings['copy_seconds'] = perf_counter()-start
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys=ON")
            if self.connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Scratch backup integrity failed")
            self.copy_foreign_keys = [list(r) for r in self.connection.execute("PRAGMA foreign_key_check")]
            if self.copy_foreign_keys:
                raise ValueError("Source copy has foreign-key violations")
            (self.path.parent/'lineage.json').write_text(canonical_json({
                'source_namespace':self.namespace, 'source':str(self.source),
                'scope':'rehearsal_only; never production lineage allocation'}),encoding='utf-8')
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        self._temporary.cleanup()

    @contextmanager
    def transaction(self):
        """One explicit atomic rehearsal unit; callers decide the unit's scope."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def apply_schema(self):
        existing = {r[0] for r in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if existing & OCCURRENCE_TABLES:
            if not OCCURRENCE_TABLES <= existing:
                raise ValueError("Partial occurrence schema")
            self.validate_schema()
            return False
        start = perf_counter()
        with self.transaction():
            for statement in SCHEMA.split(';'):
                if statement.strip():
                    index_start = perf_counter()
                    self.connection.execute(statement)
                    if statement.strip().startswith('CREATE INDEX'):
                        self.timings['index_creation_seconds'] = perf_counter()-index_start
        self.timings['schema_creation_seconds'] = perf_counter()-start
        self.validate_schema()
        self.connection.set_authorizer(self._authorize)
        return True

    def validate_schema(self):
        for statement in SCHEMA.split(';'):
            if not statement.strip():
                continue
            name = statement.strip().split()[2]
            row = self.connection.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
            if row is None or ' '.join(row[0].split()) != ' '.join(statement.split()):
                raise ValueError(f"Schema differs from contract: {name}")

    @staticmethod
    def _authorize(action, name, other, database, trigger):
        if action == sqlite3.SQLITE_INSERT:
            return sqlite3.SQLITE_OK if name in OCCURRENCE_TABLES else sqlite3.SQLITE_DENY
        if action in (sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE, sqlite3.SQLITE_DROP_TABLE,
                      sqlite3.SQLITE_DROP_INDEX, sqlite3.SQLITE_ALTER_TABLE,
                      sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH, sqlite3.SQLITE_CREATE_TABLE,
                      sqlite3.SQLITE_CREATE_TRIGGER):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def _insert_once(self, table, key, values):
        if not self.connection.in_transaction:
            raise ValueError("Rehearsal writes require an explicit transaction")
        columns = tuple(values)
        row = self.connection.execute(f"SELECT {','.join(columns)} FROM {table} WHERE {key}=?",
            (values[key],)).fetchone()
        if row is not None:
            if tuple(row) != tuple(values.values()):
                raise ValueError("Immutable storage identity conflict")
            return False
        self.connection.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            tuple(values.values()))
        return True

    def _bind_history(self, record, count):
        if isinstance(record.key, NamedOccurrenceKey):
            source = self.connection.execute("SELECT source,source_game_id FROM games WHERE game_id=?",
                (record.game_id,)).fetchone()
            if source is None or tuple(source) != (record.key.source, record.key.source_game_id):
                raise ValueError("Named identity does not match persisted source")
        rows = list(self.connection.execute("SELECT ply_number,fen_before,uci_played FROM moves "
            "WHERE game_id=? AND ply_number>=? ORDER BY ply_number LIMIT ?",
            (record.game_id, record.decision_ply, count)))
        anchor = self.connection.execute("SELECT game_id,ply_number FROM moves WHERE move_id=?",
            (record.move_id,)).fetchone()
        if anchor is None or tuple(anchor) != (record.game_id, record.decision_ply):
            raise ValueError("Move/game anchor mismatch")
        if not rows or rows[0]['fen_before'] != record.decision_fen:
            raise ValueError("Decision FEN mismatch")
        if [r['ply_number'] for r in rows] != list(range(record.decision_ply, record.decision_ply+count)):
            raise ValueError("Incomplete contiguous actual history")
        moves = tuple(r['uci_played'] for r in rows)
        LegalReplay(record.decision_fen, moves)
        self._history[(record.key.source_namespace, record.game_id, record.move_id)] = (
            record.decision_ply, record.decision_fen, moves)

    def add_occurrence(self, record):
        self._bind_history(record, 1)
        return super().add_occurrence(record)

    def add_line(self, line):
        row = self.connection.execute("SELECT * FROM tactic_occurrences WHERE occurrence_id=?", (line.occurrence_id,)).fetchone()
        if row is None:
            raise ValueError("Missing line occurrence")
        record = self._record(row)
        self._bind_history(record, len(line.moves_uci) if line.line_type == 'actual' else 1)
        return super().add_line(line)


# Explicitly audited named fixture sources; never infer legitimacy from a negative ID.
NAMED_LEGACY_SOURCES = frozenset({("dev", "MERLIN_TEST_ROOK_FORK")})


def named_legacy_record(row, namespace):
    """Import an explicitly identified persisted developer puzzle, without reseeding it."""
    if (row.get('source'), row.get('source_game_id')) not in NAMED_LEGACY_SOURCES:
        return None
    metadata = json.loads(row.get('metadata_json') or '{}')
    if metadata.get('developer_test') is not True or metadata.get('detector') != 'developer_test':
        return None
    if row.get('candidate_status') != 'candidate' or row.get('tactic_type') != 'missed_fork':
        return None
    if any(type(row.get(k)) is not int or row[k] == 0 for k in ('candidate_id','game_id','move_id')):
        return None
    actual = LegalReplay(row['fen_before'], (row['uci_played'],))
    actor = TacticColor.WHITE if actual.board_at(0).turn else TacticColor.BLACK
    if actor != row['color'] or row['uci_played'] == row['solution_move_uci']:
        return None
    LegalReplay(row['fen_before'], (row['solution_move_uci'],))
    key = NamedOccurrenceKey(namespace, row['source'], row['source_game_id'], row['ply_number'],
        OccurrenceKind.MISSED, actor, 'fork', row['solution_move_uci'])
    reference = LegacyDecisionReference(row['game_id'], row['move_id'])
    return TacticOccurrenceRecord(key, row['ply_number'], row['fen_before'], row['uci_played'], reference)


def legacy_record(row, namespace):
    """Preserve unsupported rejected claims as UNKNOWN, never as accepted tactics.

    The active legacy adapter is unchanged. UNKNOWN is permitted only when all
    immutable anchors/root legality are independently available; bad/missing IDs
    or contradictory source data are reported, never repaired with fake IDs.
    """
    if (row.get('source'), row.get('source_game_id')) in NAMED_LEGACY_SOURCES:
        named = named_legacy_record(row, namespace)
        return (named, 'mapped_named_developer_puzzle') if named else (None, 'unproven_named_source')
    perspective = row['user_color'] if row['user_color'] in ('white','black') else None
    adaptation = occurrence_from_legacy_candidate(row, perspective_color=perspective)
    supplied = adaptation.occurrence
    if supplied is None and adaptation.reason != 'unsupported_source_verdict':
        return None, adaptation.reason
    if supplied is None:
        if row['candidate_status'] != 'rejected':
            return None, adaptation.reason
        actual = LegalReplay(row['fen_before'], (row['uci_played'],))
        actor = TacticColor.WHITE if actual.board_at(0).turn else TacticColor.BLACK
        if actor != row['color']:
            raise ValueError('Source actor mismatch')
        LegalReplay(row['fen_before'], (row['solution_move_uci'],))
        motif = row['tactic_type'].removeprefix('missed_')
        kind = OccurrenceKind.UNKNOWN
    else:
        actor, motif, kind = supplied.actor_color, supplied.motif_type, supplied.kind
    key = OccurrenceKey(namespace, row['game_id'], row['move_id'], kind, actor, motif, row['solution_move_uci'])
    return TacticOccurrenceRecord(key, row['ply_number'], row['fen_before'], row['uci_played']), adaptation.reason


def migrate_legacy(store):
    """Attempt every candidate, preserve undecoded evidence, insert all valid links atomically."""
    start = perf_counter()
    results = []
    insert_counts = Counter()
    identity_seconds = 0
    with store.transaction():
        for source in store.connection.execute(LEGACY_SELECT).fetchall():
            row = dict(source)
            identity_start = perf_counter()
            try:
                record, reason = legacy_record(row, store.namespace)
            except (ValueError, TypeError, KeyError) as error:
                record, reason = None, f'invalid_archive_anchor:{type(error).__name__}:{error}'
            identity_seconds += perf_counter()-identity_start
            item = dict(candidate_id=row['candidate_id'], source_status=row['candidate_status'],
                game_id=row['game_id'], move_id=row['move_id'], adapter_reason=reason)
            if record is None:
                results.append(dict(item, mapped=False, relation='unmappable'))
                continue
            coverage = [dict(r) for r in store.connection.execute(
                'SELECT * FROM analysis_coverage WHERE move_id=? AND analysis_type=?',
                (row['move_id'],row['tactic_type']))]
            payload = canonical_json({'legacy_candidate':row, 'legacy_coverage':coverage,
                'adaptation_reason':reason, 'facet_decoding':'deferred; raw source preserved verbatim',
                'activation':'none; archival claim only'})
            evidence = OccurrenceEvidence(record.occurrence_id, 'legacy:'+row['tactic_type'],
                str(row['detector_version']), 'legacy_archive_snapshot_v1', f"candidate:{row['candidate_id']}",
                row['user_color'] if row['user_color'] in ('white','black') else None,
                'not_decoded','not_decoded','not_decoded','not_decoded',payload)
            insert_counts['occurrences'] += store.add_occurrence(record)
            insert_counts['evidence'] += store.add_evidence(evidence)
            insert_counts['legacy_links'] += store.link_candidate(row['candidate_id'], record.occurrence_id)
            results.append(dict(item, mapped=True, occurrence_id=record.occurrence_id,
                revision_id=evidence.revision_id, relation=record.relationship(evidence.perspective_color),
                motif=record.key.motif_type))
    return dict(attempted=len(results), mapped=sum(r['mapped'] for r in results),
        insert_counts=dict(insert_counts), rows=results, relation_counts=dict(Counter(r['relation'] for r in results)),
        elapsed_seconds=perf_counter()-start, identity_and_adapter_seconds=identity_seconds)
