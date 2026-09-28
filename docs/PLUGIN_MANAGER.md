# Plugin Manager

Open **Tools > Plugins** from Game Review or its shared desktop menu. The manager
lists locally installed plugins; it does not download or install code on opening.
Use **Refresh / Rescan** after changes made through the CLI.

## States and actions

| Status | Meaning / next step |
| --- | --- |
| Needs approval | This exact artifact has not been acknowledged; review Enable. |
| Disabled | Requested intent is off, or explicit re-enable is needed. |
| Ready | Compatible, trusted and enabled; an explicit factual request may run. |
| Running | A factual invocation is outstanding, including initialization. |
| Failed | Worker/session or installation inspection failed; inspect Details. |
| Incompatible | The API, app, Python or dependency contract is incompatible. |
| Conflict | More than one installed distribution claims the ID; all are blocked. |

The table separately shows requested state, effective status, compatibility and
trust. A failed or incompatible plugin may retain requested Enabled intent without
being executable. Details retain the richer typed status and compatibility reason.
An empty list with a recovery message means state needs review, not a new empty
profile silently replacing corrupt data.

**Enable** shows the name, version, author, license, local source description,
artifact SHA256 and capabilities before newly installed or changed code can run.
The acknowledgement starts unchecked. Cancel makes no intent change. Approval is
bound to the displayed artifact, so replacing it while the dialog is open cannot
inherit consent. Hashes identify bytes; they do not certify the publisher.

> Plugins are executable Python code and run with your user permissions.
> They are not sandboxed.

**Disable** returns control promptly while the service persists disabled intent
and cancels/drains active workers. It leaves the installation intact. **Enable**
is also the explicit retry after a session failure. There is no automatic retry
loop, background invocation on selection, or discovery on resize.

**Details / Diagnostics** shows provenance, compatibility, failure phase and a
bounded sanitized diagnostic tail. Raw worker output, tracebacks and private game
context are not displayed. Details and result panes are resizable and scrollable;
the table has horizontal and vertical scrolling and uses system font scaling.

## Run the material-inventory reference plugin

1. Open a game in Game Review and navigate to a position.
2. Open Tools > Plugins and select the installed material-inventory plugin.
3. Review and explicitly enable it if needed.
4. Choose **Run on Current Position**.

This uses the board currently displayed in Game Review, including opening-book or
stored-line exploration. It does not use an unrelated training board or invent a
starting position when no game is loaded. Run is disabled when no position exists.

The existing service invokes a separate bounded worker and core independently
checks every square and material count. The manager renders those validated facts
as White/Black material inventory and occupied squares. Output is transient, not a
tactic, engine evaluation or persisted chess record. Navigation clears displayed
facts and discards in-flight results, even if you move away and return to the same
FEN. A state change or disable also invalidates earlier results.

## Installation and removal remain CLI operations

Use the [Phase 2 command reference](PLUGIN_PHASE2.md#entry-points) with the same
absolute user profile as the desktop. The normal profile comes from
`application_paths.application_data_directory()`; `CHESSWIZARD_DATA_DIR` overrides
it. Installation and replacement start disabled and require trust. Explicit CLI
removal deletes only the owned installation; it does not remove chess data.

No wheel-picker, removal dialog, marketplace, automatic update or new capability
is included in V1.5. Application servicing follows the [upgrade contract](UPGRADING.md). A packaged build must
include the separate approved plugin console host; a missing host produces a
bounded discovery failure rather than launching the GUI executable as a worker.
Clean-machine execution of the final frozen runtime remains a mandatory V1.5
release gate. Same-host/source tests are not clean-machine certification.

## Developer boundaries and checks

`plugin_manager_controller` owns asynchronous completion and stale-result handling;
`plugin_presentation` owns readable projections. Neither imports Tkinter or chess
storage. `merlin_ui.plugin_manager` owns only widgets and frontend events. Discovery,
compatibility, trust persistence, worker supervision and fact validation remain in
the approved shared services. No plugin receives a widget or database connection.

Run `python -B -m tools.run_tests --pattern "test_plugin*.py"` for lifecycle and UI
regressions. Tests use temporary profiles and synthetic public wheels, including
hung imports, failed metadata, crashes, incorrect facts, duplicate IDs, trust races,
corrupt state, navigation invalidation and 100/125/150% Tk scaling. Then run the full
working-tree/public-copy suites, pydoc and public-source validation as documented
in [Phase 2](PLUGIN_PHASE2.md#regression-coverage).
