// I2C Scanner at 10kHz to find NAU7802 address
#include <Wire.h>

#define MUX1_ADDR 0x71
#define MUX2_ADDR 0x73

void tcaSelect(uint8_t mux_addr, uint8_t channel) {
  if (channel > 7) return;
  Wire.beginTransmission(mux_addr);
  Wire.write(1 << channel);
  Wire.endTransmission();
}

void tcaDisable(uint8_t mux_addr) {
  Wire.beginTransmission(mux_addr);
  Wire.write(0);
  Wire.endTransmission();
}

void scanI2C(const char* label) {
  Serial.print(label);
  Serial.print(": ");

  int found = 0;
  for (byte addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    byte error = Wire.endTransmission();

    if (error == 0) {
      Serial.print("0x");
      if (addr < 16) Serial.print("0");
      Serial.print(addr, HEX);
      Serial.print(" ");
      found++;
    }
  }

  if (found == 0) {
    Serial.print("None");
  }
  Serial.println();
}

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  Serial.println("\n\nI2C Scanner @ 10kHz - Finding NAU7802");
  Serial.println("=====================================");
  Serial.println("Standard NAU7802 address: 0x2A");
  Serial.println("Previously detected: 0x36");
  Serial.println();

  Wire.begin();
  Wire.setClock(10000);  // 10kHz - ultra slow
  
  delay(100);

  // Disable both muxes first
  tcaDisable(MUX1_ADDR);
  tcaDisable(MUX2_ADDR);
  delay(50);

  // Scan main bus
  Serial.println("=== MAIN BUS (all MUX OFF) ===");
  scanI2C("Devices");
  Serial.println();

  // Scan MUX 0x71 channels
  Serial.println("=== MUX 0x71 CHANNELS ===");
  for (int ch = 0; ch < 5; ch++) {
    tcaSelect(MUX1_ADDR, ch);
    delay(20);
    char label[32];
    sprintf(label, "Ch%d", ch);
    scanI2C(label);
    tcaDisable(MUX1_ADDR);
    delay(10);
  }
  Serial.println();

  // Scan MUX 0x73 channels
  Serial.println("=== MUX 0x73 CHANNELS ===");
  for (int ch = 0; ch < 5; ch++) {
    tcaSelect(MUX2_ADDR, ch);
    delay(20);
    char label[32];
    sprintf(label, "Ch%d", ch);
    scanI2C(label);
    tcaDisable(MUX2_ADDR);
    delay(10);
  }
  Serial.println();

  Serial.println("=====================================");
  Serial.println("Scan complete!");
  Serial.println();
  Serial.println("Look for:");
  Serial.println("- 0x2A = Standard NAU7802 address");
  Serial.println("- 0x36 = Previously detected address");
  Serial.println("- Other addresses = Unknown devices");
}

void loop() {
  // Nothing
}
