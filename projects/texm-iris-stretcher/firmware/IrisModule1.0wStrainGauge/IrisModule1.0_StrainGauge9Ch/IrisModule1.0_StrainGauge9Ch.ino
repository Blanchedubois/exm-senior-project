#include <Wire.h>
#include <hd44780.h>
#include <hd44780ioClass/hd44780_I2Cexp.h>
#include "USB.h"
#include <math.h>
#include <AccelStepper.h>
#include <SPI.h>
#include <TMCStepper.h>
#include "SparkFun_Qwiic_Scale_NAU7802_Arduino_Library.h"

// =============== 9-Channel Strain Gauge Configuration =================
#define USE_STRAIN_GAUGES 1  // Set to 0 to disable strain gauge reading

// TCA9548A Multiplexer Addresses
// Changed from 0x70/0x71 to avoid conflicts with LCD at 0x3F and device at 0x36
// Configure your TCA9548A hardware: MUX1 with A2=1,A1=0,A0=0 and MUX2 with A2=1,A1=0,A0=1
#define MUX1_ADDRESS 0x74  // First multiplexer (4 ADCs) - was 0x70
#define MUX2_ADDRESS 0x75  // Second multiplexer (5 ADCs) - was 0x71
#define NAU7802_ADDRESS 0x2A

// Number of ADCs per multiplexer
#define MUX1_CHANNELS 4
#define MUX2_CHANNELS 5
#define TOTAL_ADCS 9

// NAU7802 Settings
#define NAU7802_GAIN 128  // Gain: 1, 2, 4, 8, 16, 32, 64, 128
#define NAU7802_SPS 80    // Samples per second: 10, 20, 40, 80, 320
#define AVDD_VOLTAGE 3.3  // Reference voltage (3.3V or 5.0V)

// Structure to hold multiplexer and channel info
struct ADCChannel {
  uint8_t muxAddress;
  uint8_t muxChannel;
  bool isActive;
  int32_t rawValue;
};

ADCChannel adcChannels[TOTAL_ADCS];
NAU7802 adc;  // Single ADC object (reused for all channels)

// Strain gauges are read on EVERY step when output is enabled via menu
// ======================================================

// --------- Stepper Motor Control ---------
#define MAX_CMD_LEN  32
#define STEP_PIN 12
#define DIR_PIN 13

// ---------- Encoder direction and Menu----------
#define ENC_INVERT_DIR 0  // set to 1 to flip rotation direction

#include <stdint.h>
enum class MenuItem : uint8_t;   // forward declare the enum
void runAction(MenuItem it);     // forward declare the function

// ================= USER CONFIG =================
#define USE_INTERNAL_PULLDOWN  1   // 1: use INPUT_PULLDOWN; 0: use INPUT (for external pulldowns)
#define AUTO_DETECT_LCD_ADDRESS 0  // 0: use fixed address (DETECTED: LCD is at 0x3F)
#define FIXED_LCD_ADDRESS 0x3F     // LCD address confirmed via I2C scan
#define CUSTOM_I2C_PINS            // ENABLE custom I2C pins
#define I2C_SDA_PIN  3             // SDA on pin 3
#define I2C_SCL_PIN  4             // SCL on pin 4
// =================================================

// ---------- About/FW metadata ----------
#define FW_NAME     "Iris Stretcher"
#define FW_VERSION  "v1.0.1-SG9"
#define FW_CREATOR  "Tejasvin Shrikanth"
#define FW_LABLINE1 "Kisely Lab"
#define FW_LABLINE2 "CWRU"
#define FW_BUILDDATE __DATE__ //sets date
#define FW_BUILDTIME __TIME__ //sets time

// ============ Iris Stretcher parameters ===========
const bool  strainData = true; // set true to log strain & step data
const float baudrate   = 115200;
const float verBuf     = 2.1;

// Geometry / math constants
const float r0   = 7.1;
const float rp   = 5.25;
const float Y0   = -6.1;     // must be negative
const float E0   = r0 - rp;
const float g    = 15.0;     // gear ratio
const float rPin = 0.5;      // pin offset
const float maxEx = 4.2; // EDIT THIS TO YOUR MAX EXPANSION

float targetEx = 0.123456f;
float theta    = 0.0f;

// Microstepping and motion
const int pulsesPerRev = 1600; // set for your microstepping
unsigned int stepDelayUs = 2000;
float speedBlade = 2.0f;

// AccelStepper just for position bookkeeping
AccelStepper stepper(AccelStepper::DRIVER, STEP_PIN, DIR_PIN);

// -------- Serial command buffer --------
char     commandBuffer[MAX_CMD_LEN];
uint8_t  cmdIndex = 0;
bool     cmdReady = false;

void sendCommand(const char* cmd) {
  Serial.print(cmd);
  Serial.print('\n');
}

// ========== LCD / UI ===========
// Buttons (pressed==HIGH with pulldowns)
const uint8_t BTN_MENU   = A0;
const uint8_t BTN_DOWN   = A1;
const uint8_t BTN_ACCEPT = A2;
const uint8_t ENC_A      = A5;   // encoder A (keep INPUT_PULLUP)
const uint8_t ENC_B      = A4;   // encoder B
const uint8_t ENC_SW     = A3;   // encoder push

