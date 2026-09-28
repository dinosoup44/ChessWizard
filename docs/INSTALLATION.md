# Installing ChessWizard on Windows

ChessWizard uses a per-user Inno Setup installer around a PyInstaller ONEDIR
application. Administrator privileges, Python, Git, and an editor are not required.
The supported runtime is Windows 10/11 AMD64; the bundled analysis engine also
requires AVX2. Installing does not start an engine or migrate a game database.

Run the complete installer from a trusted distribution. The Desktop shortcut is
selected by default; the Start Menu entry and Windows Installed Apps entry use
the same application identity. Close ChessWizard normally before installation,
repair, upgrade, or removal. Finish unsaved work and allow plugin workers to drain.
Setup does not terminate the app, even in silent mode.

| Content | Location |
| --- | --- |
| Application, runtime, plugin host, notices | `%LOCALAPPDATA%\Programs\ChessWizard` |
| Games, settings, training, reviews, openings, themes, caches, plugins | `%LOCALAPPDATA%\ChessWizard` |

The application directory is installer-owned. Do not put editable opening books
or other personal content there. Unknown files are preserved, and collisions
with new application files are refused rather than overwritten.

## Removing ChessWizard

The default is **Your ChessWizard data will be kept.** Removal deletes the
application, its runtime/hosts, owned shortcuts, and Installed Apps registration.
Games, settings, authored openings, themes, caches, reviews/training, installed
plugins, plugin state, and diagnostics remain available to a later reinstall.
Silent uninstall always preserves data.

**Also remove all local ChessWizard data** is unchecked by default. Selecting it
requires a second confirmation naming the managed profile and the categories
being permanently deleted. The helper enumerates the files first and checks that
the confirmed contents have not changed. Full removal cannot be undone and is
not part of application rollback. If deletion itself fails, it may be partial;
read the uninstall log rather than assuming a recovery copy exists.

Automatic deletion refuses custom `CHESSWIZARD_DATA_DIR` locations, links,
junctions, traversal, broad/system/home roots, or app/profile overlap. Keep data
and review a custom location manually. It never follows plugin-owned links into
external directories. Reinstall after full removal creates a fresh profile.

## Unsigned builds

The local release-candidate installer is unsigned. Windows may show publisher or
reputation warnings, especially for a new or infrequently downloaded build.
An unsigned local install is not evidence about the Internet-download/Mark of
the Web experience. Microsoft describes reputation checks and warning behavior
in its [SmartScreen documentation](https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/).
Do not disable Windows security to install ChessWizard. Signing and downloaded
installer acceptance remain explicit release-readiness decisions; this phase
neither acquires a certificate nor publishes a release.

See [upgrades and repair](UPGRADING.md) and [first run](FIRST_RUN.md).

## Release acceptance status

V1.5 is a validation candidate, not an approved public release. The public version
remains unchanged until owner approval. Follow the [release checklist](FIRST_PUBLIC_RELEASE_CHECKLIST.md)
for clean-Windows install, Plugin Manager, repair, upgrade, both uninstall paths,
reinstall and human 100/125/150% DPI acceptance. Automated or same-host tests do not
substitute for those observations. Test kits must be used only on a disposable clean
Windows account; synthetic versions are not application releases.
