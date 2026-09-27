# Fork Pass 2: legal threats and exchange detail

The registered Fork V2 calculation now applies `fork_threats.functional_fork_threats`
after geometric discovery. Shared attack maps retain their geometric meaning.

The helper requires a valid board and legal proposed move, preserves the input,
and reports each attacked non-pawn target separately. Non-king targets are tested
on the resulting occupancy with the attacker's turn and no en-passant entitlement.
This is a **threat probe**, not a legal opponent pass, prediction of a defense, or
proof that a capture is forced. Own-king safety is mandatory. A check is the king
threat; king captures are never generated. Two executable targets are necessary,
not sufficient: the existing evaluation, best-reply and conversion gates still run.

Qg7 has one executable target (Qg3), because Qxd4 exposes Kg8. Its favorable
engine evaluation is unaffected. A pinned rook/queen can still capture along its
pin line. Rejecting every pinned piece or changing shared attack maps would be
incorrect. The helper reports version 1; newly calculated V2 payloads retain this
provenance. Thresholds and the production registry version remain unchanged.

The experimental V3/V3.1 paths retain their frozen replay contracts. This task does
not activate/migrate them or revise their historical evidence. Adoption of the
reusable helper there requires a separate controlled replay/version decision.

## Separate answer and detail contracts

`solution_line` remains the concise Training answer. `exchange_presentation`
metadata is optional, independently versioned presentation evidence. It never
changes admission, coverage state, or Training's answer length.

`exchange_presentation.py` is pure and UI-independent. It composes `StoredLine`,
shared material values, and `tactical_proof.play_proof_move`. It legally replays
supplied evidence and exposes immutable short/full/continuation lines, endpoint,
whole-line material accounting, source provenance and completeness. It does not
own an engine, database connection, candidate selection or motif attribution.

Prefer the original tactical PV **only if its entire legal prefix matches the
short answer exactly**. Otherwise use an independently supplied exact endpoint
PV. Never splice a different reply into the original line. The registered V2
specialist already holds both evaluations, so adding detail needs no new search.

Default presentation limits are 12 additional plies, two quiet actual plies and
two quiet lookahead plies. Lookahead avoids stopping between a6 Bg3 and axb5.
Checks, captures and promotions interrupt quietness. Terminal states stop replay.
A missing/invalid/exhausted PV or cap hit stays incomplete; the observed material
is not exposed as settled material. A bounded settled line is not exhaustive
best-defense proof and is never automatically credited to the Fork motif.

`ExchangePresentationSettings` uses the shared typed Settings/setting schema and
is injected explicitly. Its schema IDs are `presentation.exchange.max_plies` and
`presentation.exchange.quiet_plies`; defaults/ranges are 12/[1,32] and 2/[1,4].
Both are advanced presentation settings with no raw-cache or analyzer-currentness
impact. There is no new settings file, Admin UI, or changed global proof profile.
Consumers must regenerate optional detail if they choose a different policy.

`exchange_presentation_repository.StoredExchangeReader` enriches a read model
from existing exact `tactic_verify_v1` rows only. It cannot start an engine or
insert/update data. Missing evidence produces an incomplete detail, not a search.
This legacy source has its existing single-position cache identity limitations;
reading it is not promotion into the candidate-line cache.

FeedbackContext validates a serialized detail by identity and legal replay,
recomputing all derived fields. FeedbackResult contains separate continuation and
summary fields, and the existing canonical Game Review renderer displays its
explanation. The frontend contains no new chess logic. Optional fields clear on
selection changes. The feedback pack example includes the additive detail keys.

Detailed wording distinguishes the captured target, settled whole-line material,
and the historical evaluation delta. A neutral exchange never becomes a free
bishop; +267 cp of evaluation never becomes +267 cp of material. Incomplete detail
explicitly withholds a retained-material conclusion.

## Reconciliation boundary

No live row is reclassified, rewritten, or invalidated by this task. In particular,
the saved Qg7 candidate still exists until a separately approved reconciliation;
only new calculation and the review shortlist report it as a non-Fork. Existing
coverage remains protected/current under its existing version rules. A future
scoped reconciliation must explicitly handle versions/currentness and candidate
history without deleting/reinserting canonical IDs. Do not use old standalone
launchers or bulk invalidation to apply this change.
