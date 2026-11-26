#!/usr/bin/env python3
"""Create the tb_inv_sch testbench schematic around the inv_sch inverter.

Circuit::

    V0 (vdc 0.9 V):   PLUS=VDD  MINUS=gnd!
    V1 (vdc 0 V):     PLUS=VSS  MINUS=gnd!
    V2 (vpulse):      PLUS=VIN  MINUS=gnd!   0 V <-> 0.9 V, 10 ns period
    I0 (inv_sch):     VIN (wired to V2 PLUS), VOUT (labelled VOUT), VDD, VSS

Run create_inv_sch.py first so <LIB>/inv_sch/schematic exists. If inv_sch has
no symbol view yet, one is generated from its schematic.

Usage::

    python sim_inv_sch.py <LIB>
    python sim_inv_sch.py <LIB> --dut-cell inv_sch --tb-cell tb_inv_sch
    python sim_inv_sch.py <LIB> --overwrite    # replace an existing testbench

Prerequisites:
  - virtuoso-bridge service running (virtuoso-bridge start)
  - analogLib vdc and vpulse masters available in your Virtuoso install
"""

from __future__ import annotations

import argparse
import re

from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.schematic.ops import (
    schematic_create_inst_by_master_name as inst,
    schematic_create_wire_between_instance_terms as wire,
    schematic_label_instance_term as label_term,
)
from virtuoso_bridge.virtuoso.ops import escape_skill_string

GND = "gnd!"

# Source settings. tr + pw + tf = 10 ns gives a 50 % duty-cycle square wave.
VDD_VALUE = "900m"
VSS_VALUE = "0"
PULSE = dict(v1="0", v2="900m", per="10n", pw="4.99n", tr="5p", tf="5p", td="0")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the tb_inv_sch testbench schematic.")
    parser.add_argument("lib", help="library holding inv_sch; the testbench is created here too")
    parser.add_argument("--dut-cell", default="inv_sch", help="inverter cell to instantiate")
    parser.add_argument("--tb-cell", default="tb_inv_sch", help="testbench cell to create")
    parser.add_argument("--overwrite", action="store_true",
                        help="replace the testbench schematic if it already exists")
    return parser.parse_args()


def _exists(client: VirtuosoClient, lib: str, cell: str, view: str) -> bool:
    names = " ".join(f'"{escape_skill_string(n)}"' for n in (lib, cell, view))
    skill = f"ddGetObj({names}) != nil"
    return (client.execute_skill(skill).output or "").strip() == "t"


def _ensure_dut_symbol(client: VirtuosoClient, lib: str, cell: str) -> None:
    if not _exists(client, lib, cell, "schematic"):
        raise SystemExit(f"{lib}/{cell}/schematic does not exist; run create_inv_sch.py first.")
    if _exists(client, lib, cell, "symbol"):
        print(f"Using existing {lib}/{cell}/symbol")
        return
    result = client.symbol.generate_from_schematic(lib, cell, sort_pins="geometric")
    print(f"Generated {lib}/{cell}/symbol (pins: {', '.join(result.pin_order)})")


def _create_testbench(client: VirtuosoClient, lib: str, dut: str, tb: str) -> None:
    with client.schematic.create(lib, tb) as sch:
        sch.add(inst(lib, dut, "symbol", "I0", 1.5, 0.0, "R0"))
        sch.add(inst("analogLib", "vdc", "symbol", "V0", -3.0, 0.0, "R0"))
        sch.add(inst("analogLib", "vdc", "symbol", "V1", -1.5, 0.0, "R0"))
        sch.add(inst("analogLib", "vpulse", "symbol", "V2", 0.0, -1.5, "R0"))

        # Supplies: each source sits between its rail and global ground.
        sch.add(label_term("V0", "PLUS", "VDD"))
        sch.add(label_term("V0", "MINUS", GND))
        sch.add(label_term("V1", "PLUS", "VSS"))
        sch.add(label_term("V1", "MINUS", GND))
        sch.add(label_term("V2", "MINUS", GND))

        # Pulse source drives the inverter input. Both ends are labelled VIN,
        # so they share the net by name even if the routed wire is not drawn.
        sch.add(wire("V2", "PLUS", "I0", "VIN"))
        sch.add(label_term("V2", "PLUS", "VIN"))
        sch.add(label_term("I0", "VIN", "VIN"))

        # Inverter rails and output.
        sch.add(label_term("I0", "VDD", "VDD"))
        sch.add(label_term("I0", "VSS", "VSS"))
        sch.add(label_term("I0", "VOUT", "VOUT"))
        # schCheck + dbSave happen on context exit

    # Set the source values on the testbench cellview itself (not on whichever
    # window is current), save, and read every value back.
    for name, params in (("V0", {"vdc": VDD_VALUE}), ("V1", {"vdc": VSS_VALUE}), ("V2", PULSE)):
        _set_cdf_params(client, lib, tb, name, params)
    _verify_vin_net(client, lib, tb)
    client.open_window(lib, tb, view="schematic")


