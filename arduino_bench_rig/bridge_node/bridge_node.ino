/*
  CANvisionNative bridge node.

  Speaks a minimal Lawicel/slcan protocol over USB serial, so python-can's
  built-in "slcan" interface (see backend/hardware/can_interface.py,
  interface="slcan") can talk to this board directly. No backend changes
  needed — this board just looks like any other slcan adapter.

  Wiring and library install steps: see ../README.md
*/

#include <mcp_can.h>
#include <SPI.h>

const int CAN_CS_PIN  = 10;
const int CAN_INT_PIN = 2;

MCP_CAN CAN(CAN_CS_PIN);

bool channelOpen = false;

void setup() {
  Serial.begin(115200);

  // If this never succeeds (board hangs here), the usual cause is the
  // MCP_8MHZ crystal assumption below being wrong for your specific
  // board — try MCP_16MHZ instead. See ../README.md troubleshooting.
  while (CAN.begin(MCP_ANY, CAN_500KBPS, MCP_8MHZ) != CAN_OK) {
    delay(200);
  }
  CAN.setMode(MCP_NORMAL);
  pinMode(CAN_INT_PIN, INPUT);
}

void loop() {
  handleIncomingSerialCommand();
  if (channelOpen) {
    forwardCanFrameToSerial();
  }
}

// ---- PC -> board: read one Lawicel command per line ----
void handleIncomingSerialCommand() {
  static char buf[32];
  static uint8_t idx = 0;

  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r' || c == '\n') {
      if (idx > 0) {
        buf[idx] = '\0';
        processCommand(buf);
        idx = 0;
      }
    } else if (idx < sizeof(buf) - 1) {
      buf[idx++] = c;
    }
  }
}

void processCommand(const char* cmd) {
  switch (cmd[0]) {
    case 'O':  // open channel
      channelOpen = true;
      Serial.print('\r');
      break;
    case 'C':  // close channel
      channelOpen = false;
      Serial.print('\r');
      break;
    case 'S':  // set bitrate request — this board is fixed at 500k
               // (set in CAN.begin() above), just acknowledge the command
      Serial.print('\r');
      break;
    case 'V':  // version query
      Serial.print("V1010\r");
      break;
    case 't':  // transmit standard frame: t + 3 hex ID + 1 hex len + hex data
      transmitFromCommand(cmd);
      Serial.print('z');
      Serial.print('\r');
      break;
    default:
      Serial.print('\r');
      break;
  }
}

void transmitFromCommand(const char* cmd) {
  if (strlen(cmd) < 5) return;

  char idHex[4] = { cmd[1], cmd[2], cmd[3], '\0' };
  unsigned long id = strtoul(idHex, NULL, 16);

  char lenHex[2] = { cmd[4], '\0' };
  uint8_t len = strtoul(lenHex, NULL, 16);
  if (len > 8) len = 8;

  byte data[8] = {0};
  for (uint8_t i = 0; i < len; i++) {
    char byteHex[3] = { cmd[5 + i * 2], cmd[6 + i * 2], '\0' };
    data[i] = (byte)strtoul(byteHex, NULL, 16);
  }

  CAN.sendMsgBuf(id, 0, len, data);  // 0 = standard (11-bit) frame
}

// ---- Bus -> PC: forward any received frame immediately ----
void forwardCanFrameToSerial() {
  if (digitalRead(CAN_INT_PIN)) return;  // nothing waiting

  long unsigned int rxId;
  unsigned char len = 0;
  unsigned char rxBuf[8];
  byte readStatus = CAN.readMsgBuf(&rxId, &len, rxBuf);
  if (readStatus != CAN_OK) return;  // the read itself failed; nothing valid to send
  if (len > 8) len = 8;  // a noisy/corrupted frame can report a bad length; never forward garbage

  char out[24];
  uint8_t pos = 0;
  out[pos++] = 't';
  snprintf(out + pos, 4, "%03lX", rxId & 0x7FF);
  pos += 3;
  out[pos++] = '0' + len;
  for (uint8_t i = 0; i < len; i++) {
    snprintf(out + pos, 3, "%02X", rxBuf[i]);
    pos += 2;
  }
  out[pos++] = '\r';
  out[pos] = '\0';

  // Belt-and-suspenders: whatever the cause of occasional bus noise, never
  // forward a line that isn't cleanly valid — a dropped frame is invisible,
  // a malformed one crashes the PC side's parser and kills the connection.
  for (uint8_t i = 1; i < pos - 1; i++) {
    if (!isxdigit((unsigned char)out[i])) return;
  }
  Serial.print(out);
}
