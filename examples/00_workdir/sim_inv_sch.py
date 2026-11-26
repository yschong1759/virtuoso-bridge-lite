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

from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.schematic.ops import (
    schematic_create_inst_by_master_name as inst,
    schematic_create_wire_between_instance_terms as wire,
    schematic_label_instance_term as label_term,
)
from virtuoso_bridge.virtuoso.schematic.params import set_instance_params
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

        # Pulse source drives the inverter input with a real wire, labelled VIN.
        sch.add(wire("V2", "PLUS", "I0", "VIN"))
        sch.add(label_term("I0", "VIN", "VIN"))

        # Inverter rails and output.
        sch.add(label_term("I0", "VDD", "VDD"))
        sch.add(label_term("I0", "VSS", "VSS"))
        sch.add(label_term("I0", "VOUT", "VOUT"))
        # schCheck + dbSave happen on context exit

    # set_instance_params acts on the current schematic window, so open the
    # testbench first.
    client.open_window(lib, tb, view="schematic")
    set_instance_params(client, "V0", vdc=VDD_VALUE, param_filters=None)
    set_instance_params(client, "V1", vdc=VSS_VALUE, param_filters=None)
    set_instance_params(client, "V2", param_filters=None, **PULSE)


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
