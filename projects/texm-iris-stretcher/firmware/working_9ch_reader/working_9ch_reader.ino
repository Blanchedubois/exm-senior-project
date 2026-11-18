// 9-Channel NAU7802 Reader - Accounting for byte duplication at 0x36
#include <Wire.h>

#define MUX1_ADDR 0x71
#define MUX2_ADDR 0x73
#define ADC_ADDR 0x36

struct ADC_Channel {
  uint8_t mux_addr;
  uint8_t channel;
  const char* name;
};

ADC_Channel adcs[] = {
  {MUX1_ADDR, 0, "ADC1"},
  {MUX1_ADDR, 1, "ADC2"},
  {MUX1_ADDR, 2, "ADC3"},
  {MUX1_ADDR, 3, "ADC4"},
  {MUX2_ADDR, 0, "ADC5"},
  {MUX2_ADDR, 1, "ADC6"},
  {MUX2_ADDR, 2, "ADC7"},
  {MUX2_ADDR, 3, "ADC8"},
  {MUX2_ADDR, 4, "ADC9"}
};

void tcaSelect(uint8_t mux_addr, uint8_t channel) {
  Wire.beginTransmission(mux_addr);
  Wire.write(1 << channel);
  Wire.endTransmission();
}

// Read ADC value - accounting for byte duplication
int32_t readADC() {
  // Read 12 bytes (6 unique values due to duplication)
  // Based on diagnostic data: bytes 4-5 and 8-9 contain changing values
  Wire.requestFrom(ADC_ADDR, (uint8_t)12);

  if (Wire.available() >= 12) {
    uint8_t data[12];
    for (int i = 0; i < 12; i++) {
      data[i] = Wire.read();
    }

    // Extract unique bytes from positions that showed changing data
    // Bytes at 4, 8 were changing in diagnostic tests
    int32_t value = 0;
    value = ((int32_t)data[4] << 16) | ((int32_t)data[8] << 8) | 0x00;

    // Convert to signed 24-bit
    if (value & 0x800000) {
      value |= 0xFF000000;
    }

    return value;
  }

  return 0;
}

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  Serial.println("\n\n9-Channel ADC Reader - Working Version");
  Serial.println("========================================");

  Wire.begin();
  Wire.setClock(100000);  // 100kHz
  delay(100);

  Serial.println("Ready!\n");
}

void loop() {
  Serial.println("====================================");
  Serial.println("ADC Readings:");
  Serial.println("====================================");

  for (int i = 0; i < 9; i++) {
    tcaSelect(adcs[i].mux_addr, adcs[i].channel);
    delay(10);

    int32_t reading = readADC();
    float voltage = (reading / 8388608.0) * 1.5;  // Assuming 3.0V reference, gain of 128

    Serial.print(adcs[i].name);
    Serial.print(": ");
    Serial.print(reading);
    Serial.print(" | ");
    Serial.print(voltage, 6);
    Serial.println(" V");
  }

  Serial.println();
  delay(500);
}
