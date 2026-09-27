"""Typed local QA judgments. These records never participate in analyzer decisions."""
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from game_review_sets import ReviewSet
    from tactic_presentation import TacticalMoment

MAX_NOTE_LENGTH = 500


class ReviewVerdict(StrEnum):
    PASS = "PASS"
    WRONG_MOTIF = "WRONG MOTIF"
    WRONG_PAYOFF = "WRONG PAYOFF"
    WORDING = "WORDING"
    NOT_IMPORTANT = "NOT IMPORTANT"
    INVESTIGATE = "INVESTIGATE"


@dataclass(frozen=True)
class HumanReviewCase:
    """A canonical candidate or an explicitly namespaced audit-only QA anchor."""
    game_id: int
    move_id: int | None
    candidate_id: int | None
    tactic_type: str
    review_set: str
    review_reason: tuple[str, ...] = ()
    source_artifacts: tuple[str, ...] = ()
    analyzer_provenance: tuple[tuple[str, str], ...] = ()
    audit_case_id: str | None = None
    proposed_move: str | None = None
    move_number: int | None = None
    color: str | None = None
    review_reason_codes: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.game_id) is not int or self.game_id <= 0:
            raise ValueError("Review requires a positive game ID")
        for value in (self.move_id, self.candidate_id):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError("Stored move/candidate IDs must be positive or absent")
        if self.candidate_id is not None:
            if self.move_id is None or self.audit_case_id is not None:
                raise ValueError("Candidate reviews require a real move and no audit identity")
        elif not isinstance(self.audit_case_id, str) or not self.audit_case_id.strip():
            raise ValueError("Audit reviews require an explicit stable case ID")
        if self.move_number is not None and (type(self.move_number) is not int or self.move_number < 0):
            raise ValueError("Invalid review move number")
        if self.move_id is None and self.move_number != 0:
            raise ValueError("An unlocated audit case requires the non-chess move-zero anchor")
        if self.move_id is not None and self.move_number == 0:
            raise ValueError("Move zero cannot describe a real stored move")
        if self.proposed_move is not None and (not isinstance(self.proposed_move, str) or not self.proposed_move):
            raise ValueError("Invalid proposed move reference")
        if self.color not in (None, "white", "black"):
            raise ValueError("Invalid move color")
        if not isinstance(self.tactic_type, str) or not self.tactic_type:
            raise ValueError("Review requires a tactic type")
        if not isinstance(self.review_set, str) or not self.review_set:
            raise ValueError("Review requires a review-set identity")
        for values in (self.review_reason, self.source_artifacts, self.review_reason_codes):
            if not isinstance(values, tuple) or not all(isinstance(value, str) for value in values):
                raise ValueError("Review metadata must be immutable text tuples")
        if not isinstance(self.analyzer_provenance, tuple) or not all(
            isinstance(pair, tuple) and len(pair) == 2 and all(isinstance(v, str) for v in pair)
            for pair in self.analyzer_provenance
        ):
            raise ValueError("Invalid analyzer provenance")

    @property
    def identity(self) -> str:
        if self.candidate_id is not None:
            return f"candidate:{self.candidate_id}"
        # Structured encoding prevents delimiter collisions and excludes changing
        # labels, reasons and review-set membership from identity.
        return "audit:" + json.dumps([self.game_id, self.move_id, self.audit_case_id, self.proposed_move], separators=(",", ":"))

    @property
    def label(self) -> str:
        if self.candidate_id is not None:
            return f"Selected tactic · candidate {self.candidate_id}"
        anchor = (f"move {self.move_number or '?'} {self.color or ''}".strip()
                  if self.move_id is not None else "game-level anchor (not a chess move)")
        move_label = dict(self.analyzer_provenance).get("review_move_label", self.proposed_move)
        move = f" · {move_label}" if move_label else ""
        reasons = "; ".join(self.review_reason)
        return f"Audit · {anchor}{move} · {reasons or self.audit_case_id}"


def _entry_matches_moment(entry, moment):
    # Independent assessment anchors must not be merged into a stored candidate.
    if dict(entry.audit_metadata).get('independent_audit') == 'true':
        return False
    return (entry.candidate_id == moment.candidate_id or
            entry.proposed_move is not None and entry.move_id == moment.move_id and entry.proposed_move == moment.solution_uci)


def case_for_moment(moment: "TacticalMoment | None", review_set: "ReviewSet") -> HumanReviewCase | None:
    """Attach only exact matching audit provenance, never a nearby game's case."""
    if moment is None or review_set.audit_only:
        return None
    matches = tuple(e for e in review_set.entries_for_game(moment.game_id) if _entry_matches_moment(e, moment))
    return HumanReviewCase(moment.game_id, moment.move_id, moment.candidate_id,
                           moment.tactic_type, review_set.id,
                           tuple(dict.fromkeys(e.reason_label for e in matches)),
                           tuple(dict.fromkeys(e.source_artifact for e in matches)),
                           tuple(moment.feedback.provenance),
                           review_reason_codes=tuple(dict.fromkeys(e.reason_code for e in matches)))


