"""Opt-in translation of supplied legacy rows; no repositories or analyzer calls."""
from dataclasses import dataclass
from typing import Mapping

from position_range_evidence import LegalReplay

from tactic_occurrences import OccurrenceKind, TacticColor, TacticOccurrence


_LEGACY_MOTIFS = {
    "missed_fork": "fork", "missed_pin": "pin", "missed_skewer": "skewer",
    "missed_xray": "xray", "missed_mate": "mate",
}


@dataclass(frozen=True)
class OccurrenceAdaptation:
    occurrence: TacticOccurrence | None
    reason: str


def occurrence_from_legacy_candidate(
    row: Mapping, *, perspective_color: TacticColor | None,
) -> OccurrenceAdaptation:
    """Map explicit stored missed claims without deriving proof or user perspective.

    Only known candidate vocabularies are accepted. Equal moves in a missed row
    are contradictory legacy data, not permission to invent a played tactic.
    Stored SAN proof is referenced, never relabeled as actual game history.
    """
    data = dict(row)
    legacy_type = data.get("tactic_type")
    motif = _LEGACY_MOTIFS.get(legacy_type) if isinstance(legacy_type, str) else None
    if motif is None:
        return OccurrenceAdaptation(None, "unsupported_legacy_tactic_type")
    if data.get("candidate_status") not in ("candidate", "confirmed"):
        return OccurrenceAdaptation(None, "unsupported_source_verdict")
    if any(type(data.get(key)) is not int or data[key] <= 0 for key in ("candidate_id", "move_id", "game_id")):
        return OccurrenceAdaptation(None, "missing_or_invalid_source_identity")
    if not all(isinstance(data.get(key), str) and data[key].strip()
               for key in ("fen_before", "color", "uci_played", "solution_move_uci")):
        return OccurrenceAdaptation(None, "missing_decision_evidence")
    if data["uci_played"] == data["solution_move_uci"]:
        return OccurrenceAdaptation(None, "legacy_missed_move_was_played")
    identity = f"candidate:{data['candidate_id']}"
    try:
        actual = LegalReplay(data["fen_before"], (data["uci_played"],))
        actor = TacticColor.WHITE if actual.board_at(0).turn else TacticColor.BLACK
        if TacticColor(data["color"]) != actor:
            return OccurrenceAdaptation(None, "actor_disagrees_with_decision_position")
        LegalReplay(data["fen_before"], (data["solution_move_uci"],))
        occurrence = TacticOccurrence(
            motif, identity, kind=OccurrenceKind.MISSED,
            actor_color=TacticColor(data["color"]), perspective_color=perspective_color,
            source_position=data["fen_before"], actual_move=data["uci_played"],
            tactical_move=data["solution_move_uci"], actual_game_line=(data["uci_played"],),
            counterfactual_line=(data["solution_move_uci"],),
            proof_source_identity=f"{identity}/solution_line" if data.get("solution_line") else None,
            candidate_id=data["candidate_id"], source_verdict=data["candidate_status"],
            provenance=(("game_id", str(data["game_id"])), ("move_id", str(data["move_id"])),
                        ("legacy_tactic_type", data["tactic_type"]),
                        ("detector_version", str(data.get("detector_version", "unknown")))),
        )
    except (TypeError, ValueError):
        return OccurrenceAdaptation(None, "invalid_decision_evidence")
    return OccurrenceAdaptation(occurrence, "mapped_legacy_missed_claim")
