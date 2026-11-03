# TALUS hardware — licensing and credits

The original **Central Control Module (CCB)** and **Remote Control Module (RCB)** KiCad hardware design contributions in this directory are offered under the **CERN Open Hardware Licence Version 2 — Weakly Reciprocal (CERN-OHL-W-2.0)**.

**License:** See [`LICENSE`](LICENSE) (official license text; copy unchanged from [CERN/Open Hardware Repository](https://ohwr.org/licences/)).

**Copyright:** © 2026 Tyler Krumm, to the extent of original copyrightable material I own.

**Source location:** `https://github.com/Me-Smrt/TALUS-Control-System`

## Scope

Covered original contributions include the author-created schematics, circuit organization, PCB layout, and related project-level design files in:

- `Central Control Module/`
- `Remote Control Module/`

This statement does **not** transfer or relicense third-party material found in those project files, including vendor symbols, imported footprints, external reference layouts, third-party graphics or model data. All material in `Footprints/` and any third-party content copied into project-local `.pretty` libraries or `.kicad_sym` files retains its respective source rights and notices. Only independently authored portions are offered under my license.

KiCad project and library metadata (`.kicad_pro`, `fp-lib-table`, etc.) is included to assist reproduction, but not every individual metadata element necessarily qualifies for copyright protection.

## Rebuilding the hardware

The source-only GitHub repository tracks editable KiCad schematic, PCB and library source, not downloaded vendor STEP geometry, Gerbers, manufacturing ZIPs or other generated outputs. External footprint and 3D-model dependencies should be obtained from their original sources, with any manufacturer-specific library notices kept intact. See [the Design README](README.md) and the relevant component documentation for prerequisites. A missing 3D STEP model may affect visualization but should not be mistaken for an electrical design error.

The designs are shared as **engineering research and development**. They are not certified for manufacturing safety or physical actuator operation merely because source files are public.

## License notice for derivative designs

When redistributing covered modified design files, follow the CERN-OHL-W-2.0 terms for notices, modification records and complete source. This document is an explanation and does not replace the official license.