def audit_cases_for_game(review_set: "ReviewSet", game_id: int, visible_moments=()) -> tuple[HumanReviewCase, ...]:
    """Group repeated shortlist reasons without inventing candidate identities."""
    grouped = {}
    for entry in review_set.entries_for_game(game_id):
        if any(_entry_matches_moment(entry, moment) for moment in visible_moments):
            continue
        if not entry.case_key:
            raise ValueError("Audit entry is missing its stable case key")
        key = (entry.source_artifact, entry.case_key, entry.move_id, entry.proposed_move)
        grouped.setdefault(key, []).append(entry)
    cases = []
    for (source, key, move_id, proposed), entries in grouped.items():
        first = entries[0]
        cases.append(HumanReviewCase(
            game_id, move_id, None, first.tactic_type or "unspecified", review_set.id,
            tuple(dict.fromkeys(e.reason_label for e in entries)),
            tuple(dict.fromkeys(e.source_artifact for e in entries)),
            analyzer_provenance=tuple(dict.fromkeys(pair for e in entries for pair in e.audit_metadata)),
            audit_case_id=f"{source}#{key}", proposed_move=proposed,
            move_number=first.move_number if move_id is not None else 0, color=first.color,
            review_reason_codes=tuple(dict.fromkeys(e.reason_code for e in entries))))
    return tuple(cases)


@dataclass(frozen=True)
class HumanReviewRecord:
    case: HumanReviewCase
    verdict: ReviewVerdict
    note: str
    reviewed_at: str
    schema_version: int = 1

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Unsupported human-review schema")
        if not isinstance(self.case, HumanReviewCase) or not isinstance(self.verdict, ReviewVerdict):
            raise ValueError("Invalid review case or verdict")
        if not isinstance(self.note, str) or len(self.note) > MAX_NOTE_LENGTH:
            raise ValueError(f"Note must contain at most {MAX_NOTE_LENGTH} characters")
        if not isinstance(self.reviewed_at, str) or datetime.fromisoformat(self.reviewed_at).utcoffset() is None:
            raise ValueError("Review timestamp must include its timezone")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "HumanReviewRecord":
        data = dict(payload)
        case = dict(data.pop("case"))
        for key in ("review_reason", "source_artifacts", "review_reason_codes"):
            values = case.get(key, [])
            if not isinstance(values, list):
                raise ValueError("Invalid review metadata list")
            case[key] = tuple(values)
        pairs = case.get("analyzer_provenance", [])
        if not isinstance(pairs, list) or not all(isinstance(pair, list) for pair in pairs):
            raise ValueError("Invalid provenance list")
        case["analyzer_provenance"] = tuple(tuple(pair) for pair in pairs)
        data["verdict"] = ReviewVerdict(data["verdict"])
        # A missing version is not permission to reinterpret an unknown format.
        if "schema_version" not in data:
            raise ValueError("Missing review schema version")
        return cls(case=HumanReviewCase(**case), **data)


def summarize_reviews(records: tuple[HumanReviewRecord, ...]) -> dict:
    """Count human judgments without assessing or changing analyzer quality."""
    counts = Counter(record.verdict.value for record in records)
    return {
        "reviewed_total": len(records),
        "verdicts": {verdict.value: counts[verdict.value] for verdict in ReviewVerdict},
        "by_tactic_type": dict(sorted(Counter(r.case.tactic_type for r in records).items())),
        "by_review_set": dict(sorted(Counter(r.case.review_set for r in records).items())),
        "by_relation": dict(sorted(Counter(dict(r.case.analyzer_provenance).get('relation', 'unspecified') for r in records).items())),
        "non_pass": [r.to_dict() for r in records if r.verdict != ReviewVerdict.PASS],
    }


def review_decision_step(moves, case: HumanReviewCase, *, game_id: int) -> int | None:
    """Resolve an audit's exact stored move; absent/unavailable anchors stay unlocated."""
    if game_id != case.game_id:
        raise ValueError("Audit case belongs to another game")
    if case.move_id is None:
        return None
    for index, move in enumerate(moves):
        if move["move_id"] == case.move_id:
            expected_fen = dict(case.analyzer_provenance).get("decision_fen")
            if expected_fen is not None and expected_fen != move["fen_before"]:
                raise ValueError("Audit position disagrees with the stored decision move")
            metadata = dict(case.analyzer_provenance)
            if metadata.get('actual_move_matches_tactical_move') == 'true' and metadata.get('played_move') != move['uci_played']:
                raise ValueError('Audit played move disagrees with the stored move')
            return index
    return None