// LCD
hd44780_I2Cexp lcd;
const int LCD_COLS = 16, LCD_ROWS = 2;
uint8_t lcdAddress = 0x00; // Will be auto-detected

// Menu
enum class MenuItem : uint8_t { XsetZero, Xzero, Xcalibrate, Xspeed, Xgoto, StrainGauge, Xhelp, Xabout, COUNT };
const char* const MENU_LABELS[] = {"XsetZero","Xzero","Xcalibrate","Xspeed","Xgoto","StrainGauge","Xhelp","Xabout"};
uint8_t menuIndex = 0;

// Strain Gauge Output Control
bool strainGaugeOutputEnabled = false;  // Toggle for strain gauge serial output

// Ranges
const float XSPEED_MIN = 0.1f,  XSPEED_MAX = 5.0f;
// Variable resolution for Xspeed:
const float XSPEED_STEP_COARSE = 0.10f;  // default step
const float XSPEED_STEP_FINE   = 0.01f;  // fine step when toggled

bool xSpeedFineMode = false;  // false = coarse, true = fine

const float XGOTO_MIN  = 1.001f, XGOTO_MAX  = maxEx;
// Variable resolution for Xgoto:
// Variable resolution for Xgoto
const float XGOTO_STEP_FINE   = 0.001f;   // fine increments
const float XGOTO_STEP_COARSE = 0.050f;   // coarse increments

bool xGotoFineMode = false;  // false = coarse, true = fine
float xSpeedValue = 1.0f;
float xGotoValue  = 1.500f;

// Debounced button helper
struct DebouncedButton {
  uint8_t pin; bool activeLevel = true; bool s, r; unsigned long t=0; const unsigned long db=25;
  void begin(uint8_t mode, bool activeHigh){
    pinMode(pin, mode); activeLevel = activeHigh; s = r = digitalRead(pin); t = millis();
  }
  uint8_t edge(){ bool x=digitalRead(pin); unsigned long now=millis();
    if(x!=r){ r=x; t=now; }
    if(now - t >= db && r != s){
      bool wasPressed = (s == activeLevel);
      s = r;
      bool nowPressed = (s == activeLevel);
      if (wasPressed && !nowPressed) return 1; // released
      if (!wasPressed && nowPressed) return 2; // pressed
    }
    return 0;
  }
  bool fell(){ return edge()==2; }
  bool isPressed() const { return s==activeLevel; }
};

// Encoder (detent-latched)
struct Encoder {
  uint8_t a,b;
  uint8_t last=0;
  int8_t accum=0;

  void begin(uint8_t A,uint8_t B){
    a=A; b=B;
    pinMode(a, INPUT_PULLUP);
    pinMode(b, INPUT_PULLUP);
    last = (digitalRead(a)<<1) | digitalRead(b);
  }
  int8_t step(){
    uint8_t s = (digitalRead(a)<<1) | digitalRead(b);
    static const int8_t quad[16] = {
      0,-1,+1, 0,
      +1, 0, 0,-1,
      -1, 0, 0,+1,
       0,+1,-1, 0
    };
    int8_t d = quad[(last<<2)|s];
    last = s;
    if (d) accum += d;
    if ((s==0 || s==3) && (accum >= 4 || accum <= -4)) {
      int8_t out = (accum > 0) ? +1 : -1;
      accum = 0;
      return out;
    }
    return 0;
  }
} enc;

// UI state
enum class UiState : uint8_t { MENU, RUNNING, EDIT_XSPEED, EDIT_XGOTO, EDIT_STRAINGAUGE };
UiState ui = UiState::MENU;
unsigned long statusUntil = 0;

// Menu actions now do real work
__attribute__((weak)) void XsetZero(){        // set current position as zero
  zeroAndLogStepperPosition();
}
__attribute__((weak)) void Xzero(){           // move back to theta = 0
  goToZeroPosition();
}
__attribute__((weak)) void Xcalibrate(){      // your calibration routine
  stepperMotorCalibration();
}
__attribute__((weak)) void Xspeed(float v){   // set blade speed
  setAngularSpeed(v);
}
__attribute__((weak)) void Xgoto(float ex){   // compute theta for Ex and move
  double angle = findThetaHighPrec(ex, r0, rp, Y0, E0, 0.0001, 0.6);
  if (ex <= 1.001 || ex >= maxEx || isnan(angle)) {
    Serial.println("Error: no valid θ found for that targetEx");
    return;
  }
  Serial.print("Computed θ (rad): "); Serial.println(angle, 10);
  double actualEx = computeEx(r0, rp, Y0, angle, E0);
  Serial.print("Resulting expansion: "); Serial.println(actualEx, 10);
  rotateThetaRadians((float)angle);
}

