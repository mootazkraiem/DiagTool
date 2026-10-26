/*
  CANvisionNative simulator node — "the fake car."

  Transmits a small set of realistic-looking CAN frames onto the physical
  bus on a loop, standing in for a real vehicle's ECUs, so the bridge node
  (and the Python backend behind it) has real electrical CAN traffic to
  capture. Also sends one clearly anomalous frame every 20 seconds, so
  there is something live to point at during a demo.

  This board does not need to be plugged into your PC once flashed — any
  USB power source works, since it only transmits, it never talks serial.

  Wiring and library install steps: see ../README.md
*/

#include <mcp_can.h>
#include <SPI.h>

const int CAN_CS_PIN = 10;
MCP_CAN CAN(CAN_CS_PIN);

unsigned long lastSpeed = 0;
unsigned long lastBattery = 0;
unsigned long lastAnomaly = 0;
bool firstAnomalySent = false;

void setup() {
  // TEMPORARY DIAGNOSTIC — remove Serial lines once frames are flowing.
  Serial.begin(9600);
  Serial.println("Booting simulator node...");

  // Same crystal-frequency note as bridge_node.ino — if this never
  // succeeds, try MCP_16MHZ instead of MCP_8MHZ.
  uint8_t tries = 0;
  while (CAN.begin(MCP_ANY, CAN_500KBPS, MCP_8MHZ) != CAN_OK) {
    tries++;
    Serial.print("CAN.begin() failed, retry #");
    Serial.println(tries);
    delay(200);
  }
  CAN.setMode(MCP_NORMAL);
  Serial.println("CAN.begin() succeeded. Starting to transmit.");
}

unsigned long lastHeartbeat = 0;
unsigned int sendOkCount = 0;
unsigned int sendFailCount = 0;

void loop() {
  unsigned long now = millis();

  // TEMPORARY DIAGNOSTIC — reports every second whether sendMsgBuf() is
  // actually succeeding. CAN_OK means the frame was sent AND acknowledged
  // by another node on the bus (the bridge). Repeated failures here usually
  // mean the bridge isn't acknowledging — check its wiring/power, not this board's.
  if (now - lastHeartbeat >= 1000) {
    lastHeartbeat = now;
    Serial.print("Heartbeat: ok=");
    Serial.print(sendOkCount);
    Serial.print(" fail=");
    Serial.println(sendFailCount);
  }

  // Vehicle speed, every ~20ms — a fast, regular signal like a real ECU.
  if (now - lastSpeed >= 20) {
    lastSpeed = now;
    byte speedKph = 60;  // constant cruising speed, for a stable demo
    byte data[8] = { speedKph, 0, 0, 0, 0, 0, 0, 0 };
    byte result = CAN.sendMsgBuf(0x316, 0, 8, data);
    if (result == CAN_OK) sendOkCount++; else sendFailCount++;
  }

  // Battery state of charge, every ~200ms — slower, BMS-style signal.
  if (now - lastBattery >= 200) {
    lastBattery = now;
    byte soc = 78;  // 78%
    byte data[8] = { soc, 0, 0, 0, 0, 0, 0, 0 };
    CAN.sendMsgBuf(0x3F9, 0, 8, data);
  }

  // Every 20 seconds, one frame on an ID that's never used above.
  // A clean, repeatable way to trigger the unknown-identifier check live,
  // in front of a jury.
  //
  // Connect with the "Arduino bench rig" vehicle profile: its DBC
  // (assets/dbc_files/bench-rig.dbc) defines 0x316 and 0x3F9 only, so the
  // backend flags 0x666 on its very first frame. There is no learning
  // window in live capture; the first frame still waits 35s after power-on
  // only so the first half minute of a demo shows clean decoded traffic.
  if (!firstAnomalySent) {
    if (now >= 35000) {
      firstAnomalySent = true;
      lastAnomaly = now;
      byte data[8] = { 0xDE, 0xAD, 0xBE, 0xEF, 0, 0, 0, 0 };
      CAN.sendMsgBuf(0x666, 0, 8, data);
    }
  } else if (now - lastAnomaly >= 20000) {
    lastAnomaly = now;
    byte data[8] = { 0xDE, 0xAD, 0xBE, 0xEF, 0, 0, 0, 0 };
    CAN.sendMsgBuf(0x666, 0, 8, data);
  }
}
