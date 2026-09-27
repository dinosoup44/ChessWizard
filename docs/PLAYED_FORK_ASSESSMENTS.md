# Played Fork assessments V1 (report only)

`played_fork_assessment.assess_played_fork` composes four independent layers:
geometry, supplied move admission, supplied counterfactual payoff proof, and
recorded consequence. It does not call an analyzer, engine, repository or UI.
It is usable by tools/tests and future frontends without Tkinter. There is no
master verified-played-Fork boolean and no tactic grade.

## Interfaces

- `played_fork_proof`: immutable `ForkPayoffEvidence` / `ForkProofBranch` plus
  `payoff_evidence_from_saved`. The saved result must bind its required move and
  decision FEN exactly. Classification strings are preserved, including ambiguous
  and deferred; malformed/conflicting identity fails closed. Absent proof is
  unavailable with unknown admission. Selected-root admission is consumed from
  `root_move_passes_gate`, not inferred from an approved set of other moves.
- `played_fork_assessment`: immutable `PlayedForkAssessment`, `ForkGeometry`,
  `RecordedForkConsequence`, and `RecordedTargetCapture`. Inputs are explicit
  source identity, FEN, legal actual root, actor/perspective and optional actual
  continuation/proof. Supplied continuations are immutable tuples including the
  root. Invalid legality, actor or root identity raises ValueError; no invented
  position or result is returned.
- `played_fork_descriptions.describe_played_fork`: deterministic immutable
  summary, recorded context, proof context and admission context. Consumers must
  render the contexts together to preserve adverse admission and proof ambiguity.

Geometry composes the shared `attacked_pieces` helper with the existing Fork
scope: the moved piece attacks at least two enemy non-pawns (king included as a
checking target). Pinned attacks still count geometrically; this is not a promise
of legal captures or soundness. No existing analyzer/private function is called.
The target scope matches the current provider and is named/documented explicitly.
Promotion roots use the resulting piece type; original attacker identity stays
anchored before the move. Invalid input fails; the reserved unresolved geometry
state is not substituted for programmer/source errors.

## Actual versus counterfactual evidence

Actual and proof lines are separate immutable fields. No proof PV is inserted
into actual game history. All supplied proof branches remain in the proof facet;
we do not pick a favorable branch as the occurrence's canonical proof.
`proof_line_count` counts stored nonempty lines, including partial prefixes.
`complete_sampled_branches` means each supplied branch settled; it does not mean
exhaustive proof, and it does not turn branch disagreement into verification.
Overall retained payoff is absent for ambiguous/rejected/deferred results, while
branch material/attribution values remain available. No new causal rule is used.

Recorded captures use `LegalReplay`'s `PieceIdentity` and `CaptureEvent` objects,
not square-only matching. Each capture identifies the original target, actual
capture square, capturer, SAN and plies after the root. Captures by another piece
are distinct from captures by the original attacker. Initial captures are not
original post-root targets. A target capture is independent of material outcome.

The existing `MaterialTransition` supplies material before/after, captures,
losses, promotions and snapshots. Actor-perspective gained cp includes enemy
pieces captured and own promotion increments; lost cp includes own captured
pieces and enemy promotion increments. Net equals gained minus lost and the
relative material change. These are bounded recorded-window observations, not
Fork credit. Before/after totals remain available for both colors in the shared
object. Piece values are the toolkit's shared values, not new local constants.

Missing history is unresolved, not neutral. Root-only history does not establish
a response/outcome. A supplied window with an opponent reply can support review
even if it ends before settlement; `supplied_recorded_window` never means the
whole game or a settled proof. Negative and neutral windows are reviewable too.
FEN-only history cannot establish every repetition-dependent fact; toolkit
terminal/history limitations remain attached.

## Relationship and wording

For confirmed geometry, a report-only `TacticOccurrence` carries motif `fork`,
kind played, actual=tactical move, explicit actor and perspective, no candidate
ID, and `source_verdict=confirmed_fork_geometry`. That verdict is deliberately
separate from the assessment's exact payoff-proof status. A missing continuation
leaves only the known root in the occurrence; consequence remains unresolved.
No-geometry assessments have no Fork occurrence. Existing adapters/consumers are
unchanged. `played_by_perspective` maps to played by the user only when the game
user's color is the supplied perspective; opponent wording is supported too.

