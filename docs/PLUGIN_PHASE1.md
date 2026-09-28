# Plugin runtime and contract spike (Phase 1)

This records the historical opt-in runtime spike. Current source lifecycle behavior
is documented in [Phase 2](PLUGIN_PHASE2.md) and the
[plugin architecture](PLUGIN_ARCHITECTURE.md). This is not a released feature.
ChessWizard remains at its existing application version. No Plugin Manager UI or
installer servicing is enabled.

The public `chesswizard_plugin_api` package provides immutable position, square,
and material-count models plus an analyzer protocol. The SDK package lives at the
source root, like other shared Python packages, so source-only tests and pydoc
need no editable installation or external checkout. The root `pyproject.toml`
builds **only this SDK**, not the ChessWizard desktop application.

The opt-in frozen build contains a console host. After that build, a separate
external project builds a pure-Python wheel. Its entry point group is
`chesswizard.plugins`; its regular top-level package must be named
`chesswizard_plugin_<name>` (excluding the reserved SDK name). This narrow
namespace restriction prevents accidental host-module shadowing. V1 permits
Python and static JSON package files, standard distribution metadata, and only
the public SDK dependency. No third-party dependency resolution, scripts,
native extensions, .pth hooks, editable installs, or theme-pack code.

The manifest is `<package>/chesswizard-plugin.json`, schema version 1, with
`plugin_id`, `display_name`, `minimum_app_version`, `api_version`,
`type: position_facts`, and `capabilities: [material_inventory]`.
ID must match the entry-point name. Distribution metadata supplies version,
author, license, Python requirement, and SDK compatibility. Discovery uses
real PyPA metadata without importing the package.

All spike commands require an explicit absolute disposable profile:

```text
ChessWizardPluginHost.exe install sample.whl --profile <absolute-profile>
ChessWizardPluginHost.exe list --profile <absolute-profile>
ChessWizardPluginHost.exe enable <id> --acknowledge-code-trust --profile <absolute-profile>
ChessWizardPluginHost.exe analyze <id> --fen "<six-field-FEN>" --profile <absolute-profile>
ChessWizardPluginHost.exe disable <id> --profile <absolute-profile>
ChessWizardPluginHost.exe remove <id> --profile <absolute-profile>
```

Packages are installed disabled beneath `plugins/installations/<opaque-id>/site-packages`.
Receipts retain exact installed file hashes. An identical install/state change
does not rewrite existing bytes. Package changes require reinstall/trust review.
A worker imports only the selected package and returns bounded JSON. Core uses
its chess board representation to check every square/count and request identity.
Plugin results cannot create tactics, evidence-cache rows, or database writes.

**Plugins are executable code with the user's permissions, not sandboxed.**
Explicit acknowledgement is required to enable. Process isolation and time/output
limits contain ordinary failures, not malicious filesystem or process activity.

Phase 1 intentionally has one explicit invocation at a time and a fail-closed
operation lock. Interrupted locks require review. Duplicate installation IDs are
rejected without changing the existing installation; general multi-plugin
conflict UI and transactional recovery belong to the next phase. Installation
does not execute plugin code. Metadata incompatibility prevents activation.
Disable returns only after any currently held operation lock is available
(or reports busy); successful disable permits no further invocation.

No UI, core analyzer changes, installer servicing, or production profile migration
are included. The minimal supported plugin import surface is the SDK and Python
built-ins; the external reference uses only that surface. Broader standard-library
support must be separately declared and frozen-tested.

## Uninstall contract amendment

Future application uninstall preserves the full profile by default. An optional
clearly labelled full-removal choice is OFF by default, enumerates all managed
data to delete, and requires separate explicit confirmation. It must never follow
links or plugin-owned paths outside the selected managed profile. Both outcomes,
cancelled confirmation, containment attacks, and correct reinstall must be tested.
This phase implements only removal of a specific managed plugin, not application
uninstall or profile deletion.

## Build and proof boundary

Use the existing Windows build with `-PluginSpike` and a distinct rehearsal name.
The plugin implementation must not exist in either frozen PYZ. Build the external
sample afterward; never add it to hidden imports or collect its source.

A same-host disposable profile with sanitized PATH demonstrates useful isolation
but **does not certify a clean Windows machine without installed developer tools**.
The approved strong same-host isolation proof permits Phase 2 implementation.
Running the final portable runtime on such a clean environment remains a mandatory
V1.5 release gate.
Do not enable unsupported environments or broaden dependency rules to bypass it.

The host uses [PyPA installer](https://installer.pypa.io/en/stable/) for validated
wheel installation and [importlib.metadata](https://docs.python.org/3/library/importlib.metadata.html)
for discovery. New helper dependencies are pinned in the spike requirements and
their original licenses travel with the rehearsal. This is not distribution approval.
The normal source requirements include the two host-side dependencies used by
public tests and pydoc. The opt-in build dependency list pins them separately
for the frozen rehearsal. Neither expands the allowed plugin dependency set.
