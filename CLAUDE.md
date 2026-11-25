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
- **Server side** (`virtuoso/basic/resources/`): the files deployed to the
  Cadence host. `ramic_bridge.il` is loaded in the CIW, which starts the RAMIC
  daemon through `ipcBeginProcess()`. There are two daemon variants,
  `ramic_bridge_daemon_3.py` and `ramic_bridge_daemon_27.py`. **Changes to the
  daemon or its helper modules (`ramic_*.py`) must stay Python 2.7 compatible**,
  because CI runs real 2.7 workers against them.
- `mcp_server.py` and `mcp/`: an MCP server that exposes the bridge.
- `skills/`: agent skills (virtuoso, spectre, netlist, optimizer, search) with
  references. Read only the one that applies (see AGENTS.md).
- `docs/`: the static website and guide (`docs/guide/index.html`), ADRs in
  `docs/adr/`, and agent process notes in `docs/agents/`. `website/` is a
  separate npm package (`npm ci && npm run check && npm test && npm run build`).

## Common commands

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

Live tests (`test_bridge_live*.py`, `test_geometry_regressions_live.py`) need a
real Virtuoso session and are run by hand. See [tests/README.md](tests/README.md).

## Reminders

- Read [ADR 0003](docs/adr/0003-lite-default-optional-advanced-config.md)
  before adding configuration or workflow abstractions. Keep one-host defaults
  working with no migration.
- Never commit `.env`, lab output or PDK data.
- Report what was tested offline separately from anything verified on real
  Cadence/PDK hardware.
