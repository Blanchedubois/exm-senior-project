/*
 * 9-Channel Strain Gauge Reader with TCA9548A Multiplexers
 *
 * Hardware Configuration:
 * - 2x TCA9548A I2C Multiplexers
 *   - Multiplexer 1: 4x NAU7802 ADCs (channels 0-3)
 *   - Multiplexer 2: 5x NAU7802 ADCs (channels 0-4)
 * - 9 Strain Gauges in Wheatstone bridge configuration
 *
 * Features:
 * - Automatic device detection
 * - Configurable I2C addresses
 * - Raw voltage output
 * - Serial monitoring at 115200 baud
 */

#include <Wire.h>
#include "SparkFun_Qwiic_Scale_NAU7802_Arduino_Library.h"

// ============= CONFIGURATION =============
// TCA9548A Multiplexer Addresses (default: 0x70, 0x71)
// Modify these if you've changed the address jumpers
#define MUX1_ADDRESS 0x70  // First multiplexer (4 ADCs)
#define MUX2_ADDRESS 0x71  // Second multiplexer (5 ADCs)

// NAU7802 Default Address (all NAU7802s use the same address: 0x2A)
#define NAU7802_ADDRESS 0x2A

// Number of ADCs per multiplexer
#define MUX1_CHANNELS 4
#define MUX2_CHANNELS 5
#define TOTAL_ADCS 9

// NAU7802 Settings
#define NAU7802_GAIN 128  // Gain: 1, 2, 4, 8, 16, 32, 64, 128
#define NAU7802_SPS 80    // Samples per second: 10, 20, 40, 80, 320

// ============= GLOBAL VARIABLES =============
NAU7802 adc;  // Single ADC object (reused for all channels)

// Structure to hold multiplexer and channel info
struct ADCChannel {
  uint8_t muxAddress;
  uint8_t muxChannel;
  bool isActive;
  String label;
};

ADCChannel adcChannels[TOTAL_ADCS];

// ============= FUNCTION PROTOTYPES =============
void tcaSelect(uint8_t muxAddress, uint8_t channel);
void tcaDeselect(uint8_t muxAddress);
bool scanI2C(uint8_t address);
void setupADCChannels();
bool initializeADC(uint8_t muxAddress, uint8_t channel);
void detectAndConfigureDevices();
int32_t readADCRaw(uint8_t adcIndex);
float convertToVoltage(int32_t rawValue);

// ============= SETUP =============
void setup() {
  Serial.begin(115200);
  while (!Serial) {
    delay(10); // Wait for serial port to connect
  }

  Serial.println("\n=======================================");
  Serial.println("9-Channel Strain Gauge System");
  Serial.println("=======================================\n");

  Wire.begin();
  Wire.setClock(400000); // Set I2C to 400kHz

  // Setup ADC channel configuration
  setupADCChannels();

  // Detect and configure all devices
  detectAndConfigureDevices();

  Serial.println("\n=======================================");
  Serial.println("System Ready - Starting Measurements");
  Serial.println("=======================================\n");

  // Print header
  Serial.print("Time(ms)\t");
  for (int i = 0; i < TOTAL_ADCS; i++) {
    if (adcChannels[i].isActive) {
      Serial.print(adcChannels[i].label);
      Serial.print("(V)\t");
    }
  }
  Serial.println();
}

// ============= MAIN LOOP =============
void loop() {
  static unsigned long lastRead = 0;
  unsigned long interval = 100; // Read every 100ms (10Hz)

  if (millis() - lastRead >= interval) {
    lastRead = millis();

    Serial.print(millis());
    Serial.print("\t");

    // Read all active ADC channels
    for (int i = 0; i < TOTAL_ADCS; i++) {
      if (adcChannels[i].isActive) {
        int32_t rawValue = readADCRaw(i);
        float voltage = convertToVoltage(rawValue);

        Serial.print(voltage, 6); // 6 decimal places
        Serial.print("\t");
      }
    }
    Serial.println();
  }
}

// ============= TCA9548A FUNCTIONS =============
/**
 * Select a channel on the TCA9548A multiplexer
 */
void tcaSelect(uint8_t muxAddress, uint8_t channel) {
  if (channel > 7) return;

  Wire.beginTransmission(muxAddress);
  Wire.write(1 << channel);
  Wire.endTransmission();
  delayMicroseconds(100); // Small delay for mux switching
}

/**
 * Deselect all channels on the TCA9548A multiplexer
 */
void tcaDeselect(uint8_t muxAddress) {
  Wire.beginTransmission(muxAddress);
  Wire.write(0);
  Wire.endTransmission();
}

// ============= I2C SCANNING =============
/**
 * Scan for an I2C device at a specific address
 */
bool scanI2C(uint8_t address) {
  Wire.beginTransmission(address);
  uint8_t error = Wire.endTransmission();
  return (error == 0);
}

// ============= SETUP FUNCTIONS =============
/**
 * Configure the ADC channel structure
 */
