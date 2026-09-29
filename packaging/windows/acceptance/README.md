# Acceptance console tooling

This is release-test tooling, separate from the ChessWizard runtime. The tester
uses `START-HERE.cmd`; [README-FIRST.md](README-FIRST.md) is the tester guide.
The application payload and sample plugin remain unchanged. The final installer
contains wording polish only; its source companion includes the matching helper,
installer and public application sources.

## Build and handoff

Use Windows and CPython 3.14.7. In the matching source folder, create
`build/windows/venv` with `python -m venv build/windows/venv`, then install the
pinned `packaging/windows/requirements-build.lock.txt` with that environment's
pip. Run `packaging/windows/acceptance/build.ps1` from the source folder. It creates the console-only, self-contained helper at
`build/phase5-acceptance-ux/helper/ChessWizardAcceptance.exe`. The build isolates
PATH/PYTHONPATH and rejects native inputs outside the selected Python environment.
It does not rebuild the application, installer, source companion or plugin.

Copy the helper into the kit's `acceptance/` folder and put START-HERE.cmd and
README-FIRST.md at kit root. Include the helper's matching source/build files,
GPL license, exact CPython/incorporated notices and PyInstaller notice. The
final source companion is `ChessWizard-Final-Acceptance-Source.zip` and includes
the helper alongside the matching application, installer and upstream sources.
Inspect the actual embedded module/native inventory before handing it off.

`KIT-MANIFEST.json` has `schema_version: 1` and `files` entries with `path`,
`bytes`, and lowercase `sha256`. Paths are kit-relative with forward slashes.
Include `plan_id: "v15-final-external-v1"`; an older kit cannot enter this workflow.
It covers the candidate installer, source companion, wheel, synthetic PGN, helper, notices
and instructions. Exclude the manifest itself, SHA256SUMS.json, receipts and
VIEW-RESULT.txt. Recompute after changing an immutable kit file. The helper
checks all listed hashes and rechecks packages immediately before executing them.
Hashes detect accidental drift; an unsigned local manifest is not an authenticity
signature. Keep the previously approved artifact hashes for independent review.

## Contracts and testing

- `records` saves INCOMPLETE before the first key, then atomically checkpoints
  timestamped receipts, the latest pointer and VIEW-RESULT.txt. No result lives
  only in TEMP. Storage failure stops operations.
- `console` owns prompts/progress/final pause and R/V/Q recovery. Human Y/N notes
  are mandatory. Restart never resumes a destructive operation midway.
- `workflow` runs the eight consumer stages only after an existing-profile guard
  using the Windows known folder. No silent uninstall or automatic trust.
- `windows` owns the wizard and descendants through a kill-on-close Windows job.
  Forced closure stops owned processes; it does not guarantee installer rollback.
- The existing release-acceptance gate checker remains authoritative. PASS
  records completed observations, not owner permission to publish. A signing
  recommendation can still block release.

Run `python -B -m unittest discover -s tests -p test_acceptance_wizard.py`
for the self-contained synthetic helper tests. In the full application checkout,
also run `test_release_acceptance.py` for the existing release-gate/installer
regressions (those tests require the application build tools). The optional `tests/support/acceptance_console_driver.py`
exercises a disposable console with an inert timed child; all its receipts say
simulation and cannot satisfy clean-machine/human release gates. This test driver
is not compiled into the distributed helper and there is no simulation CLI mode.

A frozen-helper smoke on a development account must stop at the existing-profile
guard. Never run consumer servicing tests against a real user profile. Visible
console probes are same-host UX evidence only. Clean Windows, real human
installer/plugin/DPI checks and security observations remain separate release gates.

## Final external scope

Schema 2 / `v15-final-external-v1` records the owner-approved shorter remaining
external flow. Schema 1 remains validated against its original full matrix; old
receipts are never reinterpreted or relabeled. Synthetic upgrades and destructive
full removal retain their automated receipts outside this manual kit. Only inspect
the full-removal confirmation and decline it.

The `observations` module records Y/N/unobserved DPI and structured security fields.
USB-only/missing evidence cannot close download security; a Defender alert/block
fails it. Supplemental forms can document later effective-scale or browser checks
without repeating the functional chain; owner review is required and the original
receipt remains intact. Signing is an owner decision, not an automatic PASS.
