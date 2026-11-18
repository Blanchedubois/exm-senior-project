// Focused test on 10kHz and 50kHz - speeds that showed changing data
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

// Read at 10kHz - showed changing data at bytes 4-5
int32_t readADC_10kHz() {
  Wire.setClock(10000);
  delay(10);

  Wire.requestFrom(ADC_ADDR, (uint8_t)8);

  if (Wire.available() >= 8) {
    uint8_t data[8];
    for (int i = 0; i < 8; i++) {
      data[i] = Wire.read();
    }

    // Bytes 4-5 showed changing values at 10kHz
    // Extract as 16-bit value
    int32_t value = ((int32_t)data[4] << 8) | data[5];

    return value;
  }

  return -1;
}

// Read at 50kHz - showed changing data at bytes 0-1
int32_t readADC_50kHz() {
  Wire.setClock(50000);
  delay(10);

  Wire.requestFrom(ADC_ADDR, (uint8_t)8);

  if (Wire.available() >= 8) {
    uint8_t data[8];
    for (int i = 0; i < 8; i++) {
      data[i] = Wire.read();
    }

    // Bytes 0-1 showed changing values at 50kHz
    int32_t value = ((int32_t)data[0] << 8) | data[1];

    return value;
  }

  return -1;
}

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  Serial.println("\n9-Channel Reader - 10kHz/50kHz Method");
  Serial.println("======================================\n");

  Wire.begin();
  delay(100);

  Serial.println("Using 10kHz I2C speed for all readings\n");
}

void loop() {
  Serial.println("====================================");
  Serial.println("ADC Readings (10kHz method):");
  Serial.println("====================================");

  for (int i = 0; i < 9; i++) {
    tcaSelect(adcs[i].mux_addr, adcs[i].channel);
    delay(20);

    int32_t reading = readADC_10kHz();

    Serial.print(adcs[i].name);
    Serial.print(": ");
    Serial.print(reading);
    Serial.print(" (0x");
    Serial.print(reading, HEX);
    Serial.println(")");

    delay(10);
  }

  Serial.println();
  delay(1000);
}
