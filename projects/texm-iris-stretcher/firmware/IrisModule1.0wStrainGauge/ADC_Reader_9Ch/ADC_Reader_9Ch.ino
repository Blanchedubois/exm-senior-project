/*
 * 9-Channel Strain Gauge ADC Reader
 *
 * Reads all 9 NAU7802 ADCs through two TCA9548A multiplexers
 * and displays the values continuously
 *
 * Hardware:
 * - MUX1 (0x74): 4 ADCs on channels 0-3
 * - MUX2 (0x75): 5 ADCs on channels 0-4
 */

#include <Wire.h>
#include "SparkFun_Qwiic_Scale_NAU7802_Arduino_Library.h"

// Custom I2C pins
#define I2C_SDA_PIN  3
#define I2C_SCL_PIN  4

// Multiplexer addresses (confirmed from scan)
#define MUX1_ADDRESS 0x74
#define MUX2_ADDRESS 0x75
#define NAU7802_ADDRESS 0x2A

// Channel configuration
#define MUX1_CHANNELS 4
#define MUX2_CHANNELS 5
#define TOTAL_ADCS 9

// NAU7802 Settings
#define NAU7802_GAIN 128
#define NAU7802_SPS 80
#define AVDD_VOLTAGE 3.3

// ADC channel structure
struct ADCChannel {
  uint8_t muxAddress;
  uint8_t muxChannel;
  bool isActive;
  int32_t rawValue;
  float voltage;
};

ADCChannel adcChannels[TOTAL_ADCS];
NAU7802 adc;

// Sampling control
unsigned long lastReadTime = 0;
const unsigned long READ_INTERVAL = 100;  // Read every 100ms (10 Hz)

void setup() {
  Serial.begin(115200);
  while (!Serial) {
    delay(10);
  }

  Serial.println("\n========================================");
  Serial.println("  9-Channel Strain Gauge ADC Reader");
  Serial.println("========================================\n");

  // Initialize I2C
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(100000);

  Serial.print("I2C pins: SDA=");
  Serial.print(I2C_SDA_PIN);
  Serial.print(", SCL=");
  Serial.println(I2C_SCL_PIN);
  Serial.println();

  // Setup ADC channels
  setupADCChannels();

  // Initialize all ADCs
  detectAndConfigureADCs();

  Serial.println("\nStarting continuous reading...");
  Serial.println("Format: ADC1, ADC2, ADC3, ADC4, ADC5, ADC6, ADC7, ADC8, ADC9\n");

  delay(1000);
}

void loop() {
  unsigned long currentTime = millis();

  if (currentTime - lastReadTime >= READ_INTERVAL) {
    lastReadTime = currentTime;

    // Read all ADCs
    readAllADCs();

    // Display values
    displayADCValues();
  }
}

void setupADCChannels() {
  int index = 0;

  // MUX1 - 4 ADCs (channels 0-3)
  for (int ch = 0; ch < MUX1_CHANNELS; ch++) {
    adcChannels[index].muxAddress = MUX1_ADDRESS;
    adcChannels[index].muxChannel = ch;
    adcChannels[index].isActive = false;
    adcChannels[index].rawValue = 0;
    adcChannels[index].voltage = 0.0;
    index++;
  }

  // MUX2 - 5 ADCs (channels 0-4)
  for (int ch = 0; ch < MUX2_CHANNELS; ch++) {
    adcChannels[index].muxAddress = MUX2_ADDRESS;
    adcChannels[index].muxChannel = ch;
    adcChannels[index].isActive = false;
    adcChannels[index].rawValue = 0;
    adcChannels[index].voltage = 0.0;
    index++;
  }
}

void tcaSelect(uint8_t muxAddress, uint8_t channel) {
  if (channel > 7) return;
  Wire.beginTransmission(muxAddress);
  Wire.write(1 << channel);
  Wire.endTransmission();
  delayMicroseconds(100);
}

void tcaDeselect(uint8_t muxAddress) {
  Wire.beginTransmission(muxAddress);
  Wire.write(0);
  Wire.endTransmission();
}

bool initializeADC(uint8_t muxAddress, uint8_t channel) {
  tcaSelect(muxAddress, channel);

  if (adc.begin(Wire, false)) {
    adc.setGain(NAU7802_GAIN);
    adc.setSampleRate(NAU7802_SPS);
    adc.calibrateAFE();
    tcaDeselect(muxAddress);
    return true;
  }

  tcaDeselect(muxAddress);
  return false;
}

void detectAndConfigureADCs() {
  Serial.println("Initializing ADCs...\n");

  int activeCount = 0;

  for (int i = 0; i < TOTAL_ADCS; i++) {
    Serial.print("ADC ");
    Serial.print(i + 1);
    Serial.print(" (MUX 0x");
    Serial.print(adcChannels[i].muxAddress, HEX);
    Serial.print(", Ch");
    Serial.print(adcChannels[i].muxChannel);
    Serial.print("): ");

    if (initializeADC(adcChannels[i].muxAddress, adcChannels[i].muxChannel)) {
      Serial.println("OK");
      adcChannels[i].isActive = true;
      activeCount++;
    } else {
      Serial.println("FAILED");
    }
  }

  Serial.println();
  Serial.print("Active ADCs: ");
  Serial.print(activeCount);
  Serial.print("/");
  Serial.println(TOTAL_ADCS);
}

int32_t readADCRaw(uint8_t adcIndex) {
  if (adcIndex >= TOTAL_ADCS || !adcChannels[adcIndex].isActive) {
    return 0;
  }

  tcaSelect(adcChannels[adcIndex].muxAddress, adcChannels[adcIndex].muxChannel);

  int timeout = 100;
  while (!adc.available() && timeout > 0) {
    delayMicroseconds(100);
    timeout--;
  }

  int32_t rawValue = 0;
  if (timeout > 0) {
    rawValue = adc.getReading();
  }

  tcaDeselect(adcChannels[adcIndex].muxAddress);

  return rawValue;
}

float convertToVoltage(int32_t rawValue) {
  float maxRaw = 8388608.0;  // 2^23
  float voltage = (rawValue / maxRaw) * (AVDD_VOLTAGE / NAU7802_GAIN);
  return voltage;
}

void readAllADCs() {
  for (int i = 0; i < TOTAL_ADCS; i++) {
    if (adcChannels[i].isActive) {
      adcChannels[i].rawValue = readADCRaw(i);
      adcChannels[i].voltage = convertToVoltage(adcChannels[i].rawValue);
    }
  }
}

void displayADCValues() {
  // Option 1: CSV format (easy to log/plot)
  Serial.print(millis());
  Serial.print(",");

  for (int i = 0; i < TOTAL_ADCS; i++) {
    Serial.print(adcChannels[i].rawValue);
    if (i < TOTAL_ADCS - 1) {
      Serial.print(",");
    }
  }
  Serial.println();

  // Option 2: Detailed format (uncomment to use instead)
  /*
  Serial.print("Time: ");
  Serial.print(millis());
  Serial.print(" ms | ");

  for (int i = 0; i < TOTAL_ADCS; i++) {
    Serial.print("ADC");
    Serial.print(i + 1);
    Serial.print(": ");
    Serial.print(adcChannels[i].rawValue);
    Serial.print(" (");
    Serial.print(adcChannels[i].voltage, 6);
    Serial.print("V)");
    if (i < TOTAL_ADCS - 1) {
      Serial.print(" | ");
    }
  }
  Serial.println();
  */
}
