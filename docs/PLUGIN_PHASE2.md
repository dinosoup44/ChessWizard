# Plugin Phase 2: lifecycle and state

Phase 2 adds durable lifecycle services and CLI operations. It does not activate
plugins in the desktop, build Plugin Manager UI, implement installer servicing,
change the application/API version, or admit external tactical conclusions.
See the [architecture and safety contract](PLUGIN_ARCHITECTURE.md).

## Entry points

`PluginService(profile, limits)` is the frontend-independent orchestration entry.
Use `scan()` for typed `DiscoverySnapshot`/`PluginView` results and recovery
messages. `list_plugins()` is a compact compatibility projection. `install`,
`replace`, `set_enabled`, `analyze`, `remove`, `cleanup` and `close` are explicit
operations. Constructors do not write or start workers. Call `close()` when the
application exits; current generation checks also discard superseded work.

All lifecycle operations require an explicit absolute profile outside the core
installation/source directory. Use disposable profiles for development:

```text
python -B plugin_host.py install sample.whl --profile <absolute-disposable-profile>
python -B plugin_host.py list --profile <absolute-disposable-profile>
python -B plugin_host.py enable org.example.inventory --acknowledge-code-trust --profile <absolute-disposable-profile>
python -B plugin_host.py analyze org.example.inventory --fen "4k3/8/8/8/8/8/4Q3/4K3 w - - 0 1" --profile <absolute-disposable-profile>
python -B plugin_host.py disable org.example.inventory --profile <absolute-disposable-profile>
python -B plugin_host.py replace org.example.inventory --wheel replacement.whl --profile <absolute-disposable-profile>
python -B plugin_host.py remove org.example.inventory --profile <absolute-disposable-profile>
python -B plugin_host.py cleanup <retired-installation-uuid> --profile <absolute-disposable-profile>
```

The optional frozen console host offers the same commands. Phase 1's previously
built portable validation kit remains historical evidence; changing source does
not update that kit or certify a new frozen build.

## Operational behavior

- New installation is disabled. Enable checks static metadata, identity and explicit
  exact-artifact trust without importing the implementation.
- Healthy exact reinstall retains UUID, trust, bytes and timestamps.
- Different artifacts require `replace`; unchanged ID/version strings do not
  transfer trust. In-place file/retained-wheel changes revoke trust and enablement.
- Requested intent, compatibility and effective runtime state remain separate.
  Failed workers latch for the session; explicit re-enable allows another attempt.
- Disable persists intent and cancels active work through a separate channel.
  Cross-process callers observe generation changes without a long-held state lock.
- Duplicate IDs block every claimant and preserve files. Explicit removal can use
  `--installation-id`; unresolved selection remains disabled.
- Failed or interrupted publication remains in transactions/staging for review.
  No plugin becomes executable merely because its directory exists.
- Removal unpublishes first and deletes only a receipt-proven owned tree. Failed
  cleanup stays retired/disabled and never retries automatically on startup/rescan.
- Corrupt or unsupported state is reported and preserved. Recovery must never
  silently replace it with empty enabled state. Legacy disposable schema-1 spike
  profiles require explicit review/recreation rather than an implicit migration.

Limits are supplied through the shared typed `PluginLimits` model. Frontends must
not invent another enabled-state store or bypass the service/admission boundary.
The [Phase 3 Plugin Manager](PLUGIN_MANAGER.md) consumes these typed views without
owning version parsing, filesystem ownership, trust, subprocesses, or factual
validation. Its enable request binds approval to the displayed artifact SHA256;
a replacement after review requires another review. CLI behavior is unchanged.

## Regression coverage

All fixtures are synthetic public-source files under `tests/support`; none depend
on an external checkout, owner profile, historical game, engine, or private report.

- Atomic state persistence, corruption preservation, restart and no-op timestamps.
- Deterministic static metadata, missing/malformed manifests, distribution contracts,
  proper version ordering, Python/API/application/dependency/capability checks.
- Duplicate IDs, explicit resolution, artifact/site/receipt tampering and trust.
- Interrupted and unindexed staging, failed replacement, atomic switch failure,
  exact reinstall, successful replacement and required new trust.
- Owned removal, protected unrelated-data sentinels, cleanup failure/retry, canonical
  archive paths, traversal, case collisions, Windows junction rejection.
- Metadata deadline, import exception/SystemExit, import/call/close hangs, abnormal
  exit, malformed/oversized/nonfinite transport, wrong context and contract version.
- Session failure latch, bounded/redacted diagnostics, explicit retry and worker cap.
- Real synthetic child-process cleanup on disable, timeout, removal, replacement,
  normal return, application close, and abnormal controller exit on Windows.
- Cross-process disable, separate frozen console-host routing, and no Tkinter or
  chess-storage dependency in reusable plugin modules.

Validation commands:

```text
python -B -m tools.run_tests --pattern "test_plugin*.py"
python -B -m tools.run_tests
python -B -m tools.check_public_copy
python -B -m tools.check_pydoc
python -B -m tools.public_source
```

`tools.run_tests` provides an isolated profile and forbids real Stockfish launches.
The external reference plugin also retains independent tests against the unchanged
public SDK. The public-copy check uses exactly the public manifest, with no owner
or private files. Durable run counts, platform details and protected-file integrity
results are recorded in the local Phase 2 validation report, which is not a public
source dependency.

## Owner review boundary

Phase 2 ends at reviewed service/CLI behavior. Do not proceed to Plugin Manager UI,
installer servicing, version changes, other plugin capabilities, or V2 features
without separate approval. Phase 3 UI now has that approval; installer servicing
and version changes do not. Main is not merged as part of these checkpoints. The
clean-Windows release gate remains outstanding regardless of source test results.
