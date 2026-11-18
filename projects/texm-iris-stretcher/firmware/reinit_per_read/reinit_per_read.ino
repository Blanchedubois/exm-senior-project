// Strategy: Re-initialize before EVERY read
// Theory: The NAU7802 at 0x36 needs fresh initialization each time
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

// Reinitialize the I2C bus completely
void resetI2C() {
  Wire.end();
  delay(10);
  Wire.begin();
  Wire.setClock(10000);  // 10kHz showed best results
  delay(10);
}

// Read with full reinitialization
int32_t readADC_withReinit() {
  // Reset I2C bus
  resetI2C();
  delay(20);

  // Simple read
  Wire.requestFrom(ADC_ADDR, (uint8_t)8);

  if (Wire.available() >= 8) {
    uint8_t data[8];
    for (int i = 0; i < 8; i++) {
      data[i] = Wire.read();
    }

    // Extract bytes 4-5 (showed changing data at 10kHz)
    int32_t value = ((int32_t)data[4] << 8) | data[5];

    return value;
  }

  return -1;
}

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  Serial.println("\n9-Channel Reader - Reinit Method");
  Serial.println("==================================\n");
  Serial.println("Reinitializing I2C before each read...\n");

  Wire.begin();
  Wire.setClock(10000);
  delay(100);
}

void loop() {
  Serial.println("====================================");
  Serial.println("ADC Readings:");
  Serial.println("====================================");

  for (int i = 0; i < 9; i++) {
    // Select MUX channel
    tcaSelect(adcs[i].mux_addr, adcs[i].channel);
    delay(50);

    // Read with reinitialization
    int32_t reading = readADC_withReinit();

    Serial.print(adcs[i].name);
    Serial.print(": ");
    Serial.print(reading);
    Serial.print(" (0x");
    Serial.print(reading, HEX);
    Serial.println(")");

    delay(50);
  }

  Serial.println();
  delay(2000);
}