def _q(text: str) -> str:
    return f'"{escape_skill_string(text)}"'


def _set_cdf_params(client: VirtuosoClient, lib: str, cell: str, inst_name: str,
                    params: dict[str, str]) -> None:
    """Write CDF parameters of one instance in lib/cell/schematic, save, and verify them."""
    sets = " ".join(
        f"p = cdfFindParamByName(cdf {_q(k)}) "
        f"unless(p error(\"%s has no CDF parameter %s\" {_q(inst_name)} {_q(k)})) "
        f"p~>value = {_q(v)}"
        for k, v in params.items()
    )
    reads = " ".join(f"cdfFindParamByName(cdf {_q(k)})~>value" for k in params)
    skill = (
        "let((cv inst cdf p) "
        f"cv = dbOpenCellViewByType({_q(lib)} {_q(cell)} \"schematic\" nil \"a\") "
        f"unless(cv error(\"cannot open %s/%s/schematic for edit\" {_q(lib)} {_q(cell)})) "
        f"inst = dbFindAnyInstByName(cv {_q(inst_name)}) "
        f"unless(inst error(\"instance %s not found\" {_q(inst_name)})) "
        "cdf = cdfGetInstCDF(inst) "
        f"{sets} "
        "schCheck(cv) dbSave(cv) "
        f"list({reads}))"
    )
    result = client.execute_skill(skill)
    if result.errors:
        raise SystemExit(f"Setting {inst_name} parameters failed: {result.errors}")
    got = re.findall(r'"([^"]*)"', result.output or "")
    expected = list(params.values())
    if got != expected:
        raise SystemExit(
            f"{inst_name} parameters did not stick: wanted {dict(zip(params, expected))}, "
            f"read back {result.output}"
        )
    print(f"  {inst_name}: " + ", ".join(f"{k}={v}" for k, v in params.items()))


def _verify_vin_net(client: VirtuosoClient, lib: str, cell: str) -> None:
    """Fail unless V2 PLUS and I0 VIN are on the same net, named VIN."""
    skill = (
        "let((cv) "
        f"cv = dbOpenCellViewByType({_q(lib)} {_q(cell)} \"schematic\") "
        "mapcar(lambda((it) list(it~>inst~>name it~>name it~>net~>name)) "
        "setof(it cv~>instTerms "
        "(it~>inst~>name == \"V2\" && it~>name == \"PLUS\") || "
        "(it~>inst~>name == \"I0\" && it~>name == \"VIN\"))))"
    )
    output = client.execute_skill(skill).output or ""
    nets = dict(((a, b), n) for a, b, n in re.findall(r'\("([^"]+)" "([^"]+)" "([^"]+)"\)', output))
    v2, i0 = nets.get(("V2", "PLUS")), nets.get(("I0", "VIN"))
    if v2 != "VIN" or i0 != "VIN":
        raise SystemExit(f"VIN is not connected: V2 PLUS is on {v2!r}, I0 VIN is on {i0!r} ({output})")
    print("  VIN net: V2 PLUS and I0 VIN connected")


def main() -> int:
    args = _parse_args()
    client = VirtuosoClient.from_env()

    if _exists(client, args.lib, args.tb_cell, "schematic") and not args.overwrite:
        raise SystemExit(
            f"{args.lib}/{args.tb_cell}/schematic already exists; "
            "pass --overwrite to replace it."
        )

    _ensure_dut_symbol(client, args.lib, args.dut_cell)
    _create_testbench(client, args.lib, args.dut_cell, args.tb_cell)

    print(f"Created {args.lib}/{args.tb_cell}/schematic")
    print(f"  V0 vdc    VDD = {VDD_VALUE}")
    print(f"  V1 vdc    VSS = {VSS_VALUE}")
    print(f"  V2 vpulse VIN = {PULSE['v1']} <-> {PULSE['v2']}, period {PULSE['per']}")
    print(f"  I0 {args.dut_cell}: VIN <- V2, output labelled VOUT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
