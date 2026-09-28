# Plugin architecture: lifecycle and trust

Phase 2 provides reusable services and an explicit-profile CLI. Desktop UI,
installer servicing, a marketplace, and external tactic admission are outside
this phase. The application version and public Plugin API remain unchanged.
See [Phase 2 operations and validation](PLUGIN_PHASE2.md) and the historical
[Phase 1 runtime proof](PLUGIN_PHASE1.md).

## Boundaries

The public `chesswizard_plugin_api` exposes immutable position context, square
facts, material counts, and the factual analyzer protocol. It exposes no core
repository, database, UI, engine, or mutable application service. Core checks
returned squares/counts against its own chess board and rejects stale request
identity, different FEN, invalid inventory, unsupported values and nonfinite JSON.

Plugins are **trusted executable code with the user's permissions**. Separate
processes, controlled imports, Windows jobs and bounded transport contain ordinary
failures; they are not a hostile-code security sandbox. Hashes prove byte identity,
not publisher identity. Theme packs remain data and assets only.

V1 accepts restricted `py3-none-any` wheels containing one regular
`chesswizard_plugin_*` package, static JSON, and standard distribution metadata.
The only declared dependency is the public SDK. There is no dependency resolver,
`.pth` processing, native extension loading policy, editable install support, or
uninstall hook. The runtime import surface remains the minimal frozen-tested SDK
and built-ins; broader library/dependency support requires separate approval.

## Structure

| Layer | Modules | Responsibility |
| --- | --- | --- |
| Typed state | `plugin_models`, `plugin_state` | Receipts, requested intent, compatibility, runtime views, strict data encoding |
| Owned storage | `plugin_repository`, `plugin_locking` | Atomic bytes, containment, inventories, short state locks, invocation leases |
| Static admission | `plugin_discovery`, `plugin_compatibility`, `plugin_inspection`, `plugin_admission` | Standard metadata discovery, versions, exact receipt identity, currentness |
| Lifecycle | `plugin_installation`, `plugin_service` | Staging, publication, enable/disable, replacement, cleanup, validated facts |
| Worker boundary | `plugin_host`, `plugin_runtime`, `plugin_process`, `plugin_protocol` | Versioned transport, deadlines, cancellation, jobs and session failure state |
| Diagnostics | `plugin_diagnostics` | Bounded local core-authored failure records |

These modules are usable without Tkinter or any chess database. The separate
console host is selected explicitly in a frozen application; the desktop
executable is never used as the worker entry point.

## Independent state dimensions

`<profile>/plugins/state.json` uses host-state schema **2**, independently of
Plugin API **1** and application version. It contains:

- `installations`: published immutable receipts indexed by installation UUID.
- `requested`: selected installation, enabled intent, artifact-specific trust,
  generation and an explicit re-enable requirement, indexed by stable plugin ID.
- `transactions`: staged, validated, published or failed operation boundaries.
- `retired`: unpublished ownership receipts awaiting successful/explicit cleanup.
- `cleanup_failures`: bounded explanations for retained disabled installations.

An installed receipt contains stable ID, distribution/version, UUID, retained
wheel SHA256, canonical relative path, UTC installation time, local source
filename, manifest SHA256, required API/app versions, type/capabilities, and exact
site-relative file hashes. The receipt is also stored beside the retained wheel.
It is data only. No plugin-enabled flag is duplicated in application settings.

Compatibility distinguishes compatible, unsupported API, unmet application
minimum, Python mismatch, invalid metadata, unsupported dependency, duplicate
identity, and installation/receipt integrity failures. Proper PEP 440 version and
specifier parsing keeps application and SDK API versions independent.

Runtime views distinguish disabled, blocked, ready (not loaded), running and
failed. Enabled intent alone never authorizes execution. Admission requires a
unique indexed receipt, compatible metadata, matching receipt/artifact/file
identity, acknowledged exact artifact, current generation, and no replacement
stop request. Session failures prohibit automatic retries until explicit re-enable;
a new application session re-evaluates persisted intent and static admission.

## Discovery and collisions

A bounded metadata helper inspects one managed site at a time with the real
`importlib.metadata.entry_points(group="chesswizard.plugins")` API. It checks the
entry point's distribution association and static manifest without loading the
implementation. Descriptors are sorted by ID, distribution, version and UUID.