void setupADCChannels() {
  int index = 0;

  // Multiplexer 1 - 4 ADCs (channels 0-3)
  for (int ch = 0; ch < MUX1_CHANNELS; ch++) {
    adcChannels[index].muxAddress = MUX1_ADDRESS;
    adcChannels[index].muxChannel = ch;
    adcChannels[index].isActive = false;
    adcChannels[index].label = "SG" + String(index + 1);
    index++;
  }

  // Multiplexer 2 - 5 ADCs (channels 0-4)
  for (int ch = 0; ch < MUX2_CHANNELS; ch++) {
    adcChannels[index].muxAddress = MUX2_ADDRESS;
    adcChannels[index].muxChannel = ch;
    adcChannels[index].isActive = false;
    adcChannels[index].label = "SG" + String(index + 1);
    index++;
  }
}

/**
 * Initialize a single NAU7802 ADC on a specific mux channel
 */
bool initializeADC(uint8_t muxAddress, uint8_t channel) {
  tcaSelect(muxAddress, channel);

  if (adc.begin(Wire, false)) {  // false = don't use internal LDO
    // Configure the NAU7802
    adc.setGain(NAU7802_GAIN);
    adc.setSampleRate(NAU7802_SPS);
    adc.calibrateAFE();  // Calibrate analog front end

    tcaDeselect(muxAddress);
    return true;
  }

  tcaDeselect(muxAddress);
  return false;
}

/**
 * Detect all multiplexers and ADCs, then initialize them
 */
void detectAndConfigureDevices() {
  Serial.println("Scanning I2C Bus...\n");

  // Check for Multiplexer 1
  Serial.print("Checking Multiplexer 1 at 0x");
  Serial.print(MUX1_ADDRESS, HEX);
  Serial.print("... ");

  if (scanI2C(MUX1_ADDRESS)) {
    Serial.println("FOUND");

    // Scan all channels on Multiplexer 1
    for (int ch = 0; ch < MUX1_CHANNELS; ch++) {
      Serial.print("  Channel ");
      Serial.print(ch);
      Serial.print(" - NAU7802... ");

      tcaSelect(MUX1_ADDRESS, ch);
      if (scanI2C(NAU7802_ADDRESS)) {
        Serial.print("FOUND - Initializing... ");

        if (initializeADC(MUX1_ADDRESS, ch)) {
          Serial.println("SUCCESS");
          adcChannels[ch].isActive = true;
        } else {
          Serial.println("FAILED");
        }
      } else {
        Serial.println("NOT FOUND");
      }
      tcaDeselect(MUX1_ADDRESS);
    }
  } else {
    Serial.println("NOT FOUND");
  }

  Serial.println();

  // Check for Multiplexer 2
  Serial.print("Checking Multiplexer 2 at 0x");
  Serial.print(MUX2_ADDRESS, HEX);
  Serial.print("... ");

  if (scanI2C(MUX2_ADDRESS)) {
    Serial.println("FOUND");

    // Scan all channels on Multiplexer 2
    for (int ch = 0; ch < MUX2_CHANNELS; ch++) {
      int adcIndex = MUX1_CHANNELS + ch;
      Serial.print("  Channel ");
      Serial.print(ch);
      Serial.print(" - NAU7802... ");

      tcaSelect(MUX2_ADDRESS, ch);
      if (scanI2C(NAU7802_ADDRESS)) {
        Serial.print("FOUND - Initializing... ");

        if (initializeADC(MUX2_ADDRESS, ch)) {
          Serial.println("SUCCESS");
          adcChannels[adcIndex].isActive = true;
        } else {
          Serial.println("FAILED");
        }
      } else {
        Serial.println("NOT FOUND");
      }
      tcaDeselect(MUX2_ADDRESS);
    }
  } else {
    Serial.println("NOT FOUND");
  }

  // Summary
  Serial.println();
  int activeCount = 0;
  for (int i = 0; i < TOTAL_ADCS; i++) {
    if (adcChannels[i].isActive) activeCount++;
  }

  Serial.print("Total Active ADCs: ");
  Serial.print(activeCount);
  Serial.print("/");
  Serial.println(TOTAL_ADCS);
}

// ============= READING FUNCTIONS =============
/**
 * Read raw ADC value from a specific channel
 */
int32_t readADCRaw(uint8_t adcIndex) {
  if (adcIndex >= TOTAL_ADCS || !adcChannels[adcIndex].isActive) {
    return 0;
  }

  tcaSelect(adcChannels[adcIndex].muxAddress, adcChannels[adcIndex].muxChannel);

  // Wait for data to be available
  int timeout = 100;
  while (!adc.available() && timeout > 0) {
    delay(1);
    timeout--;
  }

  int32_t rawValue = 0;
  if (timeout > 0) {
    rawValue = adc.getReading();
  }

  tcaDeselect(adcChannels[adcIndex].muxAddress);

  return rawValue;
}

/**
 * Convert raw ADC reading to voltage
 * NAU7802 is 24-bit ADC with AVDD reference (typically 3.3V or 5V)
 */
float convertToVoltage(int32_t rawValue) {
  // NAU7802 24-bit ADC: range is -8388608 to 8388607
  // Voltage = (rawValue / (2^23)) * (AVDD / Gain)
  // Assuming AVDD = 3.3V (adjust if using 5V)

  float AVDD = 3.3;  // Change to 5.0 if using 5V reference
  float maxRaw = 8388608.0;  // 2^23

  // Calculate voltage accounting for gain
  float voltage = (rawValue / maxRaw) * (AVDD / NAU7802_GAIN);

  return voltage;
}
