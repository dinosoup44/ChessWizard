# Human analyzer feedback logger V1

Human Review is local test/QA feedback, independent of analyzer truth. Open
Tools > Human Review / QA from Game Review, then select a
stored Tactical Moment or an audit target in the QA dropdown, then choose
PASS, WRONG MOTIF, WRONG PAYOFF, WORDING,
NOT IMPORTANT or INVESTIGATE, optionally enter a note (500 characters maximum),
and click Save Review. Saving does not navigate. Choosing a target reloads the saved
verdict and note; the status shows whether the candidate has been reviewed.
Save before choosing another review target. Drafts clear when the target/game/context
changes. Show Line, Hide Line and projected-line playback retain the draft;
actual-game navigation also retains a draft for the same audit target.

## Scope and identity

Candidate-backed reviews use `candidate:<candidate_id>` as their stable logical
identity within this project's database. Game, move and tactic type must also match the saved record.
Changing review set does not create a duplicate review. Saving again updates the
one current record, including the latest review-set context; there is no revision
history. Identical saves preserve the timestamp and file bytes.

Audit-only cases use `candidate_id = null` and an explicit `audit_case_id`
containing the source artifact and stable source case key. Their identity is an
`audit:` namespace with a canonical JSON tuple of game ID, nullable move ID,
audit-case ID and proposed move. Review-set membership, labels and reason text
are excluded, so changing review sets does not duplicate the same audit review.
Source artifact paths and case keys are treated as stable provenance identifiers.

The QA target dropdown lists unrepresented audit cases for the current game.
A sole audit case is selected automatically; several cases require an explicit
choice. Duplicate shortlist reasons for one source case merge into a single
target. A selected Tactical Moment takes priority and uses its real candidate
ID; matching visible candidates are excluded from the audit-only choices.
Unrelated moments never inherit the game's audit reason. Selecting a QA target
changes only what the logger records; it does not jump the board, create a
Tactical Moment or make a scratch proof playable. The target label identifies
the audit move/color/proposed move and reasons.

If there is no real move ID, an explicit audit-case ID is still required and
`move_number = 0` is stored strictly as a non-chess review anchor. Move and
candidate IDs remain null. The UI and summary say "game-level anchor (not a
chess move)"; no real game move is numbered zero. Known real moves must not use
this fallback. Different case IDs/proposed moves remain different reviews even
when they share a game or move.

Existing candidate-only schema-v1 records remain readable without migration or
rewriting. New audit fields have defaults for legacy records. Identical legacy
saves retain the original timestamp and bytes; adding audit reviews preserves
existing review values. The typed JSON record schema gains nullable IDs and
optional audit reference fields; the production SQLite schema is unchanged.

Exact matching case metadata supplies reason labels and source artifacts. The
record also retains the current FeedbackResult's small provenance pairs when
available. This is presentation/evidence provenance, not a newly calculated
analyzer version. No proof payload, FEN, score, candidate status or engine output
is copied or changed.

## Storage contract

Default location: `reviews/human_analyzer_review.jsonl`, relative to the project
module directory, independent of the launcher's working directory. The directory
and file are created only on the first successful save. Each UTF-8 JSON line is
one current `HumanReviewRecord`: `schema_version` (1), nested `case`, `verdict`,
`note`, and timezone-aware UTC `reviewed_at`. The nested case contains game/move/
candidate IDs, tactic type, review-set ID, reason labels, source artifacts and
provenance pairs. Surrounding note whitespace is trimmed. A local QA file limit
of 8 MiB bounds parsing and replacement; this is a small review log, not a proof
archive.

`human_analyzer_reviews.py` defines immutable typed models, exact case association
and pure summary logic. `human_analyzer_review_repository.py` handles file access.
Neither imports SQLite, Tkinter or chess/engine/analyzer modules. The desktop
`HumanReviewPanel` calls this shared repository; the Tactical Moments selection
hook updates the target only on selection changes, not on proof rendering.

