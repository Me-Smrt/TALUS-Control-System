Raspberry Pi 5 Mechanical Footprint - KiCad 10 native

Files:
  RPi5_Mechanical_KiCad10.pretty/Raspberry_Pi_5_Mechanical.kicad_mod

The footprint references:
  ${KIPRJMOD}/rpi-5b_with_graphics.step

Place your existing rpi-5b_with_graphics.step file in the KiCad project root.

Import:
  Preferences -> Manage Footprint Libraries
  Project Specific Libraries -> Add Existing Library
  Select the RPi5_Mechanical_KiCad10.pretty directory.

Then in PCB Editor:
  Place -> Add Footprint
  Search Raspberry_Pi_5_Mechanical

This file uses the KiCad 10 footprint file format (version 20260206).
Do not paste the .kicad_mod text into PCB Editor via the clipboard.
