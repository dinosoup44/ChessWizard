"""Approved entry branches with fresh per-ply evaluation and the original bounded clock."""
from dataclasses import replace
from tactical_proof import verify_bounded_line


def line_evaluation(line):
    """Expose validated line evidence in the shared White-POV proof contract."""
    score = line.score.pov("white")
    return {"score_pov": "white", "score_type": "cp" if score.score_cp is not None else "mate",
            "score_cp": score.score_cp, "mate": score.mate_score,
            "principal_variation": " ".join(line.pv_san), "best_move_uci": line.move_uci,
            "best_move_san": line.move_san}


def verify_approved_bounded_line(after_tactic, color, prefix, best, piece_values, window):
    """Fix only approved entry moves; all later plies use fresh selected evidence.

    Entry plies count inside the original payoff window, never in front of it.
    Prefix objects enforce gate membership; legality and settlement remain shared.
    """
    position = after_tactic.copy(stack=False)
    entries = {}
    for entry in prefix:
        if entry.approval.source.fen != position.fen():
            raise ValueError("Discontinuous approved proof prefix")
        line = next(line for line in entry.approval.lines if line.move_uci == entry.move_uci)
        entries[position.fen()] = line
        position.push_uci(entry.move_uci)
    def evaluate(fen):
        return line_evaluation(entries[fen] if fen in entries else best(fen))
    return verify_bounded_line(after_tactic, color, evaluate, piece_values,
        replace(window, version="approved_entry_each_ply_v1"))