// Utils
template<typename T> T clamp(T v,T lo,T hi){ if(v<lo) return lo; if(v>hi) return hi; return v; }
float roundToStep(float x,float st){ return (float)((long)lround(x/st))*st; }
void printFloatFixed(float v, uint8_t places){
  long scale=1; for(uint8_t i=0;i<places;i++) scale*=10;
  long s = lround(v*scale); long ip = s/scale; long fp = labs(s%scale);
  lcd.print(ip); lcd.print('.');
  long div = scale/10;
  for(uint8_t i=1;i<places;i++){ if(fp<div) lcd.print('0'); div/=10; }
  lcd.print(fp);
}


// Buttons
DebouncedButton btnMenu  { BTN_MENU };
DebouncedButton btnDown  { BTN_DOWN };
DebouncedButton btnAccept{ BTN_ACCEPT };
DebouncedButton btnEncSW { ENC_SW };

// Drawing
void drawMenu(){
  lcd.clear();
  lcd.setCursor(0,0); lcd.write(byte(0x7E)); lcd.print(MENU_LABELS[menuIndex]);
  lcd.setCursor(0,1); lcd.print(' ');
  uint8_t next=(menuIndex+1)%(uint8_t)MenuItem::COUNT;
  lcd.print(MENU_LABELS[next]);
}
void drawStatus(const char* msg){
  lcd.clear();
  lcd.setCursor(0,0); lcd.print(msg);
  lcd.setCursor(0,1); lcd.print("Running...");
}
void drawEditXspeed(){
  lcd.clear();
  lcd.setCursor(0,0); lcd.print("Xspeed:");
  lcd.setCursor(0,1);
  // show more precision in fine mode
  printFloatFixed(xSpeedValue, xSpeedFineMode ? 2 : 1);
  lcd.print(xSpeedFineMode ? " F" : " C");   // F=fine, C=coarse
  lcd.print("  [SW]");
}

void drawEditXgoto(){
  lcd.clear();
  lcd.setCursor(0,0); lcd.print("Xgoto:");
  lcd.setCursor(0,1);
  // fewer decimals in coarse, more in fine
  printFloatFixed(xGotoValue, xGotoFineMode ? 3 : 2);
  lcd.print(xGotoFineMode ? " F" : " C");  // F=fine, C=coarse
  lcd.print("  [SW]");
}

void drawEditStrainGauge(){
  lcd.clear();
  lcd.setCursor(0,0); lcd.print("Strain Gauge:");
  lcd.setCursor(0,1);
  if (strainGaugeOutputEnabled) {
    lcd.print("ON  [Turn OFF]");
  } else {
    lcd.print("OFF [Turn ON]");
  }
}

void drawHelp(){
  lcd.clear(); lcd.setCursor(0,0); lcd.print("Commands:"); lcd.setCursor(0,1); lcd.print("________"); delay(1200);
  lcd.clear(); lcd.setCursor(0,0); lcd.print("1.Xgoto <v>"); lcd.setCursor(0,1); lcd.print("  move to Ex"); delay(1200);
  lcd.clear(); lcd.setCursor(0,0); lcd.print("2.Xzero");      lcd.setCursor(0,1); lcd.print("  moves to 1x"); delay(1200);
  lcd.clear(); lcd.setCursor(0,0); lcd.print("3.XsetZero");   lcd.setCursor(0,1); lcd.print("  Ex=1x here"); delay(1200);
  lcd.clear(); lcd.setCursor(0,0); lcd.print("4.Xcalibrate"); lcd.setCursor(0,1); lcd.print("  calibrates"); delay(1200);
  lcd.clear(); lcd.setCursor(0,0); lcd.print("5.Xspeed <v>"); lcd.setCursor(0,1); lcd.print("  cm/s");       delay(1200);
  lcd.clear(); lcd.setCursor(0,0); lcd.print("6.Xhelp");      lcd.setCursor(0,1); lcd.print("  this msg");   delay(1200);
}
void drawAbout(){
  lcd.clear(); lcd.setCursor(0,0); lcd.print(FW_NAME); lcd.setCursor(0,1); lcd.print("FW "); lcd.print(FW_VERSION); delay(1000);
  lcd.clear(); lcd.setCursor(0,0); lcd.print("Build:"); lcd.setCursor(0,1); lcd.print(FW_BUILDDATE); delay(900);
  lcd.clear(); lcd.setCursor(0,0); lcd.print("Time:");  lcd.setCursor(0,1); lcd.print(FW_BUILDTIME); delay(900);
  lcd.clear(); lcd.setCursor(0,0); lcd.print("Creator:"); lcd.setCursor(0,1); lcd.print(FW_CREATOR); delay(1000);
  lcd.clear(); lcd.setCursor(0,0); lcd.print(FW_LABLINE1); lcd.setCursor(0,1); lcd.print(FW_LABLINE2); delay(900);
  lcd.clear(); lcd.setCursor(0,0); lcd.print("Encoder dir:"); lcd.setCursor(0,1);
#if ENC_INVERT_DIR
  lcd.print("inverted");
#else
  lcd.print("normal");
#endif
  delay(800);
  lcd.clear(); lcd.setCursor(0,0); lcd.print("Buttons:"); lcd.setCursor(0,1);
#if USE_INTERNAL_PULLDOWN
  lcd.print("INT pulldown");
#else
  lcd.print("EXT pulldown");
#endif
  delay(800);
}

