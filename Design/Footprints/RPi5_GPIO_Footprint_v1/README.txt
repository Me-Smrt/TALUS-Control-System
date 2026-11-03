RPi5 GPIO custom footprint

Import RPi5_GPIO.pretty as a Project Specific Footprint Library with nickname RPi5_GPIO.
Assign footprint RPi5_GPIO:PinSocket_2x20_P2.54mm_Vertical_RPi5 to J_PI1 in the schematic so future Update PCB from Schematic / Update Footprints from Library keeps the corrected numbering orientation.

This footprint keeps the same 2x20 physical hole grid but reverses numbering along the long axis. Physical pins 1/2 are at the end opposite pins 39/40, matching the Raspberry Pi orientation used on the CCB.
