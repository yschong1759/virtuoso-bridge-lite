# CLAUDE.md

The canonical agent guide is [AGENTS.md](AGENTS.md). It holds the Lite
boundary, the operational rules for shared Virtuoso sessions and the
verification requirements. Follow it; this file only adds a map of the code.

@AGENTS.md

## What this project is

`virtuoso-bridge` lets Python, SKILL or the CLI drive Cadence Virtuoso and run
Spectre, either locally or on a remote server reached over SSH. Virtuoso,
Spectre and foundry PDKs are licensed tools and are not available here. Most
work and all CI tests are offline.

## Architecture at a glance

- **Client side** (`src/virtuoso_bridge/`)
  - `virtuoso/basic/bridge.py`: `VirtuosoClient`, the main SKILL execution API.
    Public exports are listed in `__init__.py`.
  - `transport/`: SSH tunnels (`tunnel.py`, `ssh.py`, the optional
    `paramiko_backend.py`), file transfer and remote host roles. Host role
    vocabulary (GUI, daemon, deployment and Spectre host) is defined in
    [CONTEXT.md](CONTEXT.md) and ADR 0001.
  - `spectre/`: `SpectreSimulator`/`SpectrePool` runner plus PSF parsers.
    This part works without a Virtuoso daemon.
  - `virtuoso/{schematic,symbol,layout,maestro,library,sos}/`: lightweight
    wrappers for common operations. Raw SKILL remains the escape hatch.
  - `cli.py`: the `virtuoso-bridge` console entrypoint (`init`, `start`,
    `status`, `eval`, `load`, `doctor`, `profile`, dialog/window tools, and
    others).
  - `env.py`, `profile.py`, `instance_discovery.py`, `daemon_auth.py`:
    configuration (`~/.virtuoso-bridge/.env`), profiles, opt-in automatic
    sessions (`VB_AUTO_SESSIONS`) and signed daemon authentication.
  - `resources/` (top-level package dir, not the server one below): client-side
    X11 dialog helpers (`x11_dialog_close.py`, `x11_dismiss_dialog.py`).
- **Server side** (`virtuoso/basic/resources/`): the files deployed to the
  Cadence host. `ramic_bridge.il` is loaded in the CIW, which starts the RAMIC
  daemon through `ipcBeginProcess()`. There are two daemon variants,
  `ramic_bridge_daemon_3.py` and `ramic_bridge_daemon_27.py`, plus helper
  modules (`ramic_deploy.py`, `ramic_registry.py`, `ramic_owner.py`,
  `ramic_paths.py`, `ramic_request_recovery.py`). **Changes to the daemon or
  its helper modules must stay Python 2.7 compatible**, because CI runs real
  2.7 workers against them.
- `mcp_server.py` and `mcp/`: an MCP server that exposes the bridge (`mcp/`
  holds an example config and smoke tests).
- `tools/` (`signoff.py`, `skill_exec.py`, `record_cadence_fixtures.py`) and
  `scripts/` (`fix-symlinks.sh`, `track_traffic.py`): standalone helpers.
- `CONTEXT.md`: domain vocabulary.
- `skills/`: agent skills (virtuoso, spectre, netlist, optimizer, search) with
  references. Read only the one that applies (see AGENTS.md).
- `docs/`: the static website and guide (`docs/guide/index.html`), ADRs in
  `docs/adr/`, and agent process notes in `docs/agents/`. `website/` is a
  separate npm package (`npm ci && npm run check && npm test && npm run build`).

## Common commands

Python `>=3.9`. CI (`.github/workflows/tests.yml`) runs Linux on Python 3.9 and
3.13. Only the 3.13 job builds a pinned CPython 2.7.18 worker, passed in as
`VB_TEST_WORKER_PYTHON`, for the native daemon checks.

```bash
uv venv .venv && source .venv/bin/activate && uv pip install -e .
```

```bash
uv run --extra dev pytest                      # full offline suite
```

```bash
uv run --extra dev pytest tests/test_cli_eval.py -q   # single file
```

```bash
python3 tests/native_instance_registry.py src/virtuoso_bridge/virtuoso/basic/resources
```

```bash
python3 tests/native_daemon_concurrency.py src/virtuoso_bridge/virtuoso/basic/resources
```

X11 dialog native test (needs `xvfb`, `libx11-6`, `libxext6`, `libxtst6`):

```bash
uv run --extra dev python tests/test_x11_dialog_close_native.py -v
```

```bash
uv build
```

Live tests (`test_bridge_live*.py`, `test_geometry_regressions_live.py`) need a
real Virtuoso session and are run by hand. See [tests/README.md](tests/README.md).

## Reminders

- Read [ADR 0003](docs/adr/0003-lite-default-optional-advanced-config.md)
  before adding configuration or workflow abstractions. Keep one-host defaults
  working with no migration.
- Never commit `.env`, lab output or PDK data.
- Report what was tested offline separately from anything verified on real
  Cadence/PDK hardware.