// Actions
void runAction(MenuItem it){
  switch(it){
    case MenuItem::XsetZero:    drawStatus("XsetZero");   XsetZero();   statusUntil=millis()+1000; ui=UiState::RUNNING; break;
    case MenuItem::Xzero:       drawStatus("Xzero");      Xzero();      statusUntil=millis()+1000; ui=UiState::RUNNING; break;
    case MenuItem::Xcalibrate:  drawStatus("Xcalibrate"); Xcalibrate(); statusUntil=millis()+1000; ui=UiState::RUNNING; break;
    case MenuItem::Xspeed:      ui=UiState::EDIT_XSPEED;  drawEditXspeed(); break;
    case MenuItem::Xgoto:       ui=UiState::EDIT_XGOTO;   drawEditXgoto();  break;
    case MenuItem::StrainGauge: ui=UiState::EDIT_STRAINGAUGE; drawEditStrainGauge(); break;
    case MenuItem::Xhelp:       drawHelp();  statusUntil=millis()+3000; ui=UiState::RUNNING; break;
    case MenuItem::Xabout:      drawAbout(); statusUntil=millis()+3000; ui=UiState::RUNNING; break;
    default: break;
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
  delayMicroseconds(100);
}

/**
 * Deselect all channels on the TCA9548A multiplexer
 */
void tcaDeselect(uint8_t muxAddress) {
  Wire.beginTransmission(muxAddress);
  Wire.write(0);
  Wire.endTransmission();
}

/**
 * Scan for an I2C device at a specific address
 */
bool scanI2C(uint8_t address) {
  Wire.beginTransmission(address);
  uint8_t error = Wire.endTransmission();
  return (error == 0);
}

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
    adcChannels[index].rawValue = 0;
    index++;
  }

  // Multiplexer 2 - 5 ADCs (channels 0-4)
  for (int ch = 0; ch < MUX2_CHANNELS; ch++) {
    adcChannels[index].muxAddress = MUX2_ADDRESS;
    adcChannels[index].muxChannel = ch;
    adcChannels[index].isActive = false;
    adcChannels[index].rawValue = 0;
    index++;
  }
}

/**
 * Initialize a single NAU7802 ADC on a specific mux channel
 */
bool initializeADC(uint8_t muxAddress, uint8_t channel) {
  tcaSelect(muxAddress, channel);

  if (adc.begin(Wire, false)) {  // false = don't use internal LDO
    adc.setGain(NAU7802_GAIN);
    adc.setSampleRate(NAU7802_SPS);
    adc.calibrateAFE();
    tcaDeselect(muxAddress);
    return true;
  }

  tcaDeselect(muxAddress);
  return false;
}

/**
 * Detect all multiplexers and ADCs, then initialize them
 */
