"""Physical Raspberry Pi 5 GPIO map from the uploaded CCB KiCad PCB.

BCM numbering is used here. Physical header pin numbers are included in comments.
"""

SPI_MOSI = 10  # physical 19
SPI_MISO = 9   # physical 21
SPI_SCK = 11   # physical 23

CAN_CS = (8, 7, 4, 17, 27, 22, 23, 24)       # physical 24,26,7,11,13,15,16,18
CAN_INT = (25, 5, 6, 12, 13, 19, 16, 26)      # physical 22,29,31,32,33,35,36,37

SUP_UART_TX = 14   # physical 8, Pi -> supervisor
SUP_UART_RX = 15   # physical 10, supervisor -> Pi
SUP_HEARTBEAT = 18 # physical 12, Pi -> supervisor
PWR_FAULT_N = 20   # physical 38, CCB -> Pi

MCP25625_OSC_HZ = 20_000_000
