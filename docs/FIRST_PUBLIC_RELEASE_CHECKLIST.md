# Release acceptance checklist

The source repository is public. This checklist now governs the first V1.5 installer
release, not Git initialization. Public identity: **ChessWizard: Chess Analysis**.
Public version stays `1.0.0-beta` until validation completes and the owner approves
`1.5.0`. Synthetic test versions are not published releases.

## Automated preparation

- Review the approved installer-servicing commit and remote SHA; use a focused
  release-validation branch. Do not merge, tag or upload during validation.
- Run focused plugin/servicing tests, the full guarded working-tree suite and the
  full fresh public-copy suite. Never use owner data as a fixture.
- Run `tools.public_source`, privacy/secret review, pydoc validation/HTML generation,
  public Markdown link validation and the exact frozen package/license audit.
- Build the final consumer candidate and matching source companion. Hash every
  distributed input. Verify the separate external plugin was built afterward and
  is absent from every frozen archive. Retain notices, default-opening provenance,
  artwork permission and corresponding Stockfish source/networks.
- Hash protected owner files before/after; check SQLite integrity read-only. No
  analysis or owner migration is authorized by release validation.

## Mandatory clean Windows acceptance

Use a disposable clean Windows installation/account without a source checkout,
Python, Git or VS Code. Use normal consumer installers and canonical per-user paths,
not fixture-root installers. Keep logs and a durable receipt outside the managed
profile so full removal cannot erase evidence.

1. Install with no elevation. Inspect Desktop/Start Menu/Installed Apps entries and
   icon; launch from Finished; verify fresh profile and default opening content.
2. Install the independently built reference wheel using the included console host.
   Import the kit's synthetic PGN; use Plugin Manager trust and Run on Current Position.
   Disable, restart, verify no execution; remove without touching chess data.
3. Reinstall the reference plugin and enable it for upgrade tests. Rerun the same
   installer as repair. Verify profile preservation, no duplicate shortcuts and UI use.
4. With synthetic builds, test 1.5.0 -> 1.5.1 -> 2.0 API1; verify compatible plugin
   files/state and user data preserved. Default-uninstall and reinstall; verify prior
   data usable. Then install 2.0 API2: plugin retained, clearly incompatible, unable
   to run. Do not implement V2 features or bypass compatibility.
5. Default-uninstall preserves the entire profile. Explicit full removal is unchecked
   initially and requires a second confirmation enumerating data. Verify cancellation,
   then confirm deletion on this disposable account only. Reinstall creates fresh data.
6. Check no plugin worker remains after disable, close, removal and uninstall.

## Human review is separate

Observe welcome/options, install-path wording, Desktop option, progress, Finished
launch, uninstall keep-data wording, full-removal checkbox/confirmation, cancellation,
errors, plugin trust and Plugin Manager at **100%, 125%, 150%** Windows scaling.
Record observations/screenshots, not just automated scaling-test results.

Download/copy the exact unsigned candidate as a normal user. Record browser warnings,
Mark of the Web/transfer method, exact SmartScreen prompts, whether More info/Run anyway
was offered/needed, and Defender findings. Do not disable security. No warning on a
local copied file proves nothing about downloaded reputation. Choose either documented
unsigned distribution or code signing before public release; do not buy a certificate
as part of this checklist. A private vulnerability reporting route must also be ready.

## Receipt and approval

The local portable acceptance kit contains a pending receipt and step-by-step log
instructions. Missing observations remain pending, not PASS. Bind the receipt to the
installer/source/wheel hashes and Windows build; distinguish clean-machine results from
same-host fixture tests. Use `tools.release_acceptance` to check completeness after
manual review. Failed gates require fixes and affected revalidation.

Only after all gates pass may the owner approve the merge, public version bump, tag,
GitHub Release and installer upload. A changed final version/build must be re-audited;
a candidate hash does not certify bytes built later. Keep final decisions and exact
commits in the local owner-review report. No checklist command publishes automatically.