void detectAndConfigureStrainGauges() {
  Serial.println("\n=== Strain Gauge System Initialization ===");
  Serial.println("Scanning I2C Bus for Multiplexers and ADCs...\n");

  // Check for Multiplexer 1
  Serial.print("Checking Multiplexer 1 at 0x");
  Serial.print(MUX1_ADDRESS, HEX);
  Serial.print("... ");

  if (scanI2C(MUX1_ADDRESS)) {
    Serial.println("FOUND");

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

  Serial.print("Total Active Strain Gauges: ");
  Serial.print(activeCount);
  Serial.print("/");
  Serial.println(TOTAL_ADCS);
  Serial.println("==========================================\n");
}

/**
 * Read raw ADC value from a specific channel
 */
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

/**
 * Read all 9 strain gauge ADCs quickly
 */
void readAllStrainGauges() {
  for (int i = 0; i < TOTAL_ADCS; i++) {
    if (adcChannels[i].isActive) {
      adcChannels[i].rawValue = readADCRaw(i);
    }
  }
}

/**
 * Convert raw ADC reading to voltage
 */
float convertToVoltage(int32_t rawValue) {
  float maxRaw = 8388608.0;  // 2^23
  float voltage = (rawValue / maxRaw) * (AVDD_VOLTAGE / NAU7802_GAIN);
  return voltage;
}

/**
 * Output strain gauge data with step count
 * Format: Steps:<count>:Arm1:<value>:Arm2:<value>:...:Arm9:<value>
 * Only outputs if strainGaugeOutputEnabled is true
 */
void outputStrainGaugeData(long stepCount) {
  if (!strainGaugeOutputEnabled) {
    return;  // Don't output if disabled
  }

  Serial.print("Steps:");
  Serial.print(stepCount);

  for (int i = 0; i < TOTAL_ADCS; i++) {
    Serial.print(":Arm");
    Serial.print(i + 1);
    Serial.print(":");
    if (adcChannels[i].isActive) {
      Serial.print(adcChannels[i].rawValue);
    } else {
      Serial.print("0");
    }
  }
  Serial.println();
}

// ======== I2C Scanner ========
uint8_t scanI2CForLCD() {
  Serial.println("Scanning I2C bus for LCD...");
  uint8_t foundAddress = 0x00;
  uint8_t deviceCount = 0;

  // Scan ONLY common LCD addresses first to avoid conflicts with multiplexers
  uint8_t lcdAddresses[] = {0x27, 0x3F};

  for (uint8_t i = 0; i < 2; i++) {
    uint8_t address = lcdAddresses[i];
    Wire.beginTransmission(address);
    uint8_t error = Wire.endTransmission();

    if (error == 0) {
      Serial.print("I2C device found at address 0x");
      if (address < 16) Serial.print("0");
      Serial.print(address, HEX);
      Serial.println(" -> LCD detected!");
      foundAddress = address;
      deviceCount++;
      break;  // Found LCD, stop scanning
    }
  }

  if (foundAddress == 0x00) {
    Serial.println("No LCD found at common addresses (0x27, 0x3F)");
    Serial.println("Performing full scan (may conflict with multiplexers)...");

    // Full scan as fallback
    for (uint8_t address = 0x20; address <= 0x3F; address++) {
      // Skip multiplexer addresses
      if (address == MUX1_ADDRESS || address == MUX2_ADDRESS || address == NAU7802_ADDRESS) {
        continue;
      }

      Wire.beginTransmission(address);
      uint8_t error = Wire.endTransmission();

      if (error == 0) {
        Serial.print("I2C device found at address 0x");
        if (address < 16) Serial.print("0");
        Serial.print(address, HEX);
        Serial.println();

        if (foundAddress == 0x00) {
          foundAddress = address;
        }
        deviceCount++;
      }
    }
  }

  if (deviceCount == 0) {
    Serial.println("No I2C devices found in LCD range!");
  } else {
    Serial.print("Found ");
    Serial.print(deviceCount);
    Serial.println(" potential LCD device(s)");
  }

  if (foundAddress != 0x00) {
    Serial.print("Using LCD address: 0x");
    if (foundAddress < 16) Serial.print("0");
    Serial.println(foundAddress, HEX);
  }

  return foundAddress;
}

// ======== setup ========
void setup(){
  delay(500);
  USB.begin();
  Serial.begin((unsigned long)baudrate);
  while (!Serial) {}

#ifdef CUSTOM_I2C_PINS
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
#else
  Wire.begin();
#endif

  Wire.setClock(100000); // Set I2C to 100kHz for better stability with multiple devices

  // LCD Initialization
#if AUTO_DETECT_LCD_ADDRESS
  Serial.println("Scanning I2C bus to identify LCD address...");
  lcdAddress = scanI2CForLCD();

  if (lcdAddress == 0x00) {
    Serial.println("WARNING: No I2C LCD detected in scan - using default 0x3F");
    lcdAddress = 0x3F;  // Default fallback
  }
#else
  lcdAddress = FIXED_LCD_ADDRESS;
  Serial.print("Using fixed LCD address: 0x");
  if (lcdAddress < 16) Serial.print("0");
  Serial.println(lcdAddress, HEX);
#endif

  // Initialize LCD
  Serial.print("Initializing LCD at 0x");
  if (lcdAddress < 16) Serial.print("0");
  Serial.print(lcdAddress, HEX);
  Serial.println("...");

  int status = lcd.begin(LCD_COLS, LCD_ROWS);

  if (status) {
    Serial.print("LCD initialization failed! Status: ");
    Serial.println(status);
    Serial.println("ERROR: LCD not responding!");
    Serial.println("Check I2C connections (SDA=3, SCL=4) and LCD power");
  } else {
    Serial.println("LCD initialized successfully!");
  }

  // Properly initialize the display with delays
  delay(100);
  lcd.clear();
  delay(50);
  lcd.backlight();
  delay(100);

  // Extra initialization sequence for stubborn displays
  lcd.home();
  delay(50);
  lcd.clear();
  delay(50);

#if USE_INTERNAL_PULLDOWN
  btnMenu.begin(  INPUT_PULLDOWN, true);
  btnDown.begin(  INPUT_PULLDOWN, true);
  btnAccept.begin(INPUT_PULLDOWN, true);
  btnEncSW.begin( INPUT_PULLDOWN, true);
#else
  btnMenu.begin(  INPUT, true);
  btnDown.begin(  INPUT, true);
  btnAccept.begin(INPUT, true);
  btnEncSW.begin( INPUT, true);
#endif

  enc.begin(ENC_A, ENC_B);

  // Display splash screen only if LCD initialized successfully
  if (status == 0) {
    lcd.clear();
    delay(50);
    lcd.setCursor(0,0);
    lcd.print(FW_NAME);
    lcd.setCursor(0,1);
    lcd.print(FW_LABLINE1);
    Serial.println("Splash screen displayed");
    delay(1500);

    // Show LCD I2C address info
    lcd.clear();
    lcd.setCursor(0,0);
    lcd.print("LCD @ 0x");
    if (lcdAddress < 16) lcd.print("0");
    lcd.print(lcdAddress, HEX);
    lcd.setCursor(0,1);
    lcd.print("I2C OK!");
    delay(1000);

    drawMenu();
  } else {
    Serial.println("Skipping LCD display - initialization failed");
    Serial.println("Device will still work via Serial commands");
  }

#if USE_STRAIN_GAUGES
  // Initialize 9-channel strain gauge system
  setupADCChannels();
  detectAndConfigureStrainGauges();
#endif

  // Banner
  Serial.println(" ___      _       ____  _            _       _               ");
  Serial.println("|_ _|_ __(_)___  / ___|| |_ _ __ ___| |_ ___| |__   ___ _ __ ");
  Serial.println(" | || '__| / __| \\___ \\| __| '__/ _ \\ __/ __| '_ \\ / _ \\ '__|");
  Serial.println(" | || |  | \\__ \\  ___) | |_| | |  __/ || (__| | | |  __/ |   ");
  Serial.println("|___|_|  |_|___/ |____/ \\__|_|  \\___|\\__\\___|_| |_|\\___|_|   ");
  Serial.println("+===============+");
  Serial.print("|KiselyLab V"); Serial.print(verBuf); Serial.println("|");
  Serial.println("+===============+");
  Serial.println("Commands:");
  Serial.println("________");
  Serial.println(" Xgoto <value>        – move to Target Expansion");
  Serial.println(" Xzero                – drive motor to zero Position");
  Serial.println(" XsetZero             – reset position counter to 0");
  Serial.println(" Xcalibrate           – run calibration routine");
  Serial.println(" Xspeed <value> cm/s  – changes expansion speed (cm/s approx)");
  Serial.println(" Xhelp                – this message");

  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN,  OUTPUT);
}

