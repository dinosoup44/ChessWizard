# Distribution and servicing architecture

The approved path is PyInstaller ONEDIR plus per-user Inno Setup. The canonical
release version remains `chesswizard_version.VERSION`; Phase 4 does not bump it.
The consumer AppId remains `{67CE3406-96D1-4EB6-AF71-3C95D925CF8B}`.

| Layer | Responsibility |
| --- | --- |
| `application_lifetime` | Desktop/host activity markers and atomic startup/servicing gate |
| `servicing_paths` | Canonical roots, traversal/reparse rejection, bounded test roots |
| `servicing_inventory` | Versioned exact payload ownership and hash validation |
| `servicing_transaction` | Preflight, app-only snapshot, verification, stale cleanup, rollback |
| `servicing_profile` | Separately confirmed canonical profile deletion |
| `servicing_host` | Frozen CLI boundary used by Inno; no UI, DB, plugin execution, or engine |
| `ChessWizard.iss` | Setup lifecycle, shortcuts/registration, user choices and finalization |

Reusable services have no Tkinter dependencies. They can be tested without the
frontend or a game DB. Mutable user content remains outside the application
payload. The installer never calls analysis, import, database migration, or plugin
installation services.

## Lifetime handshake

Every desktop and plugin-host process retains a Windows activity-mutex handle
until process termination. The identity is a SHA256 of the normalized installation
path's UTF-16LE bytes, shared with Inno. Global kernel names cover other Windows
sessions using the same installation; the installation path still separates users.
Under a short gate, startup refuses an
existing servicing marker; setup refuses activity before retaining its own marker.
This closes the check/start race and isolates separate disposable installations.
Normal plugin cancellation/Job Object cleanup remains owned by the plugin runtime.
Setup asks the user to close processes; it does not kill them. The servicing
marker is released after finalization, before the Finished page can launch the
guarded desktop; release at `ssDone` would be too late for that action.

## Build and ownership

`tools.payload_inventory` creates schema-1 `chesswizard-payload.json` from explicit
frozen inputs. `tools.build_installer` validates it and the pinned Inno compiler
before compilation. The installer extracts its own payload into a temporary
staging directory and runs that copy of the servicing helper, so a corrupt old
installation is not needed for repair preflight.

Application files use normal Inno file ownership. A final file callback verifies
the installed inventory and performs stale-owned-file cleanup before finalization.
The old application snapshot is retained until setup ends. Unknown files are not
part of rollback or deletion. Hashes detect changed bytes; they are not signatures
and do not sandbox code running as the same Windows user.

The desktop, plugin host, and servicing helper have separate frozen archives.
The exact package audit inspects every archive and accounts for installer 0.7.0,
packaging 26.3, public SDK code, and all retained runtime/asset notices.

## Isolated validation and release gates

The harness requires explicit install/profile roots under a newly marked
`chesswizard-servicing-*` temporary directory. Its synthetic installers use a
separate deterministic fixture AppId and fixture-only shortcut locations. Test
failure/full-removal switches are compiled only for that validated fixture.
Consumer installers do not contain those switches. Test builds alone can replace
version/API literals in generated build inputs; tracked release sources are unchanged.

The synthetic sequence is 1.5.0/API1, 1.5.1/API1, 2.0.0/API1, and 2.0.0/API2.
These are servicing/compatibility simulations, not released versions or V2 features.
Strong same-host isolation does not certify a clean machine. Clean-Windows install,
repair, upgrade, both uninstall choices, reinstall, downloaded/unsigned prompts,
and human visual acceptance remain mandatory release gates.

See [installation](INSTALLATION.md), [upgrade boundaries](UPGRADING.md), and the
[Windows build and validation instructions](../packaging/windows/README.md).

## Plugin state during cancellation

Windows readers can briefly prevent atomic replacement of `state.json` while
workers check their current generation. Publication waits only for recognized
Windows access/sharing failures, using the existing typed `PluginLimits`
lock deadline and polling interval. It never deletes the previous generation
first. Persistent locks expire with an error; other failures are not retried.
The state reader remains bounded and does not acquire the writer lock, avoiding
a cancellation deadlock. Trust, generation checks and factual results are unchanged.

## Portable consumer acceptance builds

`tools.build_installer --acceptance-only` permits a synthetic build identity after
checking the frozen console host against the ownership inventory. This uses the
normal consumer AppId and canonical per-user paths, without `FixtureRoot` or any
fixture-only failure/full-removal switches. Never install these on an everyday profile.
The acceptance-build receipt binds the installer and inventory hashes to the actual
frozen version. The ordinary build path still requires the central public version.

The existing spec generates synthetic identities only for explicitly named servicing
rehearsals. The payload inventory supplies the installer version; do not hand-edit
packaged metadata. The final candidate uses the unchanged public version, while
1.5.0/1.5.1 and 2.0 API1/API2 are upgrade simulations. Neither changes tracked runtime
version sources. The portable kit contains separate installers, an independently
built external plugin, synthetic PGN and pending manual receipt. No fixture results
can certify consumer UI, SmartScreen or a clean machine.