Every published installation claiming a duplicate ID is blocked. Nothing wins by
filesystem order. Files are preserved. Removal can specify an installation UUID;
removing the selected member of a collision leaves no implicit selection. Explicit
enablement of a now-unique installation resolves selection and requires applicable
trust. Ordinary install rejects a new conflicting artifact; replacement is explicit.

Malformed state is preserved, not silently reset. `scan()` returns recovery
findings without preventing core startup. Unknown state versions require explicit
recovery; disposable Phase 1 schema-1 profiles are not auto-migrated. Healthy
repeated scans and exact reinstall preserve state/file timestamps. Integrity
failures revoke trust and requested enablement; incompatible/conflicted enabled
installations require explicit re-enable even if compatibility later returns.

## Transaction and removal safety

Installation serializes lifecycle operations separately from short state locks:

1. Persist `staged`, retain bounded source bytes, and validate/install without code import.
2. Record exact receipt/inventory and `validated`.
3. For replacement, require the same stable ID and compatible metadata; stop old work.
4. Move staging to its UUID location and atomically publish the selected receipt.
5. Start the new artifact disabled and untrusted. Only after commit, retire/clean the old directory.

Atomic publication uses a flushed temporary file plus same-directory replacement.
No-op bytes are not rewritten. OS locks release after a crash; a lock filename
alone does not mean an active owner. A crash between directory placement and state
publication produces an unindexed directory retained for review, never executable.
Staged/failed records and unindexed directories are bounded recovery findings.
There is no automatic destructive retry or automatic activation after interruption.
An interrupted replacement barrier may require explicit state recovery before the
old selection can run; preserving uncertainty is preferable to guessing a commit.

An exact healthy artifact reinstall reuses its UUID and existing trust. Different
bytes require explicit replacement and new trust. Validation or atomic switch
failure preserves the old selected receipt and trust wherever no publication
occurred. Failed unpublished artifacts remain available for review.

Removal first persists disabled intent, cancels work, drains its invocation lease,
then unpublishes the selected receipt. Cleanup proves the exact immutable ownership
receipt, canonical UUID path, containment and absence of symlinks/junctions before
removing that one tree. It never runs plugin hooks. A cleanup failure leaves a
retired disabled receipt and diagnostic; only explicit `cleanup` retries it.
Partial cleanup with missing ownership proof requires manual review, never a
broader deletion. Chess databases, settings, libraries, themes and reviews are
outside this service's ownership.

## Process lifetime and diagnostics

Default limits are typed in `PluginLimits`: two concurrent helpers/workers per
profile, 3 seconds metadata, 5 seconds import, 10 seconds invocation, 1 second
shutdown, 1 MiB total response transport and 64 KiB discarded stderr. A bounded
state-lock wait and separate invocation leases allow disable to cancel work
without waiting behind a long analysis transaction. Kernel slot locks enforce the
worker cap across service instances/processes. Currentness polling observes
cross-process disable and replacement. No cancellation result is delivered.

On Windows the host creates a worker suspended, assigns a non-inherited
kill-on-close Job Object, then resumes it. Disable, removal, timeout, abnormal
exit, normal completion and application shutdown terminate owned descendants.
Closing the controller process also closes the job. Job assignment failure fails
closed. POSIX uses process groups for explicit cleanup; Windows is the validated
process-lifetime target, not a claim of equivalent parent-crash containment on
other platforms.

Transport uses a version, per-invocation nonce, ordered phase frames, bounded
messages, finite strict JSON, and final core fact validation. Requests have bounded
IDs/FENs. Metadata/import/invoke/shutdown each has a separate deadline. Output is
bounded even if a plugin bypasses ordinary stdout redirection. Failures become
session state with no infinite retry loop.

Local `plugins/diagnostics/events.json` retains at most 100 deduplicated records
with 512-character messages by default. Records contain known ID/version/artifact,
phase, failure category, UTC timestamp and a core-authored explanation. Raw plugin
exception text, stderr, private game history and PositionContext are not retained.
There is no telemetry or upload.

## Uninstall and release gates

Future application uninstall preserves the **entire profile by default**. Optional
full removal must be OFF by default, enumerate managed data, require explicit
confirmation, refuse external/link traversal, and prove reinstall behavior for
both preserve-data and full-removal outcomes. Phase 2 implements per-plugin removal
only; application servicing remains a later phase.

Strong isolated same-host frozen Phase 1 proof permits Phase 2 development. A
clean Windows machine without developer tools remains a **mandatory V1.5 release
gate**, together with validation of the final frozen runtime. Same-host evidence
must never be described as clean-machine certification.
