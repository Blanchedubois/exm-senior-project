// Advanced Debugging - Alternative approaches for NAU7802 at 0x36
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

  Serial.println("\n\nAdvanced NAU7802 Debugging");
  Serial.println("===========================\n");

  // Select first ADC
  tcaSelect(MUX1_ADDR, 0);
  delay(50);
}

void testClockSpeed(uint32_t speed) {
  Serial.print("\n--- Testing at ");
  Serial.print(speed);
  Serial.println(" Hz ---");

  Wire.begin();
  Wire.setClock(speed);
  delay(100);

  // Try simple read
  Wire.requestFrom(ADC_ADDR, (uint8_t)8);
  Serial.print("Got ");
  Serial.print(Wire.available());
  Serial.print(" bytes: ");

  for (int i = 0; i < 8 && Wire.available(); i++) {
    uint8_t b = Wire.read();
    Serial.print("0x");
    if (b < 16) Serial.print("0");
    Serial.print(b, HEX);
    Serial.print(" ");
  }
  Serial.println();
}

void testWriteThenRead() {
  Serial.println("\n--- Test: Write different values, then read ---");

  Wire.begin();
  Wire.setClock(100000);

  // Try writing different values to see if device responds
  uint8_t test_values[] = {0x00, 0x01, 0x06, 0x0E, 0x0F, 0x15, 0x80};

  for (int i = 0; i < 7; i++) {
    Wire.beginTransmission(ADC_ADDR);
    Wire.write(test_values[i]);
    byte err = Wire.endTransmission();

    Serial.print("Write 0x");
    if (test_values[i] < 16) Serial.print("0");
    Serial.print(test_values[i], HEX);
    Serial.print(" result: ");
    Serial.print(err);

    delay(10);

    // Read response
    Wire.requestFrom(ADC_ADDR, (uint8_t)4);
    Serial.print(" | Read: ");
    for (int j = 0; j < 4 && Wire.available(); j++) {
      uint8_t b = Wire.read();
      Serial.print("0x");
      if (b < 16) Serial.print("0");
      Serial.print(b, HEX);
      Serial.print(" ");
    }
    Serial.println();

    delay(50);
  }
}

void testSequentialSingleByteReads() {
  Serial.println("\n--- Test: Sequential single-byte reads ---");

  Wire.begin();
  Wire.setClock(100000);

  for (int i = 0; i < 10; i++) {
    Wire.requestFrom(ADC_ADDR, (uint8_t)1);

    if (Wire.available()) {
      uint8_t b = Wire.read();
      Serial.print("Read ");
      Serial.print(i);
      Serial.print(": 0x");
      if (b < 16) Serial.print("0");
      Serial.println(b, HEX);
    } else {
      Serial.print("Read ");
      Serial.print(i);
      Serial.println(": No data");
    }

    delay(20);
  }
}

void testWriteSequence() {
  Serial.println("\n--- Test: NAU7802 initialization sequence ---");

  Wire.begin();
  Wire.setClock(100000);

  // Try standard NAU7802 init sequence
  Serial.println("Attempting standard NAU7802 init...");

  // Reset
  Wire.beginTransmission(ADC_ADDR);
  Wire.write(0x00);  // PU_CTRL register
  Wire.write(0x06);  // RR + PUD
  byte err1 = Wire.endTransmission();
  Serial.print("Reset write: ");
  Serial.println(err1);
  delay(10);

  // Power up
  Wire.beginTransmission(ADC_ADDR);
  Wire.write(0x00);  // PU_CTRL register
  Wire.write(0x0E);  // PUD + PUA + CS
  byte err2 = Wire.endTransmission();
  Serial.print("Power up write: ");
  Serial.println(err2);
  delay(200);

  // Read status
  Wire.beginTransmission(ADC_ADDR);
  Wire.write(0x00);
  Wire.endTransmission(false);

  Wire.requestFrom(ADC_ADDR, (uint8_t)1);
  if (Wire.available()) {
    uint8_t status = Wire.read();
    Serial.print("Status after init: 0x");
    if (status < 16) Serial.print("0");
    Serial.println(status, HEX);
  }
}

void testContinuousReads() {
  Serial.println("\n--- Test: 20 continuous reads to find pattern ---");

  Wire.begin();
  Wire.setClock(100000);

  for (int i = 0; i < 20; i++) {
    Wire.requestFrom(ADC_ADDR, (uint8_t)6);

    Serial.print(i);
    Serial.print(": ");

    for (int j = 0; j < 6 && Wire.available(); j++) {
      uint8_t b = Wire.read();
      Serial.print("0x");
      if (b < 16) Serial.print("0");
      Serial.print(b, HEX);
      Serial.print(" ");
    }
    Serial.println();

    delay(100);
  }
}

void testDifferentAddresses() {
  Serial.println("\n--- Test: Try reading from nearby addresses ---");

  Wire.begin();
  Wire.setClock(100000);

  uint8_t addresses[] = {0x35, 0x36, 0x37, 0x2A, 0x2B};

  for (int i = 0; i < 5; i++) {
    Serial.print("Address 0x");
    if (addresses[i] < 16) Serial.print("0");
    Serial.print(addresses[i], HEX);
    Serial.print(": ");

    Wire.requestFrom(addresses[i], (uint8_t)6);

    if (Wire.available() > 0) {
      for (int j = 0; j < 6 && Wire.available(); j++) {
        uint8_t b = Wire.read();
        Serial.print("0x");
        if (b < 16) Serial.print("0");
        Serial.print(b, HEX);
        Serial.print(" ");
      }
      Serial.println(" [RESPONDS]");
    } else {
      Serial.println("[NO RESPONSE]");
    }

    delay(50);
  }
}

void loop() {
  Serial.println("\n\n========================================");
  Serial.println("Starting test sequence...");
  Serial.println("========================================");

  // Test 1: Different I2C speeds
  testClockSpeed(10000);    // 10 kHz
  testClockSpeed(50000);    // 50 kHz
  testClockSpeed(100000);   // 100 kHz
  testClockSpeed(400000);   // 400 kHz
  testClockSpeed(1000);     // 1 kHz (very slow)

  delay(500);

  // Test 2: Write then read
  testWriteThenRead();

  delay(500);

  // Test 3: Sequential single reads
  testSequentialSingleByteReads();

  delay(500);

  // Test 4: Init sequence
  testWriteSequence();

  delay(500);

  // Test 5: Continuous reads
  testContinuousReads();

  delay(500);

  // Test 6: Different addresses
  testDifferentAddresses();

  Serial.println("\n\n========================================");
  Serial.println("All tests complete. Waiting 10 seconds...");
  Serial.println("========================================");

  delay(10000);
}
