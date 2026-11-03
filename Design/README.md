# TALUS — KiCad Hardware Designs

This directory contains the editable hardware source for the **Central Control Module (CCB)** and **Remote Control Module (RCB)** used in TALUS's distributed robot-control architecture. The designs are research and development work; publishing the source does not establish that the boards or their actuator safety systems have been validated on physical hardware.

## Projects

| Project | Open in KiCad | Purpose |
| --- | --- | --- |
| **Central Control Module (CCB)** | [`Central Control Module.kicad_pro`](Central%20Control%20Module/Central%20Control%20Module.kicad_pro) | Raspberry Pi interface, supervisor, distributed CAN channels, remote power, and safety control. |
| **Remote Control Module (RCB)** | [`Remote Control Module.kicad_pro`](Remote%20Control%20Module/Remote%20Control%20Module.kicad_pro) | Remote CAN communications, local servo/PWM control, power management, and hardware safety interfaces. |

Each project directory includes the main schematic, hierarchical schematic sheets, PCB layout, KiCad project configuration, and project-local library content where applicable. `Footprints/` contains supplementary imported component symbols and footprints, including material supplied by third parties.

## Opening and inspecting the designs

1. Install a compatible version of **KiCad** (the projects have been developed with KiCad 10).
2. Open the relevant `.kicad_pro` file through KiCad's Project Manager.
3. Inspect the schematic and PCB layout in their respective editors. Recheck electrical and design rules in your own environment before using the files for fabrication.
4. If a custom footprint or symbol is unresolved, check the project's local `.pretty` library, `fp-lib-table`, and library paths. Libraries imported from `Footprints/` may need to be registered or their paths adjusted for your computer.

Some library and 3D-model references may reflect the author's local development paths. Prefer project-relative paths (such as `${KIPRJMOD}`) where practical, and do not assume an externally downloaded file will be present after cloning.

## Footprints and 3D models

The repository intentionally includes the **editable KiCad symbols and footprints**, but excludes externally sourced `.step` / `.stp` component models and manufacturing exports. You can edit the electrical design and generate fabrication files without the vendor STEP geometry. The 3D Viewer may display missing models until you obtain those assets separately and update their paths.

When retrieving external symbols, footprints, or 3D files, use the original vendor or library provider and respect their license and attribution requirements. The existence of a file in `Footprints/` does not mean it was created or relicensed by the TALUS author.

## Safety and licensing

The CCB and RCB include circuitry intended to manage actuator power, communication timeouts, and servo authorization. These features require hardware bring-up and verification; they should **not** be treated as a guarantee of physical safety based on the published design files alone.

Original hardware design contributions are distributed under **CERN-OHL-W-2.0**. Third-party content retains its own terms. See [hardware licensing and scope](LICENSING.md), the [license text](LICENSE), [repository-wide licensing](../LICENSE_SCOPE.md), and [third-party acknowledgments](../THIRD_PARTY_NOTICES.md).

For the broader development and verification boundaries, see [Project Status](../PROJECT_STATUS.md).
