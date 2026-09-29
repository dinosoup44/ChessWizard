# ChessWizard V1.5 FINAL ACCEPTANCE

## 1. WHAT TO CLICK

Copy this **whole folder** to writable storage on a clean disposable Windows PC
or account. Double-click **START-HERE.cmd**. This is the final acceptance guide;
do not use an earlier Phase 1 RUN_VALIDATION.cmd. No Python, Git or VS Code needed.
Keep Windows security enabled. An existing ChessWizard profile is refused.

## 2. WHAT YOU WILL SEE

A console stays open, with eight numbered stages and **Still working...** messages.
It pauses for a first key, waits for every child window, and asks for observations.
Finish each directed UI action, close ChessWizard normally, then return here.
The public candidate label remains **1.0.0-beta**; V1.5 names this release milestone.

## 3. WHAT TO CHECK

The guide runs this short flow:

1. Install normally; inspect name/icon, options, per-user path and shortcuts.
2. Launch, check default openings, import the supplied synthetic game and save one
   disposable setting/opening edit. Do not run analysis or Stockfish.
3. Tools > Plugins: the guide installs the sample; check it appears, cancel trust
   once, explicitly enable/trust, Run on Current Position, inspect facts, disable.
4. Same-version repair; game/settings/openings and disabled sample must remain.
5. Default uninstall keeps data. Reinstall must restore that profile/plugin state.
6. Inspect optional full removal: starts unchecked, shows second confirmation and
   categories. Answer **NO**. Verify the app/data remain; do not confirm deletion.
7. Record actual security behavior using **SECURITY-OBSERVATIONS.md**.
8. Inspect only five UI surfaces at each scale using **DPI-CHECKLIST.md**.

Synthetic upgrades/API1/API2, destructive full-removal/fresh-reinstall edge cases,
plugin removal and worker limits are already automated. They are intentionally
absent from this human kit. This is not permission to omit the checks above.

Answer Y/N and write a short observation. N stops functional checks with FAIL.
Unperformed DPI/security checks stay PENDING and the final result is INCOMPLETE.
Use U when offered, Q at questions or Ctrl+C to cancel. Never guess a PASS.

## 4. HOW YOU KNOW IT WORKED

PASS, FAIL or INCOMPLETE stays visible until a key. The exact receipt/log paths
are displayed. No owned acceptance job is intentionally left running afterward.
PASS means this observed run completed, not permission to publish. Signing and
owner release approval are separate; see **SIGNING-DECISION.md**.

## 5. WHERE THE RECEIPT IS

**VIEW-RESULT.txt** beside START-HERE.cmd shows status, date/time and receipt path.
Timestamped JSON, progress logs and installer/child logs stay in **receipts/**.
Return that entire folder, VIEW-RESULT.txt and any completed forms/screenshots.
Do not edit original JSON to make it pass. Nothing depends only on TEMP.

## 6. WHAT TO DO IF THE WINDOW DISAPPEARS

**If the window disappears without showing PASS or FAIL, the run did not complete
successfully.** Read VIEW-RESULT.txt. Reopen START-HERE.cmd for **R = Restart,
V = View previous result, Q = Quit**. R starts again; it never resumes uninstall.
Restore a clean disposable baseline before restarting a partly installed run.

Prefer cancellation inside installer windows. Forced closure stops owned children
but may leave a partial installation. The launcher tries to retain INCOMPLETE even
if the helper cannot start. If the kit is unwritable, it says so; retain a photo.
For DPI sign-out or USB-only security limitations, follow the supplemental forms
instead of needlessly repeating the entire functional flow.