Saves acquire an exclusive adjacent `.lock`, reload existing records, merge the
one target's judgment, write a same-directory temporary file, flush/fsync it,
and atomically replace the current file. Other review records are preserved.
The lock prevents simultaneous writers from dropping unrelated reviews. A busy
lock reports an error; no background retry or stale-lock deletion occurs. After
a crash, inspect a leftover lock and ensure no writer is active before removing
it manually. Concurrent edits to the same review target use the last explicit save.

Missing files are empty and reading never creates directories/files. Malformed
JSON, invalid schemas/records, duplicate identities, oversize files and read
errors fail closed: the UI reports the problem and refuses to overwrite the
file. Repair/preserve the local file explicitly, then reselect the moment to
reload. An interrupted replacement keeps the previous current file; a failure
to release a lock reports that the save may have completed and requires reload.
Atomic replacement plus file fsync reduces partial-write risk; it is not a claim
that every filesystem/hardware power-loss scenario is recoverable.

## Summary

From the project root:

```text
python reports/summarize_human_reviews.py
python reports/summarize_human_reviews.py --json
python reports/summarize_human_reviews.py --path path/to/test_reviews.jsonl
```

The command reads only the review file. It prints the current reviewed total,
all six verdict counts (including zeros), counts by tactic and latest review-set
context, and non-PASS candidate or audit/game/move references with notes. `--json` emits
structured counts and records. Malformed input returns exit code 2 with a clear
error and no partial summary. Unicode notes are supported on Windows. This
utility does not score analyzer quality or change any analyzer automatically.

## Safety and testing

The production chess connection remains read-only. No migration, candidate,
training, coverage, cache, proof, analyzer policy, scheduler or theme changes.
Tests exercise every verdict, notes, reload/replacement/idempotency, identity,
exact provenance, malformed input, failed atomic replacement, writer locking,
read-only summaries, UI selection, draft behavior and database independence.
Use `python -m unittest discover -s tests` for the full suite.

The feature does not modify an already-running Game Review process. Finish the
current review session normally, then restart Game Review to load the controls.


Game 2771's saved new-deferral target is move 30 Black, move ID 169882,
proposed move `a5a3`. The separate human observation around move 2 is preserved
in [Game 2771 presentation feedback](../reviews/GAME_2771_PRESENTATION_FEEDBACK.md).
It is not attributed to the move-30 audit target or treated as verified analysis.


Human-facing reason wording is generated from stable codes by
`review_reason_labels.py`. Normalized entries retain code, label and explanation;
new review records also preserve `review_reason_codes`. Existing review notes,
labels, timestamps and identities are not migrated or rewritten during label
cleanup. No stored human verdict is used to tune Critical Moment Context.


## Original audit status, separate from human verdict

Human Review shows a bold status and explanation above the verdict controls
when an audit case has an explicit supported `checker_classification` in its
source `analyzer_provenance`:

| Original classification | Label | Meaning |
|---|---|---|
| confirmed | CONFIRMED BLUNDER | The checker classified this as a major material blunder. |
| unresolved | UNRESOLVED | Suspicious material-loss evidence was insufficient for confirmation. |
| not_blunder | CONTROL — NOT BLUNDER | The checker did not call this a blunder; it tests false-positive resistance. |

`review_audit_status.audit_status_for_case` returns an immutable presentation
model without Tkinter, database, chess or engine dependencies. The desktop panel
only renders it through the existing `set_case` selection path. Classification,
reason, target type, reviewer verdict, note and save state remain distinct.

The metadata contract, not a review-set name or tactic-specific UI branch,
selects the status. Future audit sets may supply the same checker metadata with
the same semantics; a different vocabulary requires its own explicit mapping.
Missing, unknown or conflicting classifications return no status. Candidate-only
reviews and older audit sets are not relabeled from reason text or verdicts.
Selection clears/hides both labels when metadata is absent, preventing stale
status from the previous case.

