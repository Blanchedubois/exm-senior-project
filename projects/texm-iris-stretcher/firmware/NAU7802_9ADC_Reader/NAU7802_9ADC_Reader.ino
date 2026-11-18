/*
 * NAU7802 9-ADC Reader for ESP32-S3 Feather
 *
 * HARDWARE ADDRESSES (IMPORTANT - REMEMBER THESE!):
 * - Multiplexer 1: 0x71 (Channels 0-3 = ADC 1-4)
 * - Multiplexer 2: 0x73 (Channels 0-4 = ADC 5-9)
 * - NAU7802 ADCs: 0x36 (all 9 ADCs use same address on different mux channels)
 *
 * I2C PINS:
 * - SDA: GPIO 3
 * - SCL: GPIO 4
 * - Clock: 100 kHz
 *
 * WIRING:
 * ESP32-S3 ── GPIO3(SDA), GPIO4(SCL) ── Both Multiplexers
 * MUX 0x71 ── CH0-3 ── NAU7802 ADCs 1-4 (address 0x36 each)
 * MUX 0x73 ── CH0-4 ── NAU7802 ADCs 5-9 (address 0x36 each)
 *
 * LIBRARY REQUIRED:
 * Adafruit_NAU7802 (Install via Library Manager)
 *
 * ADC CONFIGURATION:
 * - LDO: 3.3V (NAU7802_3V3)
 * - Gain: 1x (NAU7802_GAIN_1) - adjust based on sensor
 * - Rate: 320 SPS (NAU7802_RATE_320SPS)
 */

#include <Wire.h>
#include <Adafruit_NAU7802.h>

// I2C Configuration
#define SDA_PIN  3
#define SCL_PIN  4
#define I2C_CLOCK 100000

// I2C Addresses
#define MUX1_ADDR  0x71  // First multiplexer
#define MUX2_ADDR  0x73  // Second multiplexer
#define NAU_ADDR   0x36  // NAU7802 address (same for all)

Adafruit_NAU7802 nau;

// ADC Configuration Structure
struct ADC_Config {
  byte mux_address;
  byte mux_channel;
  String name;
  bool initialized;
};

// Define all 9 ADCs with their multiplexer routing
ADC_Config adcs[9] = {
  // MUX 0x71 - 4 ADCs
  {MUX1_ADDR, 0, "ADC1", false},  // MUX 0x71, Channel 0
  {MUX1_ADDR, 1, "ADC2", false},  // MUX 0x71, Channel 1
  {MUX1_ADDR, 2, "ADC3", false},  // MUX 0x71, Channel 2
  {MUX1_ADDR, 3, "ADC4", false},  // MUX 0x71, Channel 3

  // MUX 0x73 - 5 ADCs
  {MUX2_ADDR, 0, "ADC5", false},  // MUX 0x73, Channel 0
  {MUX2_ADDR, 1, "ADC6", false},  // MUX 0x73, Channel 1
  {MUX2_ADDR, 2, "ADC7", false},  // MUX 0x73, Channel 2
  {MUX2_ADDR, 3, "ADC8", false},  // MUX 0x73, Channel 3
  {MUX2_ADDR, 4, "ADC9", false}   // MUX 0x73, Channel 4
};

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  Serial.println("\n╔════════════════════════════════════════════╗");
  Serial.println("║  NAU7802 9-ADC Reader - ESP32-S3         ║");
  Serial.println("╚════════════════════════════════════════════╝");
  Serial.println("\nHardware Configuration:");
  Serial.println("  • MUX 1: 0x71 (ADC 1-4 on CH 0-3)");
  Serial.println("  • MUX 2: 0x73 (ADC 5-9 on CH 0-4)");
  Serial.println("  • NAU7802: 0x36 (all ADCs)");
  Serial.println("  • I2C: GPIO3(SDA), GPIO4(SCL)");
  Serial.println("════════════════════════════════════════════\n");

  // Initialize I2C
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(I2C_CLOCK);
  delay(1000);

  // Initialize all 9 ADCs
  Serial.println("Initializing ADCs...\n");

  for (int i = 0; i < 9; i++) {
    Serial.print(adcs[i].name);
    Serial.print(" [MUX:0x");
    Serial.print(adcs[i].mux_address, HEX);
    Serial.print(" CH:");
    Serial.print(adcs[i].mux_channel);
    Serial.print("]: ");

    // Enable this multiplexer channel
    enableMuxChannel(adcs[i].mux_address, adcs[i].mux_channel);
    delay(100);

    // Initialize NAU7802
    if (nau.begin()) {
      // Configure ADC
      nau.setLDO(NAU7802_3V3);
      nau.setGain(NAU7802_GAIN_1);  // Adjust based on your sensor
      nau.setRate(NAU7802_RATE_320SPS);

      // Calibrate (do this with zero load!)
      bool cal_success = true;
      if (!nau.calibrate(NAU7802_CALMOD_INTERNAL)) {
        Serial.print("Int.Cal FAIL ");
        cal_success = false;
      }
      if (!nau.calibrate(NAU7802_CALMOD_OFFSET)) {
        Serial.print("Offset.Cal FAIL ");
        cal_success = false;
      }

      if (cal_success) {
        Serial.println("✓ OK");
        adcs[i].initialized = true;
      } else {
        Serial.println("✗ Cal Failed");
      }
    } else {
      Serial.println("✗ Init Failed");
    }

    delay(50);
  }

  // Disable all multiplexer channels
  disableAllMux();

  Serial.println("\n════════════════════════════════════════════");
  Serial.println("Starting continuous readings...\n");
  delay(1000);
}

