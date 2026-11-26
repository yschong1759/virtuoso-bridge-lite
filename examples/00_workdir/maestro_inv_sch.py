#!/usr/bin/env python3
"""Set up and run a Maestro transient test on tb_inv_sch, then measure VOUT.

Steps:
  1. Open <LIB>/tb_inv_sch/maestro in the background, add a TRAN test
     (spectre, transient 0 to 1000 ns) with VIN and VOUT as outputs, and save.
  2. Open Maestro in GUI mode, run the simulation and wait for it to finish.
  3. Report where the simulation database (PSF results) is.
  4. Read VIN and VOUT from that database and plot them (PNG).
  5. Measure every VOUT rise and fall time (10 % to 90 % of the VOUT swing),
     print them with their averages and save them to a CSV file.

Run sim_inv_sch.py first so <LIB>/tb_inv_sch/schematic exists.

Usage::

    python maestro_inv_sch.py <LIB>
    python maestro_inv_sch.py <LIB> --model-file /path/to/models.scs:tt

The inverter's transistors need device models. If the library's Maestro
setup does not already provide them, pass --model-file PATH[:SECTION]
(repeatable). Plotting needs matplotlib in the Python environment you run
this script from.

Prerequisites:
  - virtuoso-bridge service running (virtuoso-bridge start)
  - Spectre licence on the Virtuoso host
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.ops import escape_skill_string

SIGNALS = ("VIN", "VOUT")
LOW_FRACTION, HIGH_FRACTION = 0.1, 0.9


# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Maestro transient run and VOUT edge analysis for tb_inv_sch.")
    parser.add_argument("lib", help="library holding the testbench")
    parser.add_argument("--tb-cell", default="tb_inv_sch", help="testbench cell")
    parser.add_argument("--test", default="TRAN", help="Maestro test name")
    parser.add_argument("--stop", default="1000n", help="transient stop time")
    parser.add_argument("--model-file", action="append", default=[], metavar="PATH[:SECTION]",
                        help="Spectre model file for the test, optionally with a section")
    parser.add_argument("--out-dir", type=Path, default=here / "output",
                        help="local folder for the waveform files, plot and edge table")
    parser.add_argument("--timeout", type=int, default=1800, help="simulation timeout in seconds")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Maestro setup and run
# ---------------------------------------------------------------------------

def _q(text: str) -> str:
    return f'"{escape_skill_string(text)}"'


def _skill(client: VirtuosoClient, expr: str, timeout: int = 60) -> str:
    result = client.execute_skill(expr, timeout=timeout)
    if getattr(result, "errors", None):
        raise RuntimeError(f"SKILL failed: {expr}\n{result.errors}")
    return (result.output or "").strip()


def _model_files_option(specs: list[str]) -> str:
    entries = []
    for spec in specs:
        path, _, section = spec.partition(":")
        entries.append(f"({_q(path)} {_q(section)})")
    return f'(("modelFiles" ({" ".join(entries)})))'


def setup_maestro(client: VirtuosoClient, args: argparse.Namespace) -> None:
    lib, cell, test = args.lib, args.tb_cell, args.test
    if _skill(client, f"ddGetObj({_q(lib)} {_q(cell)} {_q('schematic')}) != nil") != "t":
        raise SystemExit(f"{lib}/{cell}/schematic does not exist; run sim_inv_sch.py first.")

    session = client.maestro.open_session(lib, cell)
    try:
        tests = _skill(client, f"maeGetSetup(?session {_q(session)})")
        if f'"{test}"' in tests:
            print(f"[setup] Reusing existing test {test}; updating its transient settings")
        else:
            client.maestro.create_test(test, lib=lib, cell=cell, session=session)
            print(f"[setup] Created test {test} ({lib}/{cell}/schematic, spectre)")

        client.maestro.set_analysis(
            test, "tran",
            options=f'(("stop" {_q(args.stop)}) ("errpreset" "moderate"))',
            session=session,
        )
        for name in SIGNALS:
            # maeAddOutput keeps an existing output of the same name unchanged.
            client.maestro.add_output(name, test, output_type="net",
                                      signal_name=f"/{name}", session=session)
        if args.model_file:
            client.maestro.set_env_option(test, _model_files_option(args.model_file), session=session)
            print(f"[setup] Model files: {', '.join(args.model_file)}")

        client.maestro.save_setup(lib, cell, session=session)
        print(f"[setup] Saved {lib}/{cell}/maestro: tran stop={args.stop}, outputs {', '.join(SIGNALS)}")
    finally:
        client.maestro.close_session(session)


def results_location(client: VirtuosoClient, lib: str, cell: str, history: str) -> tuple[str, str]:
    """Return (PSF results directory, library history directory) for *history*."""
    _skill(client, f"maeOpenResults(?history {_q(history)})")
    try:
        psf_dir = _skill(client, "asiGetResultsDir(asiGetCurrentSession())").strip('"')
    finally:
        _skill(client, "maeCloseResults()")
    if not psf_dir or psf_dir == "nil" or "tmpADE" in psf_dir:
        raise RuntimeError(f"No results directory found for history {history}")
    lib_path = _skill(client, f"ddGetObj({_q(lib)})~>readPath").strip('"')
    return psf_dir, f"{lib_path}/{cell}/maestro/results/maestro/{history}"


def _report_point_status(client: VirtuosoClient, lib: str, cell: str, history: str) -> None:
    """Print Spectre log status per point (only on bridge versions that have check_points)."""
    check_points = getattr(client.maestro, "check_points", None)
    if check_points is None:
        return
    for point in check_points(history, lib=lib, cell=cell):
        print(f"[sim] point {point['point'] or '?'}: {point['status']} ({point['log']})")
        for error in point["errors"]:
            print(f"        {error}")
        if point["status"] == "failed":
            raise SystemExit("Spectre reported errors; see the log lines above.")


# ---------------------------------------------------------------------------
# Waveforms
# ---------------------------------------------------------------------------

def read_ocnprint(path: Path) -> tuple[list[float], list[float]]:
    """Read a two-column ocnPrint table (time, value) into two lists."""
    times, values = [], []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            t, v = float(parts[0]), float(parts[1])
        except ValueError:
            continue  # header lines
        times.append(t)
        values.append(v)
    if not times:
        raise RuntimeError(f"No waveform data in {path}")
    return times, values


def plot_waveforms(path: Path, waves: dict[str, tuple[list[float], list[float]]], title: str) -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[plot] matplotlib is not installed; skipping the plot (pip install matplotlib)")
        return
    fig, axes = plt.subplots(len(waves), 1, figsize=(11, 6), dpi=150, sharex=True)
    for ax, (name, (t, v)), color in zip(axes, waves.items(), ("#1f77b4", "#d62728")):
        ax.plot([x * 1e9 for x in t], v, color=color, linewidth=1.2)
        ax.set_ylabel(f"{name} (V)")
        ax.grid(True, color="#d9d9d9", linewidth=0.8)
    axes[-1].set_xlabel("Time (ns)")
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"[plot] {path}")


# ---------------------------------------------------------------------------
# Edge analysis
# ---------------------------------------------------------------------------

def _crossings(t: list[float], v: list[float], level: float) -> list[tuple[float, int]]:
    """Linear-interpolated crossings of *level*: (time, +1 rising / -1 falling)."""
    found = []
    for i in range(1, len(v)):
        v0, v1 = v[i - 1], v[i]
        if v0 < level <= v1 or v0 > level >= v1:
            frac = (level - v0) / (v1 - v0)
            found.append((t[i - 1] + frac * (t[i] - t[i - 1]), 1 if v1 > v0 else -1))
    return found


def measure_edges(t: list[float], v: list[float]) -> tuple[list[dict], float, float]:
    """Every complete rise and fall of *v*, measured between 10 % and 90 % of its swing.

    Returns (edges, low threshold, high threshold). Each edge is
    {"type": "rise"|"fall", "start": s, "end": s, "time": s}. An edge counts
    only if the signal crosses both thresholds without turning back.
    """
    vmin, vmax = min(v), max(v)
    swing = vmax - vmin
    if swing <= 0:
        raise RuntimeError("VOUT does not switch; no edges to measure")
    low, high = vmin + LOW_FRACTION * swing, vmin + HIGH_FRACTION * swing

    events = [(tc, d, "low") for tc, d in _crossings(t, v, low)]
    events += [(tc, d, "high") for tc, d in _crossings(t, v, high)]
    # In time order; on a tie, a rising edge meets low first and a falling edge meets high first.
    events.sort(key=lambda e: (e[0], 0 if (e[1] > 0) == (e[2] == "low") else 1))

    edges, rise_start, fall_start = [], None, None
    for tc, direction, level in events:
        if direction > 0:
            fall_start = None
            if level == "low":
                rise_start = tc
            elif rise_start is not None:
                edges.append({"type": "rise", "start": rise_start, "end": tc, "time": tc - rise_start})
                rise_start = None
        else:
            rise_start = None
            if level == "high":
                fall_start = tc
            elif fall_start is not None:
                edges.append({"type": "fall", "start": fall_start, "end": tc, "time": tc - fall_start})
                fall_start = None
    return edges, low, high


def report_edges(edges: list[dict], low: float, high: float, csv_path: Path) -> None:
    print(f"\n=== VOUT edges (10 % = {low:.4f} V, 90 % = {high:.4f} V) ===")
    print(f"{'#':>4}  {'type':<5} {'starts at (ns)':>15} {'time (ps)':>12}")
    for i, edge in enumerate(edges, 1):
        print(f"{i:>4}  {edge['type']:<5} {edge['start'] * 1e9:>15.4f} {edge['time'] * 1e12:>12.3f}")

    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["index", "type", "start_s", "end_s", "time_s"])
        for i, edge in enumerate(edges, 1):
            writer.writerow([i, edge["type"], f"{edge['start']:.6e}", f"{edge['end']:.6e}", f"{edge['time']:.6e}"])

    print()
    for kind in ("rise", "fall"):
        times = [e["time"] for e in edges if e["type"] == kind]
        if times:
            avg = sum(times) / len(times)
            print(f"Average {kind} time: {avg * 1e12:.3f} ps over {len(times)} edges "
                  f"(min {min(times) * 1e12:.3f} ps, max {max(times) * 1e12:.3f} ps)")
        else:
            print(f"Average {kind} time: no complete {kind} edges found")
    print(f"[edges] {csv_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = _parse_args()
    lib, cell = args.lib, args.tb_cell
    args.out_dir.mkdir(parents=True, exist_ok=True)
    client = VirtuosoClient.from_env()

    setup_maestro(client, args)

    session = client.maestro.open_gui_session(lib, cell)
    print(f"[session] {session} (GUI)")
    try:
        t0 = time.time()
        history, status = client.maestro.run_and_wait(session=session, timeout=args.timeout)
        history = history.strip('"')
        print(f"[sim] {history}: {status} ({time.time() - t0:.1f} s)")
        if not history or history == "nil":
            raise SystemExit("Maestro did not report a simulation history.")
        _report_point_status(client, lib, cell, history)

        psf_dir, history_dir = results_location(client, lib, cell, history)
        print("\n=== Simulation database ===")
        print(f"PSF results : {psf_dir}")
        print(f"History     : {history_dir}")

        waves = {}
        for name in SIGNALS:
            local = args.out_dir / f"{cell}_{history}_{name}.txt"
            client.maestro.export_waveform(session, f'v("/{name}")', str(local),
                                           analysis="tran", history=history,
                                           precision=12, width=22)
            waves[name] = read_ocnprint(local)
            print(f"[wave] {name}: {len(waves[name][0])} points -> {local}")
    finally:
        try:
            client.maestro.close_gui_session(session, save=False)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] close_gui_session failed: {exc}", file=sys.stderr)

    plot_waveforms(args.out_dir / f"{cell}_{history}_VIN_VOUT.png", waves,
                   f"{lib}/{cell}  {history}  transient")
    edges, low, high = measure_edges(*waves["VOUT"])
    report_edges(edges, low, high, args.out_dir / f"{cell}_{history}_VOUT_edges.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
