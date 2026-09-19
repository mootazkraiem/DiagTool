"""
Quick smoke test for the Arduino bench rig — bypasses the FastAPI backend
entirely so we can check the raw hardware path first: simulator node ->
physical CAN bus -> bridge node -> slcan -> this script.

Usage:
    python test_bus.py COM5
(replace COM5 with your bridge node's actual COM port)

Expected output once running: frames with ID 0x316 (speed) about every
20ms, ID 0x3F9 (SOC) about every 200ms, and one frame with ID 0x666
(the on-purpose anomaly frame) about every 20 seconds.
"""
import sys
import can

if len(sys.argv) != 2:
    print("Usage: python test_bus.py <COM_PORT>")
    print("Example: python test_bus.py COM5")
    sys.exit(1)

port = sys.argv[1]
print(f"Connecting to bridge node on {port} at 500000 bps...")

bus = can.interface.Bus(interface="slcan", channel=port, bitrate=500000)
print("Connected. Listening for CAN frames (press Ctrl+C to stop)...\n")

try:
    for msg in bus:
        print(f"ID=0x{msg.arbitration_id:03X}  data={msg.data.hex()}")
except KeyboardInterrupt:
    print("\nStopped.")
finally:
    bus.shutdown()