// ======== Math / driver helper functions ========
    //Finds the degree of expansion of the cell by inputing the theta
      float computeEx(float r0, float rp, float y0, float Theta, float E0) {
        // slope μ
        float theta = Theta - (M_PI/2);
        Serial.print("theta: ");
        Serial.println(Theta);
        float mu = (r0 * sin(theta) - y0) / (r0 * cos(theta));

        // quadratic coefficients A·x² + b·x + c = 0
        float A = 1.0f + mu * mu;
        float b = -2.0f * r0 * cos(theta)
                  - 2.0f * r0 * sin(theta) * mu
                  + 2.0f * mu * y0;
        float c = r0 * r0
                  - 2.0f * r0 * sin(theta) * y0
                  + y0 * y0
                  - rp * rp;

        // discriminant
        float disc = b * b - 4.0f * A * c;
        // (optional: handle disc < 0 error here)
        float sqrt_disc = sqrt(disc);

        // choose the "–√" root
        float x = (-b - sqrt_disc) / (2.0f * A);

        // final Eₓ
        float underRoot = A * x * x + 2.0f * mu * y0 * x + y0 * y0;
        Serial.print("Computed expansion: ");
        Serial.println( sqrt(underRoot) / E0);
        float FinalExpansion = (sqrt(underRoot)- rPin) / (E0 - rPin);
        return FinalExpansion;

      }
      double findThetaHighPrec(
        double targetEx,
        double r0, double rp, double y0, double E0,
        double thetaLow, double thetaHigh
      ) {
        // normalized-shifted target (extension ratio)
        double shift = targetEx;

        // 1) bracket check
        double fLow  = computeEx(r0, rp, y0, thetaLow,  E0) - shift;
        double fHigh = computeEx(r0, rp, y0, thetaHigh, E0) - shift;
        if (fLow * fHigh > 0) return NAN;

        // 2) bisection to narrow bracket
        for (int i = 0; i < 50; i++) {
          double mid  = 0.5 * (thetaLow + thetaHigh);
          double fmid = computeEx(r0, rp, y0, mid, E0) - shift;
          if (fLow * fmid <= 0) {
            thetaHigh = mid;
            fHigh     = fmid;
          } else {
            thetaLow = mid;
            fLow     = fmid;
          }
        }

        // 3) Newton–Raphson with NaN/Inf check
        double theta     = 0.5 * (thetaLow + thetaHigh);
        const double tolF     = 1e-10;
        const double tolTheta = 1e-10;
        const double eps      = 1e-8;

        for (int iter = 0; iter < 50; iter++) {
          double f = computeEx(r0, rp, y0, theta, E0) - shift;
          if (fabs(f) < tolF) break;

          double f1 = computeEx(r0, rp, y0, theta + eps, E0) - shift;
          double f2 = computeEx(r0, rp, y0, theta - eps, E0) - shift;
          double fp = (f1 - f2) / (2.0 * eps);

          double prevTheta = theta;
          double dtheta    = -f / fp;
          theta += dtheta;

          // if we blow up to NaN or Inf, revert and stop
          if (isnan(theta) || isinf(theta)) {
            theta = prevTheta;
            break;
          }
          if (fabs(dtheta) < tolTheta) break;
        }

        return theta;
      }

    void rotateThetaRadians(float theta) {
      float stepsPerRad = (pulsesPerRev * g) / (2.0f * M_PI);
      long targetSteps  = lround(theta * stepsPerRad);
      long currentSteps = stepper.currentPosition();
      long deltaSteps   = targetSteps - currentSteps;
      bool dir = (deltaSteps >= 0);
      digitalWrite(DIR_PIN, dir ? HIGH : LOW);

      long stepsToMove = labs(deltaSteps);

      for (long i = 0; i < stepsToMove; ++i) {
        digitalWrite(STEP_PIN, HIGH);
        delayMicroseconds(stepDelayUs);
        digitalWrite(STEP_PIN, LOW);
        delayMicroseconds(stepDelayUs);

#if USE_STRAIN_GAUGES
        // Read strain gauges every step
        if (strainData) {
          readAllStrainGauges();
          outputStrainGaugeData(i);
        }
#else
        if (strainData) {
          Serial.print("Steps, ");
          Serial.println(i);
        }
#endif

        if (dir) stepper.setCurrentPosition(currentSteps + (i + 1));
        else     stepper.setCurrentPosition(currentSteps - (i + 1));
      }

      Serial.print("Moved "); Serial.print(deltaSteps);
      Serial.print(" steps, new position = "); Serial.println(stepper.currentPosition());
    }

    long stepperMotorPosition() {
      stepper.run();
      long pos = stepper.currentPosition();
      Serial.print("Current position (steps): "); Serial.println(pos);
      return pos;
    }

    void goToZeroPosition() {
      long startPos = stepperMotorPosition();
      Serial.print("Moving back to zero from "); Serial.print(startPos); Serial.println(" steps…");
      rotateThetaRadians(0.0f);
      Serial.println("Motor is now at zero position (θ = 0).");
    }

    void zeroAndLogStepperPosition() {
      long current = stepperMotorPosition();
      stepper.setCurrentPosition(0);
      Serial.print("Internal counter reset to zero. Previous position was: ");
      Serial.println(current);
    }

    void stepperMotorCalibration(){
      Serial.println("Starting calibration...");
      // example moves (tune to your rig)
      rotateThetaRadians(0.7f);
      zeroAndLogStepperPosition();
      Serial.println("Moving back in by -0.290 rad...");
      rotateThetaRadians(-0.287f);
      zeroAndLogStepperPosition();
      Serial.println("Setting Zero");
      zeroAndLogStepperPosition();
      Serial.println("Calibration complete.");
    }

    unsigned int microsecondsForOmega(double bladeSpeed) {
      double omega = bladeSpeed / 13.6; // convert linear blade speed into angular speed
      if (omega <= 0.0) return 0;
      double delayUs = (M_PI*(1e6)) / (omega * pulsesPerRev * g);
      return (unsigned int)lround(delayUs);
    }
    void setAngularSpeed(double bladeSpeed) {
      stepDelayUs = microsecondsForOmega(bladeSpeed);
      Serial.print("Step pulse half‐period delay set to ");
      Serial.print(stepDelayUs); Serial.println(" µs");
    }

    // ======== command parser ========
    void parseCommand() {
      if (commandBuffer[0] != 'X') {
        Serial.println("Invalid prefix. Commands must start with 'X'.");
        return;
      }
      char *p = commandBuffer + 1;
      char *cmd = strtok(p, " ");
      if (!cmd) return;

      if (strcmp(cmd, "goto") == 0) {
        char *arg = strtok(NULL, " ");
        if (!arg) { Serial.println("Usage: Xgoto <targetEx>"); return; }
        double tEx = atof(arg);
        double angle = findThetaHighPrec(tEx, r0, rp, Y0, E0, 0.0001, 0.6);
        if (tEx <= 1.001 || tEx >= maxEx || isnan(angle)) {
          Serial.println("Error: no valid θ found for that targetEx");
        } else {
          Serial.print("Computed θ (rad): "); Serial.println(angle, 10);
          double actualEx = computeEx(r0, rp, Y0, angle, E0);
          Serial.print("Resulting expansion: "); Serial.println(actualEx, 10);
          rotateThetaRadians((float)angle);
        }
      } else if (strcmp(cmd, "zero") == 0) {
        goToZeroPosition();
      } else if (strcmp(cmd, "setZero") == 0) {
        zeroAndLogStepperPosition();
      } else if (strcmp(cmd, "help") == 0) {
        Serial.println("Commands:");
        Serial.println("________");
        Serial.println(" Xgoto <value>        – move to Target Expansion");
        Serial.println(" Xzero                – drive motor to zero Position");
        Serial.println(" XsetZero             – reset position counter to 0");
        Serial.println(" Xcalibrate           – run calibration routine");
        Serial.println(" Xspeed <value> cm/s  – changes the speed (cm/s approx)");
        Serial.println(" Xhelp                – this message");
      } else if (strcmp(cmd, "calibrate") == 0) {
        stepperMotorCalibration();
      } else if (strcmp(cmd, "speed") == 0) {
        char *arg = strtok(NULL, " ");
        if (!arg) { Serial.println("Usage: Xspeed <bladeSpeed_cm/s>"); }
        else {
          double sb = atof(arg);
          if (sb <= 0.0) Serial.println("Error: speed must be > 0");
          else { Serial.print("Blade speed set to: "); Serial.print(sb,4); Serial.println(" cm/s"); setAngularSpeed(sb); }
        }
      } else {
        Serial.print("Unknown command: "); Serial.println(cmd);
      }
    }

