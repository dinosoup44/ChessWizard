"""Reusable evaluation gates and bounded material proof, independent of motifs.

Calculators inject evidence access. No engine lifecycle, database, or registry.
Existing specialists keep their original policies and behavior.
"""
from dataclasses import dataclass, field
import chess
from board_analysis import material_balance
from engine_cache import score_for_color
from tactical_proof import ProofWindow, verify_bounded_line, validate_evaluation


@dataclass(frozen=True)
class MaterialPolicy:
    quick_profile: str = "tactic_quick_v1"
    verify_profile: str = "tactic_verify_v1"
    quick_gain_cp: int = 120
    quick_drop_cp: int = 300
    verify_gain_cp: int = 150
    verify_drop_cp: int = 200
    retained_cp: int = 100
    final_floor_cp: int = -100
    window: ProofWindow = field(default_factory=ProofWindow)


class MateEvidence(ValueError):
    def __init__(self, score):
        self.score = score
        super().__init__("Mate evidence requires another primary owner")


class EvaluationSession:
    def __init__(self, position, color):
        self.position, self.color = position, color
        self.cache, self.evidence = {}, []

    def raw(self, fen, profile):
        key = (fen, profile)
        if key not in self.cache:
            raw = validate_evaluation(self.position(fen, profile))
            self.cache[key] = raw
            self.evidence.append({"cache_id":raw.get("cache_id"), "profile":profile,
                                  **score_for_color(raw, self.color)})
        return self.cache[key]

    def cp(self, fen, profile):
        score = score_for_color(self.raw(fen, profile), self.color)
        if score["score_type"] == "mate":
            raise MateEvidence(score)
        return score["score_cp"]


@dataclass(frozen=True)
class MaterialAssessment:
    reason: str
    proof: object = None
    scores: dict = field(default_factory=dict)
    initial_cp: int | None = None
    final_cp: int | None = None
    retained_cp: int | None = None


def assess_material_move(row, choice, session, values, policy):
    scores = {}
    for stage, profile, gain, drop in (
            ("quick", policy.quick_profile, policy.quick_gain_cp, policy.quick_drop_cp),
            ("deep", policy.verify_profile, policy.verify_gain_cp, policy.verify_drop_cp)):
        scores[stage] = {key:session.cp(fen, profile) for key, fen in (
            ("before", row["fen_before"]), ("played", row["fen_after"]), ("tactic", choice.fen_after))}
        s = scores[stage]
        if s["tactic"] - s["played"] < gain or s["before"] - s["tactic"] > drop:
            return MaterialAssessment(f"insufficient_{stage}_gain", scores=scores)
    after = chess.Board(choice.fen_after)
    proof = verify_bounded_line(after, session.color,
        lambda fen:session.raw(fen, policy.verify_profile), values, policy.window)
    if proof.state != "stable":
        return MaterialAssessment(f"proof_{proof.state}", proof, scores)
    scores["deep"]["final"] = session.cp(proof.final_fen, policy.verify_profile)
    initial = material_balance(chess.Board(row["fen_before"]), session.color, values)
    final = material_balance(chess.Board(proof.final_fen), session.color, values)
    retained = min(final-initial, final-material_balance(after, session.color, values))
    s = scores["deep"]
    reason = ("material_not_retained" if retained < policy.retained_cp else
              "continuation_not_sustained" if s["final"] < policy.final_floor_cp or
              s["final"]-s["played"] < policy.verify_gain_cp or s["before"]-s["final"] > policy.verify_drop_cp
              else "material_verified")
    return MaterialAssessment(reason, proof, scores, initial, final, retained)