Descriptions say a target was captured only when the recorded ledger shows it.
They do not say an initial or later unrelated gain was caused by the Fork. The
summary can acknowledge a real Fork while the proof context still says ambiguous.
The formatter makes no affirmative forced-payoff claims, even for a supplied
verified result; it reports the exact provider status and scope instead. Material
context always states its recorded window and actor POV. Rejected admission is
explicit and does not erase geometry. Checkmate endpoints are factual historical
context, not a newly certified mate proof.

## Review readiness and future consumers

Readiness is evidence sufficiency, not importance or production ranking:

- confirmed geometry plus a recorded response window:
  `ready_for_recorded_consequence_review`;
- confirmed geometry without that window: `ready_for_geometry_review`;
- no confirmed geometry: `insufficient_evidence` for a Played Fork review item.

The categories are exclusive; recorded-consequence-ready cases also support
geometry review. The ten frozen pilot cases are all consequence-ready, with six
rejected and four ambiguous proof statuses unchanged. No active review set was
created. A review set may include adverse outcomes and incidental geometry to
review label quality, not just praise cards. Overlapping windows/mate sequences
must not become duplicate independent achievements in a future UI.

Future Played/Missed Game Review filters should consume the existing occurrence
relationship and typed assessment rather than run engines or duplicate domain
logic. No filters or UI integration are included now. Future ChessWizard 2.0
quality grades may consume material/admission/proof facets through a separate
policy; V1 has no A–F scores, implicit ranking, or grading thresholds. Scale and
all existing Fork proof/admission/settlement settings remain unchanged.

## Validation workflow

`reports/run_played_fork_assessments.py` reads only the exact ten saved cases,
validates the frozen follow-up IDs and writes `played_fork_assessment_v1.json`.
It blocks subprocess and sqlite connections while assessing. Tests use a compact
frozen fixture extracted from the existing evidence and include game 2704,
moved-target identity, promotions/loss, missing history, no-geometry, perspective,
immutable results, proof binding, deterministic wording, and fresh imports with
engine/database/analyzer/Tkinter imports forbidden. Existing missed-Fork guards,
proof output, candidates, coverage, caches and training remain untouched.

## Built-in human review integration

The exact ten saved assessments are now packaged as **Played Forks**
(`played_forks_v1`), an audit-only Human Review set. This authorizes review UI and
explicit local verdict/note logging, not production tactic persistence. Geometry,
admission, proof and recorded consequence remain independent and the saved
assessment descriptions are not regenerated or changed. Review judges motif,
factual recorded consequence, wording and importance; it does not re-certify
forced payoff. No production Played/Missed filter, grading or proof-policy change
is included. See HUMAN_ANALYZER_REVIEWS.md for identity and storage details.

## Frozen after ten-case human review

Played Fork Assessment V1 is frozen after review of the exact `played_forks_v1`
ten-case set: **8 PASS, 2 INVESTIGATE**, with zero WRONG MOTIF, WRONG PAYOFF,
WORDING or NOT IMPORTANT verdicts. This is a bounded human-review checkpoint,
not a statistical accuracy claim or new certification of forced payoff.

The two INVESTIGATE notes concern primary-story/context ownership rather than
Fork truth. Game 2709 highlights the queen trade and actual king-recapture /
castling-rights context; this note does not establish that king recapture was
forced under every defense. Game 2710 highlights the larger queen-blunder context,
with the Fork potentially supporting that story. No new proof or blunder analysis
was run to reinterpret either case, and no Fork truth or wording rules changed.

Future occurrence storage should preserve the Fork claim and its reviewed evidence
while allowing separate Critical Moment ownership. The proposed portable contract
is documented in [TACTIC_OCCURRENCE_STORAGE.md](TACTIC_OCCURRENCE_STORAGE.md).
Existing candidate data, review JSONL and missed-Fork behavior remain unchanged.
