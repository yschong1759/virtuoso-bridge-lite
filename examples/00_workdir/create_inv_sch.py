#!/usr/bin/env python3
"""Create a CMOS inverter schematic via the Python schematic API.

Circuit::

            VDD
             |
         +--[P0]  (S=VDD, B=VDD)
    VIN -+   |---- VOUT
         +--[N0]  (S=VSS, B=VSS)
             |
            VSS

Pins: VIN (input), VOUT (output), VDD and VSS (inputOutput).

Usage::

    python create_inv_sch.py <LIB> <CELL>
    python create_inv_sch.py <LIB> <CELL> --mos-lib tsmcN28 --nmos nch_mac --pmos pch_mac

By default the transistors are analogLib nmos4/pmos4 (terminals D G S B).
Pass --mos-lib/--nmos/--pmos to use your PDK's 4-terminal devices instead.

Prerequisites:
  - virtuoso-bridge service running (virtuoso-bridge start)
  - the chosen MOS masters available in your Virtuoso install
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _target import parse_target
from virtuoso_bridge import VirtuosoClient
from virtuoso_bridge.virtuoso.schematic.ops import (
    schematic_create_inst_by_master_name as inst,
    schematic_create_pin,
    schematic_label_instance_term as label_term,
)


def _add_device_args(parser) -> None:
    parser.add_argument("--mos-lib", default="analogLib", help="library of the MOS masters")
    parser.add_argument("--nmos", default="nmos4", help="NMOS cell name")
    parser.add_argument("--pmos", default="pmos4", help="PMOS cell name")


# Terminal-to-net map for each transistor: (instance, terminal, net).
CONNECTIONS = (
    ("P0", "D", "VOUT"),
    ("P0", "G", "VIN"),
    ("P0", "S", "VDD"),
    ("P0", "B", "VDD"),
    ("N0", "D", "VOUT"),
    ("N0", "G", "VIN"),
    ("N0", "S", "VSS"),
    ("N0", "B", "VSS"),
)

# Pins: (name, x, y, orientation, direction). Each pin joins the net of the
# same name, which the terminal labels above create.
PINS = (
    ("VIN", -1.5, 0.0, "R0", "input"),
    ("VOUT", 1.5, 0.0, "R0", "output"),
    ("VDD", -1.5, 1.0, "R0", "inputOutput"),
    ("VSS", -1.5, -1.0, "R0", "inputOutput"),
)

# Accept common PDK terminal spellings as well as analogLib's D/G/S/B.
TERM_ALIASES = {
    "D": ("DRAIN",),
    "G": ("GATE",),
    "S": ("SOURCE",),
    "B": ("BULK", "SUB", "BODY"),
}


def _create(client: VirtuosoClient, lib: str, cell: str, args) -> None:
    with client.schematic.create(lib, cell) as sch:
        sch.add(inst(args.mos_lib, args.pmos, "symbol", "P0", 0.0, 0.75, "R0"))
        sch.add(inst(args.mos_lib, args.nmos, "symbol", "N0", 0.0, -0.75, "R0"))

        for instance, term, net in CONNECTIONS:
            sch.add(label_term(instance, term, net, aliases=TERM_ALIASES[term]))

        for name, x, y, orient, direction in PINS:
            sch.add(schematic_create_pin(name, x, y, orient, direction=direction))
        # schCheck + dbSave happen on context exit

    client.open_window(lib, cell, view="schematic")


def main() -> int:
    args = parse_target(
        "Create a CMOS inverter schematic (VIN, VOUT, VDD, VSS).",
        destructive=False,
        extra=_add_device_args,
    )
    client = VirtuosoClient.from_env()
    _create(client, args.lib, args.cell, args)
    print(f"Created {args.lib}/{args.cell}/schematic")
    print(f"Devices: P0={args.mos_lib}/{args.pmos}, N0={args.mos_lib}/{args.nmos}")
    print("Pins: VIN (input), VOUT (output), VDD/VSS (inputOutput)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