All six verdict choices and saved JSONL schema/identities stay unchanged. Merely
viewing a case never saves or reinterprets a judgment: a control marked WRONG
MOTIF still displays both CONTROL — NOT BLUNDER and that saved human verdict.
No candidate is invented and no analysis runs. Existing Game Review processes
load this presentation change on their next normal restart.

## Played Forks — ten assessment cases

The built-in `played_forks_v1` set (display **Played Forks**) packages only the
identities in `reports/played_fork_assessment_v1.json`. It is audit-only: stored
candidate selections cannot create extra review targets under this set. Existing
review sets, identities and verdicts are unchanged. Each case uses motif `fork`,
relation `played_by_user`, matching actual/tactical UCI, and no candidate ID.
The existing logger writes only an explicit user Save Review to
`reviews/human_analyzer_review.jsonl`. Implementation tests use temporary files.

The panel separates confirmed geometry, supplied admission, exact best-defense
proof status, and recorded-window material. The deterministic assessment summary
is shown unchanged. Details contains source game/move, piece/targets, admission,
recorded captures/material and separate ACTUAL LINE and counterfactual PROOF
LINES. Proof text is not passed to actual-game playback. Selecting an audit jumps
to its exact stored move's fen_before and validates the recorded root identity.

PASS means identification/targets/factual consequence look right. WRONG PAYOFF
concerns recorded consequence, not a request to upgrade ambiguous forced-payoff
proof. WRONG MOTIF, WORDING, NOT IMPORTANT and INVESTIGATE retain their existing
meanings; no verdict was added. This is not re-certification of forced payoff.
The summary tool counts motif, review set and explicit relation separately;
older records without relation stay `unspecified`, with original counts intact.

Layered metadata rendering and collapsible read-only Details are generic audit
presentation. The UI does not calculate chess truth or run an analyzer.

## Optional QA resources in V1 distributions

Normal Game Review does not require private review notes or QA catalogs.
`load_review_sets` returns only the code-defined All Games set when
`review_data/builtin_review_sets.json` is absent. Normal Game Review contains no QA controls. Its dedicated Tools-launched QA
window disables the Review Set picker and explains that optional sets are absent
when none are installed; no empty review file is created. A malformed catalog that
is actually installed still reports an error; absence and corruption are distinct.
No empty replacement catalog or fabricated review entries are required.

| Set/resource | Classification | Default V1 package recommendation |
|---|---|---|
| All Games | Product browsing functionality, defined in code | Keep |
| Questionable | Internal developer QA cohort | Exclude catalog entries and source audits |
| Verified | Internal developer QA controls, not a user seed dataset | Exclude |
| Selective-12 Changes | Internal proof-policy comparison | Exclude |
| Major Material Blunders | Internal historical QA and factual fixtures | Exclude catalog and fixtures |
| Played Forks | Internal ten-case assessment QA | Exclude |
| `reviews/human_analyzer_review.jsonl` and review notes | Private human judgments and identifiers | Exclude |
| `reports/` and historical audit outputs | Research/provenance, not runtime defaults | Exclude |

All existing development artifacts remain in the working project, unchanged.
Installed/injected QA sets still use the existing identities, selection and save
contracts. `HumanReviewRepository` reads a missing JSONL as empty without creating
it. An explicit Save Review may create a profile-local
`reviews/human_analyzer_review.jsonl`; startup never does. Existing development
notes are reused only for their original source-checkout database. An explicit
repository path remains supported for QA tools/tests. Each database/profile keeps
its own review identities; notes are never copied to a different user database.
See [FIRST_RUN.md](FIRST_RUN.md) for path precedence and the clean-user contract.

## Dedicated QA window (UI round 1.1)

Review Set, target, verdict, note and Save Review reuse HumanReviewPanel and the
existing repository/identity contract in a separate managed window. Reopening
the menu lifts that window. Normal Tactical Moments still drive its selected
candidate when QA is open. Only an explicit Save Review writes feedback.
Closing QA discards unsaved drafts and removes its filter from normal browsing;
save before closing. QA layout scrolls independently of the normal review panel.
