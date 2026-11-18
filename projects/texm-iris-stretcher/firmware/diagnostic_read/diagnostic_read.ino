// Diagnostic read to understand NAU7802 at 0x36
#include <Wire.h>

#define MUX1_ADDR 0x71
#define ADC_ADDR 0x36

void tcaSelect(uint8_t mux_addr, uint8_t channel) {
  Wire.beginTransmission(mux_addr);
  Wire.write(1 << channel);
  Wire.endTransmission();
}

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  Serial.println("\n\nDiagnostic Read Test");
  Serial.println("====================");

  Wire.begin();
  Wire.setClock(100000);  // 100kHz
  delay(100);

  // Select first ADC
  tcaSelect(MUX1_ADDR, 0);
  delay(10);
}

void loop() {
  Serial.println("\n--- Test 0: Pure read without register address ---");
  Wire.requestFrom(ADC_ADDR, (uint8_t)12);
  if (Wire.available() >= 12) {
    Serial.print("Got 12 bytes: ");
    for (int i = 0; i < 12; i++) {
      uint8_t b = Wire.read();
      Serial.print("0x");
      if (b < 16) Serial.print("0");
      Serial.print(b, HEX);
      Serial.print(" ");
    }
    Serial.println();
  } else {
    Serial.print("Only got ");
    Serial.print(Wire.available());
    Serial.println(" bytes");
  }

  delay(100);

  Serial.println("\n--- Test 1: Direct 8-byte read ---");
  Wire.requestFrom(ADC_ADDR, (uint8_t)8);
  if (Wire.available() >= 8) {
    Serial.print("Got 8 bytes: ");
    for (int i = 0; i < 8; i++) {
      uint8_t b = Wire.read();
      Serial.print("0x");
      if (b < 16) Serial.print("0");
      Serial.print(b, HEX);
      Serial.print(" ");
    }
    Serial.println();
  } else {
    Serial.println("Failed to read 8 bytes");
  }

  delay(100);

  Serial.println("\n--- Test 2: Read register 0x00 (PU_CTRL) ---");
  Wire.beginTransmission(ADC_ADDR);
  Wire.write(0x00);
  byte error = Wire.endTransmission(false);
  Serial.print("Write result: ");
  Serial.println(error);

  Wire.requestFrom(ADC_ADDR, (uint8_t)1);
  if (Wire.available()) {
    uint8_t val = Wire.read();
    Serial.print("PU_CTRL = 0x");
    if (val < 16) Serial.print("0");
    Serial.println(val, HEX);
  } else {
    Serial.println("No data available");
  }

  delay(100);

  Serial.println("\n--- Test 3: Read registers 0x12-0x14 (ADC output) ---");
  for (int reg = 0x12; reg <= 0x14; reg++) {
    Wire.beginTransmission(ADC_ADDR);
    Wire.write(reg);
    Wire.endTransmission(false);

    Wire.requestFrom(ADC_ADDR, (uint8_t)1);
    if (Wire.available()) {
      uint8_t val = Wire.read();
      Serial.print("Reg 0x");
      if (reg < 16) Serial.print("0");
      Serial.print(reg, HEX);
      Serial.print(" = 0x");
      if (val < 16) Serial.print("0");
      Serial.println(val, HEX);
    }
  }

  delay(100);

  Serial.println("\n--- Test 4: Read 3 ADC bytes starting at 0x12 ---");
  Wire.beginTransmission(ADC_ADDR);
  Wire.write(0x12);  // Start at ADC output register
  byte err = Wire.endTransmission(false);
  Serial.print("Write 0x12, result: ");
  Serial.println(err);

  Wire.requestFrom(ADC_ADDR, (uint8_t)3);
  if (Wire.available() >= 3) {
    uint8_t b2 = Wire.read();
    uint8_t b1 = Wire.read();
    uint8_t b0 = Wire.read();

    int32_t value = ((int32_t)b2 << 16) | ((int32_t)b1 << 8) | b0;
    if (value & 0x800000) value |= 0xFF000000;

    Serial.print("ADC bytes: 0x");
    if (b2 < 16) Serial.print("0");
    Serial.print(b2, HEX);
    Serial.print(" 0x");
    if (b1 < 16) Serial.print("0");
    Serial.print(b1, HEX);
    Serial.print(" 0x");
    if (b0 < 16) Serial.print("0");
    Serial.print(b0, HEX);
    Serial.print(" = ");
    Serial.println(value);
  } else {
    Serial.println("Failed to read 3 bytes");
  }

  delay(100);

  Serial.println("\n--- Test 5: Read 24 bytes from 0x00 (with repeated START) ---");
  Wire.beginTransmission(ADC_ADDR);
  Wire.write(0x00);
  Wire.endTransmission(false);

  Wire.requestFrom(ADC_ADDR, (uint8_t)24);
  Serial.print("Got ");
  Serial.print(Wire.available());
  Serial.println(" bytes:");

  int count = 0;
  while (Wire.available() && count < 24) {
    if (count % 8 == 0) {
      Serial.print("\n0x");
      if (count < 16) Serial.print("0");
      Serial.print(count, HEX);
      Serial.print(": ");
    }
    uint8_t b = Wire.read();
    Serial.print("0x");
    if (b < 16) Serial.print("0");
    Serial.print(b, HEX);
    Serial.print(" ");
    count++;
  }
  Serial.println();

  delay(100);

  Serial.println("\n--- Test 6: Read 24 bytes from 0x00 (with STOP) ---");
  Wire.beginTransmission(ADC_ADDR);
  Wire.write(0x00);
  Wire.endTransmission(true);  // Send STOP

  delay(1);  // Small delay between transactions

  Wire.requestFrom(ADC_ADDR, (uint8_t)24);
  Serial.print("Got ");
  Serial.print(Wire.available());
  Serial.println(" bytes:");

  count = 0;
  while (Wire.available() && count < 24) {
    if (count % 8 == 0) {
      Serial.print("\n0x");
      if (count < 16) Serial.print("0");
      Serial.print(count, HEX);
      Serial.print(": ");
    }
    uint8_t b = Wire.read();
    Serial.print("0x");
    if (b < 16) Serial.print("0");
    Serial.print(b, HEX);
    Serial.print(" ");
    count++;
  }
  Serial.println();

  delay(2000);
}
