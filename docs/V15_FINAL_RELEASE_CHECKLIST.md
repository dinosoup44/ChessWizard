# V1.5 final release checklist

This is the current gate list. Public version remains **1.0.0-beta** until an
explicitly approved version change. Package readiness is not release permission.

## 1. Automated gates

Checkpoint: 2026-09-29; these results apply to the supplied candidate bytes.

- [x] Full working-tree (1,541) and fresh public-copy (1,392) suites pass.
- [x] Pydoc (136 modules), public-source/privacy scan and Markdown links pass.
- [x] Exact package/license/source/hash audits pass for the supplied artifacts.
- [x] GitHub private vulnerability reporting enabled (checked 2026-09-29).

Synthetic API1/API2 upgrades, full removal/fresh reinstall, plugin removal and
bounded-worker edge cases retain their automated Phase 4/5 coverage. The owner
approved keeping them out of the final normal human flow; do not repeat that matrix.

## 2. Owner manual gates

Owner review on the development PC (2026-09-29):

- [x] Installer works, app launches, existing profile/data preserved.
- [x] Uninstall completed successfully.
- [x] Plugin Manager layout, splitters and text areas accepted.

These are owner checks, not clean-machine or DPI certification. Installer wording
polish changes text only and is included in the final external kit for review.

## 3. Clean external-machine gate

Copy the complete **ChessWizard-V15-Final-Acceptance** folder. Use only
**START-HERE.cmd**, never the earlier Phase 1 RUN_VALIDATION.cmd.

- [ ] Clean Windows account/PC, no previous ChessWizard profile or source checkout.
- [ ] Install and launch; default openings and synthetic game work.
- [ ] Tools > Plugins: sample appears; trust/enable, Run on Current Position and
      disable work. A fresh sample starts disabled; the guide installs it for you.
- [ ] Same-version repair keeps profile and disabled plugin, no duplicate entries.
- [ ] Default uninstall keeps data; reinstall restores the profile/plugin state.
- [ ] Full-removal option starts unchecked; second confirmation lists categories;
      answer **No** and verify data remains. No repeated destructive test required.
- [ ] At 100%, 125%, 150% inspect only main app, Plugin Manager, trust dialog,
      installer and uninstaller: readable labels, usable panes, no clipping,
      missing buttons or overlap. Cancel installer before Install and uninstaller
      on its first page. Use the kit's **DPI-CHECKLIST.md** for sign-out constraints.
- [ ] Record actual browser/SmartScreen/Defender/block behavior with
      **SECURITY-OBSERVATIONS.md**. USB-only evidence leaves download behavior open.
- [ ] Return VIEW-RESULT.txt, the entire receipts folder and referenced supplemental
      forms/screenshots. Missing observations stay open; do not edit JSON into PASS.

## 4. Signing decision

**A — unsigned beta:** fastest; disclose observed warnings and absent signature.
**B — code signing:** stronger publisher identity; added cost/process. Signing
still does not guarantee immediate reputation or warning-free execution.
[Microsoft guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation).

There is no observed download/security result supporting a final preference yet.
Recommend A only if actual warnings are manageable, no unresolved alerts/block
remain and the owner accepts the beta experience. Recommend B if observed policy
blocks or publisher-identity needs make A unsuitable. Investigate Defender alerts;
signing is not a substitute. The owner can choose signing policy; missing security
observations are a separate open gate. Never disable Windows security for testing.

- [ ] Owner records A/B and the actual observed basis. No certificate purchase here.

## 5. Merge / version / tag / release steps

Only after evidence review and explicit owner approval:

1. Review the acceptance branch/checkpoint and remaining gate table.
2. Approve merge to main and the final version. Neither is authorized by this list.
3. If version/signature/artifact bytes change, rebuild exact sources/package and
   revalidate affected hashes, notices, install and security checks.
4. Approve tag and GitHub Release separately; provide matching source access,
   installer checksums and truthful signing/security notes.

No merge, version bump, tag, release or public installer upload is part of gate prep.
