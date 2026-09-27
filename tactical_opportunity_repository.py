"""Generic opportunity storage codec and read view over existing candidates.

Writes remain in heavy_repository's authorized, atomic candidate/coverage
transaction. This module never commits, creates tables, or runs analysis.
"""
from dataclasses import dataclass, replace
import json

from tactical_opportunities import (
    TacticalOpportunity, opportunity_from_dict, opportunity_to_dict,
)


METADATA_KEY = "tactical_opportunity"
CANONICAL_PROOF_FIELDS = {
    "played_move_uci": "uci_played",
    "tactical_move_uci": "solution_move_uci",
    "line_san": "solution_line",
}


def _metadata(raw):
    value = json.loads(raw) if raw else {}
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Candidate metadata must be a JSON object")
    return value


def _compact(value):
    if isinstance(value, dict):
        return {k: v if k == "metadata" else _compact(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_compact(v) for v in value]
    return value


def prepare_opportunity_payload(payload, opportunity, move, existing=None):
    """Return a detached payload; preserve canonical ID and unrelated metadata.

Legacy results without an opportunity retain their exact old storage behavior
unless a previously stored opportunity needs protection from silent erasure.
"""
    previous_raw = existing["metadata_json"] if existing is not None else None
    # Avoid even parsing legacy metadata when no new envelope is involved.
    if opportunity is None and METADATA_KEY not in (previous_raw or "") and METADATA_KEY not in (payload.get("metadata_json") or ""):
        return dict(payload)
    previous = _metadata(previous_raw)
    incoming = _metadata(payload.get("metadata_json"))
    old_document = previous.get(METADATA_KEY)
    if METADATA_KEY in incoming and incoming[METADATA_KEY] != old_document:
        raise ValueError("Supply opportunities through HeavyResult.opportunity")
    if opportunity is None:
        if old_document is None:
            return dict(payload)
        identity = ("detector_version", "solution_move_uci", "solution_line")
        if any(str(payload.get(k)) != str(existing[k]) for k in identity):
            raise ValueError("Changed proof/version requires an explicit replacement opportunity")
        document = old_document
    else:
        document = opportunity_to_dict(opportunity)
        context = {**dict(move), **payload}
        for proof_field, source_field in CANONICAL_PROOF_FIELDS.items():
            supplied = document["proof"].pop(proof_field)
            if supplied is not None and supplied != context.get(source_field):
                raise ValueError(f"Opportunity {proof_field} disagrees with canonical evidence")
        document = _compact(document)
    combined = {**previous, **incoming, METADATA_KEY: document}
    return {**payload, "metadata_json": json.dumps(combined, sort_keys=True, allow_nan=False)}


@dataclass(frozen=True)
class CandidateOpportunity:
    """Read-only consumer contract; absent legacy conclusions remain None."""
    candidate_id: int
    move_id: int
    tactic_type: str
    candidate_status: str
    played_move_uci: str | None
    tactical_move_uci: str | None
    tactical_move_san: str | None
    proof_line_san: str | None
    opportunity: TacticalOpportunity | None


def read_candidate_opportunity(connection, candidate_id):
    """Read one candidate without backfill, inference, engine access, or writes.

Works with both default sqlite tuples and sqlite.Row connections. None means
the candidate does not exist; a legacy candidate has opportunity=None.
"""
    cursor = connection.execute(
        "SELECT c.candidate_id,c.move_id,c.tactic_type,c.candidate_status,"
        "c.solution_move_uci,c.solution_move_san,c.solution_line,c.metadata_json,m.uci_played "
        "FROM tactic_candidates c JOIN moves m ON m.move_id=c.move_id WHERE c.candidate_id=?",
        (candidate_id,))
    row = cursor.fetchone()
    if row is None:
        return None
    row = dict(zip((column[0] for column in cursor.description), row))
    document = _metadata(row["metadata_json"]).get(METADATA_KEY)
    opportunity = opportunity_from_dict(document) if document is not None else None
    if opportunity is not None:
        context = {field: row[source] for field, source in CANONICAL_PROOF_FIELDS.items()}
        for field, value in context.items():
            if getattr(opportunity.proof, field) not in (None, value):
                raise ValueError("Stored opportunity conflicts with canonical evidence")
        opportunity = replace(opportunity, proof=replace(opportunity.proof, **context))
    return CandidateOpportunity(
        row["candidate_id"], row["move_id"], row["tactic_type"], row["candidate_status"],
        row["uci_played"], row["solution_move_uci"], row["solution_move_san"], row["solution_line"], opportunity)
