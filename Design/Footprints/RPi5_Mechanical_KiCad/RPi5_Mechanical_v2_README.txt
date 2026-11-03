RPi5 Mechanical KiCad Footprint v2
==================================

Files:
  RPi5_Mechanical_v2.pretty/Raspberry_Pi_5_Mechanical.kicad_mod
  rpi-5b_with_graphics.step   (place this user-provided STEP in the KiCad project root)

The footprint origin is Raspberry Pi GPIO physical pin 1. It also contains a
mechanical 2x20 pin-center reference grid on User.1 so the CCB socket can be
visually aligned after choosing which side of the CCB the Pi/socket are mounted on.

The attached model reference is:
  ${KIPRJMOD}/rpi-5b_with_graphics.step

Model transform used:
  offset X = -8.37 mm
  offset Y = -51.23 mm
  offset Z = 0 mm
  rotation = 0,0,0
  scale    = 1,1,1

The XY transform is based on the official Pi 5 85 x 56 mm board geometry and the
standard HAT/GPIO location: physical pin 1 is 8.37 mm from the short board edge
and 4.77 mm from the adjacent long edge. KiCad handles STEP's Y-up coordinate
system when rendering the model.

IMPORTANT VALIDATION:
After placing the footprint, open KiCad 3D Viewer and verify that:
  * all four Pi mounting holes coincide with the footprint holes,
  * the STEP GPIO header coincides with the User.1 pin-center grid,
  * USB/Ethernet are on the expected outward-facing board edge.
Then align J_PI1 to the GPIO reference grid, checking physical pin 1 and pin 2.
Do not assume the generic socket footprint has the same local rotation before it
is flipped to the bottom side; use the pin-center grid / 3D model as the authority.

If your STEP revision uses a different internal origin, adjust only the 3D model
offset in Footprint Properties; do not move the mechanical footprint geometry.
