#include <Wire.h>
#include <Adafruit_NAU7802.h>

// I²C pins (change if needed)
#define I2C_SDA_PIN 3
#define I2C_SCL_PIN 4

// ─── EDIT THIS ───
// Pick one of these for your desired gain:
//   NAU7802_GAIN_1,  NAU7802_GAIN_2,  NAU7802_GAIN_4,  NAU7802_GAIN_8,
//   NAU7802_GAIN_16, NAU7802_GAIN_32, NAU7802_GAIN_64, NAU7802_GAIN_128
NAU7802_Gain currentGain = NAU7802_GAIN_1;
// ─────────────────

// Reference voltage matching the LDO setting (3.0 V)
const float NAU7802_REF_VOLTAGE = 3.0;

// Adafruit NAU7802 instance
Adafruit_NAU7802 nau;

// Helper to print a human-readable gain
void printGain(NAU7802_Gain g) {
  switch (g) {
    case NAU7802_GAIN_1:   Serial.println("1×");   break;
    case NAU7802_GAIN_2:   Serial.println("2×");   break;
    case NAU7802_GAIN_4:   Serial.println("4×");   break;
    case NAU7802_GAIN_8:   Serial.println("8×");   break;
    case NAU7802_GAIN_16:  Serial.println("16×");  break;
    case NAU7802_GAIN_32:  Serial.println("32×");  break;
    case NAU7802_GAIN_64:  Serial.println("64×");  break;
    case NAU7802_GAIN_128: Serial.println("128×"); break;
    default:               Serial.println("Unknown"); break;
  }
}

// Map the enum gain to its numeric factor
uint16_t gainFactor(NAU7802_Gain g) {
  switch (g) {
    case NAU7802_GAIN_1:   return 1;
    case NAU7802_GAIN_2:   return 2;
    case NAU7802_GAIN_4:   return 4;
    case NAU7802_GAIN_8:   return 8;
    case NAU7802_GAIN_16:  return 16;
    case NAU7802_GAIN_32:  return 32;
    case NAU7802_GAIN_64:  return 64;
    case NAU7802_GAIN_128: return 128;
    default:               return 1;
  }
}

void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);
  Serial.println("\n=== NAU7802 on ESP32: Strain Gauge Measurement ===");

  // Bring up I²C
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Serial.print("Wire on SDA=");
  Serial.print(I2C_SDA_PIN);
  Serial.print("  SCL=");
  Serial.println(I2C_SCL_PIN);

  // Initialize NAU7802
  if (!nau.begin()) {
    Serial.println("Couldn't find NAU7802 – check wiring!");
    while (1) delay(10);
  }
  Serial.println("Found NAU7802");

  // Configure reference and rate
  nau.setLDO(NAU7802_3V0);
  nau.setRate(NAU7802_RATE_10SPS);

  // Set YOUR chosen gain here
  nau.setGain(currentGain);
  Serial.print("PGA gain set to ");
  printGain(currentGain);

  // Flush startup readings
  for (uint8_t i = 0; i < 10; i++) {
    while (!nau.available()) delay(1);
    nau.read();
  }

  // Calibrations
  while (!nau.calibrate(NAU7802_CALMOD_INTERNAL)) {
    Serial.println("Calibrating internal… retry");
    delay(500);
  }
  Serial.println("Internal calibration OK");

  while (!nau.calibrate(NAU7802_CALMOD_OFFSET)) {
    Serial.println("Calibrating offset… retry");
    delay(500);
  }
  Serial.println("Offset calibration OK");

  Serial.println("\n--- Ready! ---\n");
}

void loop() {
  if (nau.available()) {
    int32_t counts = nau.read();
    Serial.print("Raw ADC counts: ");
    Serial.println(counts);
  }
  delay(10);
}