# Arduino bench rig — CAN hardware bring-up

This folder replaces a real vehicle for the M2 hardware milestone. Two Arduino Unos, two MCP2515 CAN modules, wired to each other, standing in for a car's electrical CAN bus.

- **bridge_node** — plugs into your PC over USB. Speaks the `slcan` protocol your backend already supports (`backend/hardware/can_interface.py`, `interface="slcan"`). This is the node your Python backend connects to.
- **simulator_node** — the "fake car." Sends a few realistic-looking CAN frames onto the bus on a loop, plus one clearly anomalous frame every 20 seconds so you have something live to point at during a demo.

## Wiring (identical for both boards)

Both boards use the exact same wiring between the Arduino Uno and its MCP2515 module.

| MCP2515 module pin | Arduino Uno pin |
|---|---|
| VCC | 5V |
| GND | GND |
| CS | Digital pin 10 |
| SO (sometimes labeled MISO) | Digital pin 12 |
| SI (sometimes labeled MOSI) | Digital pin 11 |
| SCK | Digital pin 13 |
| INT | Digital pin 2 |

Do this wiring twice — once per Arduino + MCP2515 pair.

## The bus link — connecting the two boards to each other

This is the part that's actually "the CAN bus." On each MCP2515 module, find the **CAN-H** and **CAN-L** pins (sometimes on a small screw terminal, sometimes on a DB9 connector, sometimes as extra header pins — check your specific board).

Connect:
- Module A's **CAN-H** → Module B's **CAN-H**
- Module A's **CAN-L** → Module B's **CAN-L**

That's it — just those two wires, directly between the two modules. Nothing connects to the Arduino pins for this part.

**Termination:** check if your MCP2515 boards have a built-in 120Ω termination jumper (often a small jumper cap or solder pad labeled "120R"). If both boards have one, enable both and skip the loose resistor. If only one does, put your loose 120Ω resistor across CAN-H/CAN-L on the other board. If neither has one, put a 120Ω resistor across CAN-H/CAN-L on each end.

## Software setup, step by step

1. Install the **Arduino IDE** (free) if you don't have it already.
2. Plug in one Arduino. If Windows doesn't recognize it as a COM port, install the CH340 driver first: https://www.wch-ic.com/downloads/CH341SER_ZIP.html — this is expected for a clone board, not a sign anything is broken.
3. In the Arduino IDE: **Sketch → Include Library → Manage Libraries**, search for `mcp_can` (by Cory J. Fowler), and install it. Both sketches in this folder need this library.
4. Open `bridge_node/bridge_node.ino`, select the correct board and COM port, and upload it to the Arduino that's plugged into your PC.
5. Open `simulator_node/simulator_node.ino`, upload it to the second Arduino. This one can stay plugged into your PC too, or run off any USB power source (phone charger, power bank) once it's flashed — it doesn't need to talk to your PC at all, it just needs power.
6. In your Python backend, connect using `interface="slcan"` and the COM port the bridge Arduino shows up as — exactly the same call your code already makes for any other hardware adapter.

## If nothing shows up / no CAN traffic

The single most common cause is one line in both `.ino` files: `CAN.begin(MCP_ANY, CAN_500KBPS, MCP_8MHZ)`. That last part, `MCP_8MHZ`, has to match the crystal actually soldered onto your specific MCP2515 board — most cheap boards use 8MHz, but some use 16MHz. If you wire everything correctly and still see nothing, change `MCP_8MHZ` to `MCP_16MHZ` in both files, re-upload, and try again.
