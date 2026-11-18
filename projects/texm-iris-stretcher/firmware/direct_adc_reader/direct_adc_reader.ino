// Direct ADC Reader for NAU7802 at standard address 0x2A
// ESP32-S3 Feather with 2x TCA9548A multiplexers
// MUX 0x71: 4 ADCs on channels 0-3
// MUX 0x73: 5 ADCs on channels 0-4

#include <Wire.h>

#define MUX1_ADDR 0x71
#define MUX2_ADDR 0x73
#define ADC_ADDR 0x36  // NAU7802 responds at 0x36 on this hardware

// NAU7802 Register addresses
#define NAU7802_PU_CTRL  0x00
#define NAU7802_CTRL1    0x01
#define NAU7802_CTRL2    0x02
#define NAU7802_ADCO_B2  0x12  // ADC output byte 2 (MSB)
#define NAU7802_ADCO_B1  0x13  // ADC output byte 1
#define NAU7802_ADCO_B0  0x14  // ADC output byte 0 (LSB)

struct ADC_Channel {
  uint8_t mux_addr;
  uint8_t channel;
  const char* name;
};

// Define all 9 ADC channels
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

// Write to NAU7802 register
bool writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(ADC_ADDR);
  Wire.write(reg);
  Wire.write(value);
  return (Wire.endTransmission() == 0);
}

// Read from NAU7802 register
uint8_t readRegister(uint8_t reg) {
  Wire.beginTransmission(ADC_ADDR);
  Wire.write(reg);
  Wire.endTransmission(false);
  
  Wire.requestFrom(ADC_ADDR, (uint8_t)1);
  if (Wire.available()) {
    return Wire.read();
  }
  return 0;
}

// Read 24-bit ADC value (simplified - direct read)
int32_t readADC() {
  // Direct read - request 8 bytes and extract ADC value
  Wire.requestFrom(ADC_ADDR, (uint8_t)8);

  if (Wire.available() >= 8) {
    // Read all 8 bytes
    uint8_t data[8];
    for (int i = 0; i < 8; i++) {
      data[i] = Wire.read();
    }

    // The pattern we saw: 0x5C 0xEA 0x5C 0xEA...
    // Try interpreting first 3 bytes as 24-bit value
    int32_t value = 0;
    value = (int32_t)data[0] << 16;
    value |= (int32_t)data[1] << 8;
    value |= data[2];

    // Convert to signed 24-bit
    if (value & 0x800000) {
      value |= 0xFF000000;
    }

    return value;
  }

  return 0;
}

// Initialize NAU7802
bool initADC(uint8_t mux_addr, uint8_t channel, const char* name) {
  tcaSelect(mux_addr, channel);
  delay(10);
  
  // Reset and power up
  writeRegister(NAU7802_PU_CTRL, 0x06);  // Reset
  delay(10);
  writeRegister(NAU7802_PU_CTRL, 0x0E);  // Power up analog, power up digital
  delay(200);
  
  // Check if powered up
  uint8_t status = readRegister(NAU7802_PU_CTRL);
  if (!(status & 0x08)) {
    Serial.print("Failed to initialize ");
    Serial.println(name);
    return false;
  }
  
  // Configure
  writeRegister(NAU7802_CTRL1, 0x00);    // Gain = 128, LDO = 3.0V
  writeRegister(NAU7802_CTRL2, 0x00);    // Gain calibration, 10 SPS

  // Start calibration
  writeRegister(NAU7802_CTRL2, 0x03);    // Calibrate AFE
  delay(300);

  // Start conversion cycle
  writeRegister(NAU7802_PU_CTRL, 0x0F);  // Power up + start conversion (CS bit)
  
  Serial.print(name);
  Serial.print(" initialized on MUX 0x");
  Serial.print(mux_addr, HEX);
  Serial.print(", Channel ");
  Serial.println(channel);
  
  return true;
}

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  Serial.println("\n\n9-Channel ADC Reader - Direct I2C");
  Serial.println("===================================");
  
  Wire.begin();
  Wire.setClock(10000);  // 100kHz - reliable for capacitance

  delay(100);
  
  Serial.println("\nInitializing ADCs...");
  
  // Initialize all 9 ADCs
  for (int i = 0; i < 9; i++) {
    initADC(adcs[i].mux_addr, adcs[i].channel, adcs[i].name);
  }
  
  Serial.println("\nSetup complete!\n");
}

void loop() {
  Serial.println("====================================");
  Serial.println("ADC Readings:");
  Serial.println("====================================");
  
  // Read all 9 ADCs
  for (int i = 0; i < 9; i++) {
    tcaSelect(adcs[i].mux_addr, adcs[i].channel);
    delay(5);
    
    int32_t reading = readADC();
    float voltage = (reading / 16777216.0) * 3.0;  // Convert to voltage
    
    Serial.print(adcs[i].name);
    Serial.print(": ");
    Serial.print(reading);
    Serial.print(" | ");
    Serial.print(voltage, 6);
    Serial.println(" V");
  }
  
  Serial.println();
  delay(1000);  // Read every second
}
