# Upgrading and repairing ChessWizard

Updates are user-initiated full installers. There is no background updater,
patch service, marketplace, or self-modifying application.

Close ChessWizard normally and run the same-version installer to repair missing
or corrupt application files. Run a newer full installer to upgrade. Both keep
the separate user profile, including edited openings and plugin enablement
intent. An older installer is refused; use the installed version or a newer one.

A legacy installation without a valid ownership inventory cannot be safely
reconciled automatically. Uninstall it **keeping all data**, then install the
new managed payload. Do not delete the profile or fabricate an ownership file.

## Owned files and repair

`chesswizard-payload.json` is the versioned ownership record. Each entry identifies
a relative file, SHA256, byte count, and category. The inventory implicitly owns
itself. Build validation verifies an exact source set; installed validation allows
unknown files but never adopts them into ownership.

Preflight verifies architecture, canonical paths, app/profile separation, source
bytes, required artifacts, installed version, free space for installation and
rollback, and replaceability of existing owned files. It does not open a user DB.
A kernel lifetime gate prevents app/host startup while servicing is active.

Upgrades replace owned files and remove only obsolete previously owned files.
They preserve unknown files. A fresh reinstall can coexist with unknown files
left after uninstall, provided there is no collision with incoming ownership.
Same-version repair uses the same application identity, shortcuts, and Installed
Apps registration rather than creating duplicates.

## Failures and cancellation

Preflight refusal occurs before application mutation. Before file replacement,
a temporary application-only snapshot records the actual prior bytes, including
corrupt files if repair was requested. Supported pre-finalization cancellation
uses Inno's cancellation path, followed by verification/restoration from that
snapshot. Neither the snapshot nor rollback contains user databases or settings.

An exception in an `AfterInstall` callback alone is **not** a reliable abort;
the script explicitly requests cancellation. `/NOCANCEL` is refused because it
would disable that safety path. Silent setup never closes running applications.
Typical Inno failure codes include 7 for preflight refusal and 5 for cancellation
during installation; callers must treat **every** nonzero exit as failure.
See [Inno exit codes](https://jrsoftware.org/ishelp/topic_setupexitcodes.htm).

Inno finalizes installation before post-install work. A later smoke-test failure,
power loss, forced termination, filesystem race, or blocked rollback is not a
promise of automatic restoration. Keep the profile, close file users, and rerun
the same/newer installer to repair before launching. Never restore an old game DB
over newer user writes. The setup log records helper results and repair guidance.
The documented finalization boundary follows
[Inno's installation order](https://jrsoftware.org/ishelp/topic_installorder.htm).

## Plugin compatibility

The installer does not scan, import, enable, disable, or delete profile plugins.
Core re-evaluates metadata/API compatibility at runtime. Compatible artifacts and
requested enablement survive repair and upgrade. An incompatible plugin remains
installed, with an explicit reason and blocked effective runtime state. It cannot
execute. Existing conservative re-enable requirements still apply after an
incompatibility; servicing never silently grants trust.

## Release acceptance status

V1.5 is a validation candidate, not an approved public release. The public version
remains unchanged until owner approval. Follow the [release checklist](FIRST_PUBLIC_RELEASE_CHECKLIST.md)
for clean-Windows install, Plugin Manager, repair, upgrade, both uninstall paths,
reinstall and human 100/125/150% DPI acceptance. Automated or same-host tests do not
substitute for those observations. Test kits must be used only on a disposable clean
Windows account; synthetic versions are not application releases.