void loop() {
  Serial.println("┌──────────────────────────────────────────────┐");
  Serial.println("│         NAU7802 ADC READINGS                 │");
  Serial.println("└──────────────────────────────────────────────┘");

  for (int i = 0; i < 9; i++) {
    Serial.print(adcs[i].name);
    Serial.print(" [0x");
    Serial.print(adcs[i].mux_address, HEX);
    Serial.print("-CH");
    Serial.print(adcs[i].mux_channel);
    Serial.print("]: ");

    if (!adcs[i].initialized) {
      Serial.println("Not initialized");
      continue;
    }

    // Enable this channel
    enableMuxChannel(adcs[i].mux_address, adcs[i].mux_channel);
    delay(50);

    // Read ADC value
    if (nau.available()) {
      int32_t raw = nau.read();

      // Convert to voltage
      // For 24-bit ADC with 3.3V reference and gain=1:
      float voltage = (raw - 8388608.0) / 8388607.0 * 3.3;

      Serial.print(raw);
      Serial.print(" = ");
      Serial.print(voltage, 6);
      Serial.println(" V");
    } else {
      Serial.println("No data");
    }
  }

  // Disable all channels
  disableAllMux();

  Serial.println("══════════════════════════════════════════════\n");
  delay(1000);
}

// Enable a specific channel on a multiplexer
void enableMuxChannel(byte mux_addr, byte channel) {
  Wire.beginTransmission(mux_addr);
  Wire.write(1 << channel);  // Set bit for this channel
  Wire.endTransmission();
}

// Disable all channels on both multiplexers
void disableAllMux() {
  Wire.beginTransmission(MUX1_ADDR);
  Wire.write(0x00);  // All channels off
  Wire.endTransmission();

  Wire.beginTransmission(MUX2_ADDR);
  Wire.write(0x00);  // All channels off
  Wire.endTransmission();
}

/*
 * NOTES FOR STRAIN GAUGE USE:
 *
 * 1. Current readings show 3.3V because inputs are tied to rail
 * 2. For strain gauges, connect Wheatstone bridge outputs to:
 *    - VIN+ (positive bridge output)
 *    - VIN- (negative bridge output)
 * 3. Adjust gain based on expected signal:
 *    - Small signals (mV): Use GAIN_64 or GAIN_128
 *    - Larger signals (hundreds of mV): Use GAIN_1 to GAIN_16
 * 4. Calibrate with zero load before measurements
 * 5. For differential measurements, mid-scale = 8388608 = 0V
 */
