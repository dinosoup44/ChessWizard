"""Stored legacy schemas only: no board inspection or analyzer imports."""
from dataclasses import dataclass
import re
from tactical_opportunities import Evaluation, ProofEvidence
from .models import FeedbackFact


PIECES = {1: "pawn", 2: "knight", 3: "bishop", 4: "rook", 5: "queen", 6: "king"}


def piece_label(value):
    if not isinstance(value, dict):
        return None
    piece = value.get("piece") or PIECES.get(value.get("piece_type"))
    square = value.get("square")
    if type(square) is int and 0 <= square < 64:
        # Decode the stored square index, not chess geometry.
        square = chr(97 + square % 8) + str(square // 8 + 1)
    if piece not in PIECES.values() or not isinstance(square, str) or not re.fullmatch(r"[a-h][1-8]", square):
        return None
    return f"{piece} on {square}"


@dataclass(frozen=True)
class LegacyEvidence:
    facts: tuple[FeedbackFact, ...] = ()
    proof: ProofEvidence | None = None
    recommended_move: str | None = None
    played_move: str | None = None
    proof_line: str | None = None


def _evaluation(value):
    if not isinstance(value, dict):
        return None
    cp, mate = value.get("cp"), value.get("mate")
    if type(cp) is int and mate is None:
        return Evaluation(cp=cp)
    if type(mate) is int and cp is None:
        return Evaluation(mate=mate)
    return None


def fork(metadata, player_color=None):
    facts = []
    targets = metadata.get("targets")
    if isinstance(targets, list):
        labels = tuple(dict.fromkeys(label for item in targets if (label := piece_label(item))))
        if len(labels) >= 2:
            facts.append(FeedbackFact("fork_targets", (("targets", " and ".join(labels)),), ("metadata_json.targets",)))
    realization = metadata.get("realization")
    if isinstance(realization, dict):
        won = piece_label({"piece": realization.get("won_piece"), "square": realization.get("won_square")})
        reply, capture = realization.get("opponent_reply"), realization.get("conversion_move")
        if won and isinstance(reply, str) and reply and isinstance(capture, str) and capture:
            facts.append(FeedbackFact("conversion", (("reply", reply), ("capture", capture), ("target", won)), ("metadata_json.realization",)))
    classification = metadata.get("outcome_classification")
    if isinstance(classification, str):
        facts.append(FeedbackFact("classification", (("classification", classification.replace("_", " ")),), ("metadata_json.outcome_classification",)))
    proof = None
    if metadata.get("detector") == "fork_v2_post_conversion" and player_color in {"white", "black"}:
        proof = ProofEvidence(score_pov=player_color,
            evaluation_before=_evaluation(metadata.get("evaluation_before")),
            evaluation_after_played=_evaluation(metadata.get("evaluation_after_played")),
            evaluation_after_tactic=_evaluation(metadata.get("evaluation_after_fork")))
        # Conversion is not necessarily a settled position; retain its actual
        # stage as a separate fact rather than relabeling it as settlement.
        conversion = _evaluation(metadata.get("evaluation_after_conversion"))
        if conversion:
            for kind in ("cp", "mate"):
                value = getattr(conversion, kind)
                if value is not None:
                    facts.append(FeedbackFact("evaluation_" + kind,
                        (("stage", "after-conversion"), ("value", str(value)), ("pov", player_color)),
                        ("metadata_json.evaluation_after_conversion",)))
    return LegacyEvidence(tuple(facts), proof=proof,
                          played_move=metadata.get("played_move"))


def pin(metadata, player_color=None):
    relation = metadata.get("pin")
    if not isinstance(relation, dict):
        return LegacyEvidence()
    values = {key: piece_label(relation.get(source)) for key, source in
              (("attacker", "attacker"), ("front", "pinned"), ("rear", "behind"))}
    if not all(values.values()):
        return LegacyEvidence()
    pin_type = relation.get("pin_type")
    values["relationship"] = f"{pin_type} pin" if pin_type in {"absolute", "relative"} else "pin"
    proof = None
    pov = metadata.get("player_color")
    evaluations = metadata.get("evaluation_player_cp")
    if pov in {"white", "black"} and (player_color is None or pov == player_color):
        evaluations = evaluations if isinstance(evaluations, dict) else {}
        gain = metadata.get("retained_material_gain_cp")
        proof = ProofEvidence(score_pov=pov, retained_material_gain_cp=gain if type(gain) is int else None,
            evaluation_before=_evaluation({"cp": evaluations.get("before")}),
            evaluation_after_played=_evaluation({"cp": evaluations.get("played")}),
            evaluation_after_tactic=_evaluation({"cp": evaluations.get("pin")}),
            scope=metadata.get("proof_scope"))
    return LegacyEvidence((FeedbackFact("line_relationship", tuple(values.items()), ("metadata_json.pin",)),),
        proof=proof, recommended_move=metadata.get("pinning_move_san") or metadata.get("pinning_move_uci"),
        played_move=metadata.get("played_move_uci"), proof_line=metadata.get("proof_line_san"))


def mate(metadata, player_color=None):
    # Canonical solution/proof are normalized by the common builder. No mate
    # distance is parsed from notes or calculated from a SAN suffix/line length.
    return LegacyEvidence()


def skewer(metadata, player_color=None):
    relation = metadata.get("skewer")
    if not isinstance(relation, dict):
        return LegacyEvidence()
    values = {key: piece_label(relation.get(source)) for key, source in
              (("attacker", "attacker"), ("front", "front"), ("rear", "rear"))}
    if not all(values.values()):
        return LegacyEvidence()
    values["relationship"] = "skewer"
    return LegacyEvidence((FeedbackFact("line_relationship", tuple(values.items()), ("metadata_json.skewer",)),))


def canonical_only(metadata, player_color=None):
    return LegacyEvidence()


class LegacyAdapterRegistry:
    """Trusted application adapters; never loaded from community pack data."""
    def __init__(self):
        self._adapters = {}

    def register(self, tactic_type, adapter):
        if tactic_type in self._adapters:
            raise ValueError(f"Duplicate feedback adapter: {tactic_type}")
        self._adapters[tactic_type] = adapter

    def build(self, tactic_type, metadata, player_color=None):
        return self._adapters.get(tactic_type, canonical_only)(metadata, player_color)


def default_adapters():
    registry = LegacyAdapterRegistry()
    for kind, adapter in (("missed_fork", fork), ("missed_mate", mate),
                          ("missed_pin", pin), ("missed_skewer", skewer), ("missed_xray", canonical_only)):
        registry.register(kind, adapter)
    return registry