// ======== loop ========
void loop(){
  int8_t ed = enc.step();
#if ENC_INVERT_DIR
  ed = -ed;
#endif

  switch(ui){
    case UiState::MENU: {
      if (ed == +1) {
        menuIndex = (menuIndex + 1) % (uint8_t)MenuItem::COUNT; drawMenu();
      } else if (ed == -1) {
        menuIndex = (menuIndex + (uint8_t)MenuItem::COUNT - 1) % (uint8_t)MenuItem::COUNT; drawMenu();
      }

      // NOTE: buttons were already begun in setup; these instances match
      if (btnDown.fell())   { menuIndex=(menuIndex+1)%(uint8_t)MenuItem::COUNT; drawMenu(); }
      if (btnAccept.fell()) { runAction(static_cast<MenuItem>(menuIndex)); }
      if (btnMenu.fell())   { lcd.noBacklight(); delay(60); lcd.backlight(); }
    } break;

    case UiState::RUNNING:
      if (millis() >= statusUntil) { ui=UiState::MENU; drawMenu(); }
      break;

    case UiState::EDIT_XSPEED: {
      // Toggle fine/coarse on DOWN press
      if (btnEncSW.fell()) {
        xSpeedFineMode = !xSpeedFineMode;
        drawEditXspeed();
      }

      float step = xSpeedFineMode ? XSPEED_STEP_FINE : XSPEED_STEP_COARSE;

      if (ed == +1) {
        xSpeedValue = clamp(roundToStep(xSpeedValue + step, step), XSPEED_MIN, XSPEED_MAX);
        drawEditXspeed();
      } else if (ed == -1) {
        xSpeedValue = clamp(roundToStep(xSpeedValue - step, step), XSPEED_MIN, XSPEED_MAX);
        drawEditXspeed();
      }

      // Commit only if DOWN isn't held (prevents accidental commit while toggling)
      if ((btnEncSW.fell() || btnAccept.fell()) && !btnDown.isPressed()){
        drawStatus("Xspeed set");
        Xspeed(xSpeedValue);                 // applies speed (your function)
        statusUntil = millis() + 800;
        ui = UiState::RUNNING;
      }

      // Optional: MENU exits editor
      if (btnMenu.fell()) { ui = UiState::MENU; drawMenu(); }
    } break;

      case UiState::EDIT_XGOTO: {
    // Toggle fine/coarse when DOWN is pressed (debounced edge)
    if (btnEncSW.fell()) {
      xGotoFineMode = !xGotoFineMode;
      drawEditXgoto();
    }

    // Step size follows the current mode
    float step = xGotoFineMode ? XGOTO_STEP_FINE : XGOTO_STEP_COARSE;

    if (ed == +1) {
      xGotoValue = clamp(roundToStep(xGotoValue + step, step), XGOTO_MIN, XGOTO_MAX);
      drawEditXgoto();
    } else if (ed == -1) {
      xGotoValue = clamp(roundToStep(xGotoValue - step, step), XGOTO_MIN, XGOTO_MAX);
      drawEditXgoto();
    }

    // Commit only if modifier isn't held down (extra safety)
    if ((btnEncSW.fell() || btnAccept.fell()) && !btnDown.isPressed()){
      drawStatus("Xgoto set");
      Xgoto(xGotoValue);
      statusUntil = millis() + 800;
      ui = UiState::RUNNING;
    }

    // Optional: allow MENU to exit editor
    if (btnMenu.fell()) { ui = UiState::MENU; drawMenu(); }
  } break;

    case UiState::EDIT_STRAINGAUGE: {
    // Toggle strain gauge output with encoder rotation or accept button
    if (ed == +1 || ed == -1 || btnAccept.fell()) {
      strainGaugeOutputEnabled = !strainGaugeOutputEnabled;
      drawEditStrainGauge();

      // Log change to serial monitor
      Serial.print("Strain Gauge Output: ");
      Serial.println(strainGaugeOutputEnabled ? "ENABLED" : "DISABLED");
    }

    // Optional: allow MENU to exit editor
    if (btnMenu.fell()) {
      ui = UiState::MENU;
      drawMenu();
    }
  } break;

  }

  // ---- serial command reader ----
  while (Serial.available() && !cmdReady) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (cmdIndex > 0) { commandBuffer[cmdIndex] = '\0'; cmdReady = true; }
    } else if (cmdIndex < MAX_CMD_LEN - 1) {
      commandBuffer[cmdIndex++] = c;
    }
  }
  if (cmdReady) {
    parseCommand();
    cmdIndex = 0; cmdReady = false;
  }
}
