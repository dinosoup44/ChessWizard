# FULL backup retention policy

Owner policy, effective 2026-09-20: each successfully created and fully verified
FULL backup replaces exactly one oldest eligible ordinary FULL backup.

Use the existing `backup_merlin.py` FULL workflow. A copied folder or a successful
SQLite quick_check alone is insufficient: verify project/profile file hashes,
backup database logical contents, quick_check, foreign_key_check, and an explicit
FULL/PASS receipt before selecting anything for removal.

Inventory every retained FULL backup across the known backup roots. Sort oldest
first, but preserve explicitly designated milestones, release baselines and uniquely
required rollback points. Preserve ambiguous cases and continue to the next clearly
ordinary FULL. If none can safely be removed, retain all and report why. Never
remove the new backup or force deletion to satisfy a count. QUICK backups are
outside this policy unless separately governed by an approved retention rule.

Before deletion, verify the resolved absolute target is the intended direct child
of its backup root, reject reparse/symlink paths, record its path and logical file
bytes, and retain the eligibility evidence. Use native PowerShell LiteralPath file
operations on Windows. Afterwards record actual deletion, retained FULL list and
bytes reclaimed. Do not infer successful removal from a planned action.

The policy is an operational requirement, not an automatic filename-based deletion
feature added to the backup CLI. Milestone/rollback classification requires evidence;
there is no generic age-only cleanup. Backup verification failure stops rotation
and any dependent production write.

The first rotation is recorded in
`reports/tactic_relationship_production/retention.json`: the ordinary pre-Collections
copy was superseded after its migration never ran. Earlier explicit milestones and
executed-migration rollback points were retained. See the reconciliation report for
the verified replacement and complete retained inventory.

## C: active project and optional recovery media (2026-09-20)

The checkout location is chosen by the contributor (for example C:\Projects\ChessWizard). Normal source/runtime/build paths derive from the checkout; user data remains in its existing Windows profile. Historical reports retain their original paths as provenance.

Run `python -B backup_merlin.py --full` for FULL or omit `--full` for QUICK. The default local destination is Merlin_Backups beside the project (C:\Merlin_Backups). `--destination` overrides it. Project and desktop activity locks protect the snapshot; the existing SQLite backup API remains the copy mechanism. FULL/QUICK both snapshot desktop settings/themes/reviews and managed books. Supply repeated `--book <path.cwbook>` for unmanaged authored books. FULL retains the established project exclusions; QUICK additionally excludes .venv, Engines and merlin_before_*.db. Reports/build artifacts remain included under the established workflow.

All included project hashes, profile copies, database logical contents and quick/foreign-key checks must pass. FILE_HASHES.json binds the exact backup contents; VERIFICATION.json records PASS and FULL/QUICK explicitly. SQLite backup hashes can differ from original files, so logical equality is checked separately.

D: is optional. If present, a verified copy is staged and hash-checked before replacing only this tool's owned ChessWizard_LATEST_FULL or ChessWizard_LATEST_SNAPSHOT directory. Missing media is reported and does not block the local backup. `--no-mirror` leaves D: untouched; `--mirror-root` explicitly selects different recovery media. An unowned destination, interrupted previous replacement, changed backup or insufficient staging space stops replacement and preserves existing recovery. A failed staging folder is kept for inspection. Local backup success and mirror failure are reported separately; the CLI returns failure for an attempted mirror that failed.

No broad drive cleanup or age-only local retention is automated. Local FULL rotation still requires the milestone/rollback classification above. Latest-only removable slots prevent unlimited history on D:, while C: retains classified historical recovery points. The install/handoff ZIP is built separately and includes its matching source companion.
