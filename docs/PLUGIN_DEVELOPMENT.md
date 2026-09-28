# Developing a ChessWizard API V1 plugin

V1.5 supports one factual capability: material inventory with occupied-square facts.
It does not admit plugin tactics, engine evidence or direct database access. Plugins
are trusted executable Python code with user permissions, **not sandboxed**. Separate
bounded worker processes limit failures; they cannot make malicious code safe.

## Public interface

Import only from `chesswizard_plugin_api`. `PositionContext(request_id, fen)` is an
immutable six-field standard-chess position. Implement `analyze(context) -> MaterialFacts`
and `close() -> None`, and export a factory returning the `AnalyzerPlugin` protocol.
`MaterialFacts` must echo the request ID and FEN, contain a tuple of `SquareFact` for
every occupied square, and twelve `MaterialCount` entries (both colors, all six piece
types, including zero counts). Values are immutable dataclasses. Core independently
checks exact squares, counts and request identity before displaying facts. No plugin
receives a UI object, game record, database, engine handle or writable core service.

Use explicit annotations and Google-style API docstrings. Keep imports and factories
free of side effects. Do not depend on private application modules. The currently
frozen-tested import surface is the public SDK and Python built-ins; even additional
standard-library imports require a separately reviewed runtime contract.

## Distribution contract

Build a pure-Python `py3-none-any` wheel with one regular top-level package named
`chesswizard_plugin_<name>` (the SDK name is reserved). Native extensions, scripts,
`.pth` files, editable installations and arbitrary dependencies are refused. The SDK
is the only allowed declared dependency. The current runtime uses CPython 3.14.

Example `pyproject.toml` fields for an independently owned plugin:

```toml
[build-system]
requires = ["setuptools==84.0.0"]
build-backend = "setuptools.build_meta"

[project]
name = "example-chesswizard-inventory"
version = "1.0.0"
requires-python = ">=3.14,<3.15"
dependencies = ["chesswizard-plugin-api>=1.0,<2.0"]
authors = [{name = "Example contributors"}]
license = "GPL-3.0-or-later"

[project.entry-points."chesswizard.plugins"]
"org.example.inventory" = "chesswizard_plugin_inventory:create_plugin"

[tool.setuptools.package-data]
chesswizard_plugin_inventory = ["chesswizard-plugin.json"]
```

Include the static manifest at `<package>/chesswizard-plugin.json`:

```json
{
  "schema_version": 1,
  "plugin_id": "org.example.inventory",
  "display_name": "Example material inventory",
  "minimum_app_version": "1.0.0-beta",
  "api_version": "1.0.0",
  "type": "position_facts",
  "capabilities": ["material_inventory"]
}
```

The plugin ID must match the entry-point name. Version, author, license, Python and
SDK requirements come from wheel metadata. Discovery reads real entry-point metadata
without importing the implementation. Compatibility is rechecked before execution.

## Build independently

The ChessWizard root `pyproject.toml` builds only the SDK, never the desktop. With the
pinned build dependencies from the [Windows build guide](../packaging/windows/README.md):

```powershell
python -m pip wheel --no-deps --no-build-isolation --wheel-dir sdk-dist .
```

Install that SDK wheel into the external plugin's disposable development environment.
Build the separate plugin project afterward with the same wheel command from its own
root. Run its synthetic tests against the SDK without a ChessWizard checkout on the
import path. Do not put the implementation into the frozen application, hidden imports,
or shared application packages. The external material-inventory reference is distributed
separately in the acceptance kit, alongside its source; its implementation is not core.

## Install, trust, invoke and remove

The frozen desktop includes `ChessWizardPluginHost.exe`. For a disposable clean test
account, use an absolute profile matching the desktop (normally the following path):

```powershell
$profilePath = Join-Path $env:LOCALAPPDATA 'ChessWizard'
$pluginHost = Join-Path $env:LOCALAPPDATA 'Programs/ChessWizard/ChessWizardPluginHost.exe'
& $pluginHost install .\example.whl --profile $profilePath
& $pluginHost list --profile $profilePath
```

Installation starts disabled. Import a synthetic game, navigate to a position, open
**Tools > Plugins**, and select the plugin. Review the publisher description, artifact
hash and capability; explicitly acknowledge code trust to enable. Use **Run on Current
Position**. Disable it and verify Run is unavailable; restart and check the persisted
state. The [Plugin Manager guide](PLUGIN_MANAGER.md) explains statuses and stale results.

```powershell
& $pluginHost remove org.example.inventory --profile $profilePath
```

Install/remove are CLI operations in V1.5, not a wheel-picker UI. Do not confuse removal
of one plugin with full profile deletion. The [CLI reference](PLUGIN_PHASE2.md#entry-points)
includes explicit invocation, replacement and cleanup. A changed artifact requires new
trust even if it claims the same version. Compatible upgrades preserve intent; incompatible
plugins remain installed but cannot execute. See [upgrading](UPGRADING.md).

## Validation and release limits

Run `tools/run_tests.py --pattern "test_plugin*.py"`, full working/public-copy tests,
`tools/check_pydoc.py` and `tools/build_pydoc.py` from the core checkout. External authors
also test malformed output, exact request/FEN identity, counts and close behavior in
their own project. Do not run Stockfish for this factual capability.

Source tests and same-host isolation do not certify a clean Windows runtime. The final
consumer installer and independently built wheel must pass the [release checklist](FIRST_PUBLIC_RELEASE_CHECKLIST.md)
on a genuinely clean machine with no development tools required. No marketplace,
automatic plugin update, expanded import surface or third-party dependency resolution
is promised by API V1.
