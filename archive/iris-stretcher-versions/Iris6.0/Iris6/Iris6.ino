#include "USB.h"
#include <math.h>
#include <AccelStepper.h>
#include <SPI.h>
#include <TMCStepper.h>
#include <Wire.h>
#include <Adafruit_NAU7802.h>
#include <LiquidCrystal_I2C.h>

Adafruit_NAU7802 nau;
#define NAU7802_REF_VOLTAGE 3.0       // V, should match your LDO setting
NAU7802_Gain currentGain = NAU7802_GAIN_1;

#define MAX_CMD_LEN  32
#define STEP_PIN 12
#define DIR_PIN 13
#define MS2 9
#define MS1 8

// I²C pins (ESP32)
#if defined(ARDUINO_ARCH_ESP32)
  #define I2C_SDA_PIN 3  
  #define I2C_SCL_PIN 4
#endif

LiquidCrystal_I2C* lcd = nullptr; // must exist before any LCD helper uses it
void IRAM_ATTR encISR();   

// === Rotary Encoder (no push switch) ===
#define ENC_A_PIN A4
#define ENC_B_PIN A5


// === Button on A2 (pressed => HIGH) ===
#define BUTTON_PIN A2
const unsigned long BUTTON_DEBOUNCE_MS = 30;
int  btnStable      = LOW;
int  btnLastReading = LOW;
unsigned long btnLastChangeMs = 0;

// Encoder state
volatile long encTicks = 0;     // signed cumulative ticks
volatile uint8_t encState = 0;  // last 2 bits of A/B

// Dialed expansion (what the knob sets, but NOT yet moved to)
float dialEx = 1.000f;          // start at 1.000×; adjust if you prefer

// Mapping from encoder ticks -> expansion increments
const int   TICKS_PER_DETENT = 4;       // many encoders give 4 edges per detent
const float STEP_EX_PER_DETENT = 0.010; // change 1.0% per detent; tune as you like

// ----- LCD helpers -----
void lcdShowDialExpansion(float ex) {
  if (!lcd) return;
  lcd->clear();
  lcd->setCursor(0,0); lcd->print("Dial Ex:");
  lcd->setCursor(0,1);
  char buf[17];
  snprintf(buf, sizeof(buf), "%.3f x", ex);
  lcd->print(buf);
}

// (you already have lcdSayExpansionSet(ex) that prints "Expansion set to:" on LCD)





uint8_t findLcdAddress() {
  // First check the common PCF8574 ranges: 0x20–0x27 and 0x38–0x3F
  const uint8_t ranges[][2] = {{0x20,0x27},{0x38,0x3F}};
  for (auto &r : ranges) {
    for (uint8_t a = r[0]; a <= r[1]; a++) {
      Wire.beginTransmission(a);
      if (Wire.endTransmission() == 0) return a;
    }
  }
  // Fallback: scan full 7-bit space
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) return a;
  }
  return 0; // not found
}

unsigned long lastTick = 0, count = 0;

//Math constants:

  const bool strainData = false; // change this true to start collecting strain and step data.

//Baud-Rate
  const float baudrate = 115200;
  const float verBuf = 6.0;


//Defining the dimensions of the stretchxer:
  //Defining Math Constants:
    const float r0        = 7.2;
    const float rp        = 4.75;
    const float Y0        = -6.1; //Radial distance from the center to the pin (has to be negative)
    const float E0        = r0 -rp;
    const float g         = 15;   //gear ratio
    const float rPin      = 1.5; //pin offset
    const float maxEx     = 4.7;
    float targetEx  = 0.123456; 
    float theta = 0.0; 

//Defining Step and Direction Pins (Signals)
  const int stepPin = 13;
  const int dirPin  = 12;

//Defining the Microsteps of the Stepper Motor
  const int pulsesPerRev = 1600; // based on your microstepping setting
  unsigned int stepDelayUs = 2000;
  float speedBlade = 2.0;
  
  //variable logging stepper motor position:
  long pos = 0;

  AccelStepper stepper(AccelStepper::DRIVER, stepPin, dirPin);

//Defining Serial Command Variables:
  // buffer for incoming serial commands
  char commandBuffer[MAX_CMD_LEN];
  uint8_t cmdIndex = 0;
  bool    cmdReady = false;
  void sendCommand(const char* cmd) {
  Serial.print(cmd);
  Serial.print('\n');
}


void setup() {

  delay(1000); // Give USB time to settle
  USB.begin();
  Serial.begin(115200);
  while (!Serial);
    
    //LOGO:
    Serial.println(" ___      _       ____  _            _       _               ");
    Serial.println("|_ _|_ __(_)___  / ___|| |_ _ __ ___| |_ ___| |__   ___ _ __ ");
    Serial.println(" | || '__| / __| \\___ \\| __| '__/ _ \\ __/ __| '_ \\ / _ \\ '__|");
    Serial.println(" | || |  | \\__ \\  ___) | |_| | |  __/ || (__| | | |  __/ |   ");
    Serial.println("|___|_|  |_|___/ |____/ \\__|_|  \\___|\\__\\___|_| |_|\\___|_|   ");
    Serial.println("_____________________________________________________________");

    // Print the banner
    Serial.println("+===============+");
    Serial.print("|KiselyLab V");
    Serial.print(verBuf);
    Serial.println("|");
    Serial.println("+===============+");

    // Print the commands
    Serial.println("Commands:");
    Serial.println("________");
    Serial.println(" Xgoto <value>        – move to Target Expansion");
    Serial.println(" Xzero                – drive motor to zero Position");
    Serial.println(" XsetZero             – reset position counter to 0");
    Serial.println(" Xcalibrate           – run calibration routine");
    Serial.println(" Xspeed <value> cm/s  – changes the speed of the expansion in approx cm/s");
    Serial.println(" Xhelp                – this message");
         
    //Strain Gauge test:
          if (strainData) {
      Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
      Serial.println("Initializing NAU7802…");

      // 1) start the NAU7802 (default Wire bus)
      if (!nau.begin()) {
        Serial.println("Couldn't find NAU7802 – check wiring!");
        while (1) delay(10);
      }

      // 2) now set the PGA gain you want
      nau.setGain(currentGain);

      // set LDO to 3 V and sample rate to 10 SPS
      nau.setLDO(NAU7802_3V0);
      nau.setRate(NAU7802_RATE_320SPS);

      // flush startup readings
      for (uint8_t i = 0; i < 10; i++) {
        while (!nau.available());
        nau.read();
      }

      // internal & offset calibration
      while (!nau.calibrate(NAU7802_CALMOD_INTERNAL)) {
        Serial.println("Calibrating internal… retry");
        delay(500);
      }
      while (!nau.calibrate(NAU7802_CALMOD_OFFSET)) {
        Serial.println("Calibrating offset… retry");
        delay(500);
      }
      Serial.println("NAU7802 ready!");
    }
  Serial.println("Ready for commands. Prefix each with 'X':");
  pinMode(13, OUTPUT);  // Replace 13 with your LED pin if different
  
  //Intialising the Step and Direction Pins
  
    pinMode(STEP_PIN, OUTPUT);
    pinMode(DIR_PIN, OUTPUT);


    //SETTING MICROSTEPPING:
      pinMode(MS1, OUTPUT);
      pinMode(MS2, OUTPUT);
      digitalWrite(MS1, HIGH);
      digitalWrite(MS2, LOW);

    //Liquid Crystal Display Set-Up:
      #if defined(ARDUINO_ARCH_ESP32)
        Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
      #else
        Wire.begin();
      #endif

    uint8_t addr = findLcdAddress();
    if (addr == 0) {
      Serial.println("No I2C devices found. Check wiring, power, contrast, and pull-ups.");
      while (1) { delay(1000); }
    }

    Serial.print("Using LCD at I2C addr 0x");
    if (addr < 16) Serial.print('0');
    Serial.println(addr, HEX);

    lcd = new LiquidCrystal_I2C(addr, 16, 2);
    lcd->init();
    lcd->backlight();

    lcd->clear();
    lcd->setCursor(0, 0);
    lcd->print("Iris Stretcher");
    lcd->setCursor(0, 1);
    lcd->print("Kisely Lab");

    // --- Rotary encoder pins ---
    // If your A4/A5 pins support internal pullups (e.g., ESP32 GPIO32/33), use:
    pinMode(ENC_A_PIN, INPUT_PULLUP);
    pinMode(ENC_B_PIN, INPUT_PULLUP);

    // If A4/A5 are input-only w/o pullups (e.g., GPIO34/35), use 10k pullups to 3V3
    // and switch to: pinMode(ENC_A_PIN, INPUT); pinMode(ENC_B_PIN, INPUT);

    attachInterrupt(digitalPinToInterrupt(ENC_A_PIN), encISR, CHANGE);
    attachInterrupt(digitalPinToInterrupt(ENC_B_PIN), encISR, CHANGE);

    // --- Button on A2 ---
    // If your A2 lacks internal pulldown: add 10k pulldown to GND and use INPUT.
    pinMode(BUTTON_PIN, INPUT);

    // Optional: show the starting dial value
    lcdShowDialExpansion(dialEx);

}
  //LCD display Expansion:
    void lcdShowExpansionThenReset(float ex, unsigned long showMs = 2000) {
      if (!lcd) return;                         // safety if LCD not inited
      // Show expansion
      lcd->clear();
      lcd->setCursor(0, 0); lcd->print("Expansion");
      lcd->setCursor(0, 1);
      char buf[17];
      // format to 3 decimals; adjust units/label to taste
      snprintf(buf, sizeof(buf), "%7.3f", ex);
      lcd->print(buf);
      lcd->print(" x");                         // or " mm" if it’s length

      delay(showMs);                            // keep it visible briefly

      // Reset counter display
      count = 0;
      lastTick = millis();
      lcd->clear();
      lcd->setCursor(0, 0); lcd->print("Counter running");
      lcd->setCursor(0, 1); lcd->print("Count: 000000");
    }
    
      // Write the standard counter line (row 2)
    void lcdShowCounterLine() {
      if (!lcd) return;
      lcd->setCursor(0, 1);
      lcd->print("Count: 000000   ");   // pad spaces to clear leftovers
    }

    // Update only the numeric part of Count: (from column 7), fixed width
    void lcdUpdateCountNumber(unsigned long n) {
      if (!lcd) return;
      lcd->setCursor(7, 1);              // after "Count: "
      char buf[7];                       // 6 digits + NUL
      snprintf(buf, sizeof(buf), "%06lu", n);
      lcd->print(buf);
    }

    void lcdShowButtonPressed() {
      if (!lcd) return;
      lcd->clear();
      lcd->setCursor(0, 0); lcd->print("Button pressed");
      lcd->setCursor(0, 1); lcd->print(" "); // clear 2nd line
    }

    //Enocder:
    void IRAM_ATTR encISR() {
      // Index = old(BA) in low 2 bits, new(BA) in high 2 bits
      uint8_t s = encState & 0x03;
      s |= (digitalRead(ENC_A_PIN) ? 0x04 : 0);
      s |= (digitalRead(ENC_B_PIN) ? 0x08 : 0);

      // Gray-code transition table
      static const int8_t delta[16] = {
        0, -1, +1,  0,
      +1,  0,  0, -1,
      -1,  0,  0, +1,
        0, +1, -1,  0
      };
      encTicks += delta[s];
      encState = (s >> 2);  // new(BA) becomes old(BA)
    }

    void lcdSayExpansionSet(float ex) {
    if (!lcd) return;

    lcd->clear();
    lcd->setCursor(0, 0);
    lcd->print("Expansion set to:");   // exactly 16 chars, fits 16x2 line

    // Format the number: integers show like "10", otherwise "10.123"
    lcd->setCursor(0, 1);
    char buf[17];
    long exInt = lroundf(ex);
    if (fabsf(ex - exInt) < 0.0005f) {
      snprintf(buf, sizeof(buf), "%ld", exInt);
    } else {
      snprintf(buf, sizeof(buf), "%.3f", ex);
    }
    lcd->print(buf);
    lcd->print("x");
  }



//MATH FUNCTIONS:
  //Finds the degree of expansion of the cell by inputing the theta
  float computeEx(float r0, float rp, float y0, float Theta, float E0, bool showOnLCD = false) {    // slope μ
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

    // choose the “–√” root
    float x = (-b - sqrt_disc) / (2.0f * A);

    // final Eₓ
    float underRoot = A * x * x + 2.0f * mu * y0 * x + y0 * y0;
    Serial.print("Computed expansion: ");
    Serial.println( sqrt(underRoot) / E0);
    float FinalExpansion = (sqrt(underRoot) - rPin) / (E0 - rPin);
    if (showOnLCD) {
      lcdSayExpansionSet(FinalExpansion);   // <- no restore, just set and leave
    }
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




//PARSE THROUGH COMMANDS:
  void parseCommand() {
    // Must start with 'X'
    if (commandBuffer[0] != 'X') {
      Serial.println("Invalid prefix. Commands must start with 'X'.");
      return;
    }

    // Tokenize after the 'X'
    char *p = commandBuffer + 1;
    char *cmd = strtok(p, " ");
    if (!cmd) return;

    if (strcmp(cmd, "goto") == 0) {
      char *arg = strtok(NULL, " ");
      if (!arg) {
        Serial.println("Usage: Xgoto <targetEx>");
        return;
      }
              double targetEx = atof(arg);
        double thetaLow  = 0.0001;
        double thetaHigh = 0.6; 

        double angle = findThetaHighPrec(
          targetEx, r0, rp, Y0, E0,
          thetaLow, thetaHigh
        );

        if (targetEx <= 1.001 ) {
          Serial.println("Error: no valid θ found for that targetEx");
        } else if (targetEx >= maxEx ) {
          Serial.println("Error: no valid θ found for that targetEx");
        }else {
          Serial.print("Computed θ (rad): ");
          Serial.println(angle, 10);

          double actualEx = computeEx(r0, rp, Y0, angle, E0, true);  // prints on LCD
          Serial.print("Resulting expansion: ");
          Serial.println(actualEx, 6);

          // **only move if angle is valid**
          rotateThetaRadians(angle);
        }
      } else if (strcmp(cmd, "zero") == 0) {
        goToZeroPosition();

    } else if (strcmp(cmd, "setZero") == 0) {
        zeroAndLogStepperPosition();

    } else if (strcmp(cmd, "help") == 0) {
      // ===== YOUR Xhelp CODE START =====
      Serial.println("Commands:");
      Serial.println("________");
      Serial.println(" Xgoto <value>        – move to Target Expansion");
      Serial.println(" Xzero                – drive motor to zero Position");
      Serial.println(" XsetZero             – reset position counter to 0");
      Serial.println(" Xcalibrate           – run calibration routine");
      Serial.println(" Xspeed <value> cm/s  – changes the speed of the expansion in approx cm/s");
      Serial.println(" Xhelp                – this message");
      // ===== YOUR Xhelp CODE END =====

    } else if (strcmp(cmd, "calibrate") == 0) {
      stepperMotorCalibration();

} else if (strcmp(cmd, "speed") == 0) {
    char *arg = strtok(NULL, " ");
    if (!arg) {
        Serial.println("Usage: Xspeed <bladeSpeed_cm/s>");
      } else  {
          // parse fractional speeds correctly
          double speedBlade = atof(arg);
          if (speedBlade <= 0.0) {
              Serial.println("Error: speed must be > 0");
          } else {
              Serial.print("Blade speed set to: ");
              Serial.print(speedBlade, 4);
              Serial.println(" cm/s");
              // this will compute and apply the correct stepDelayUs
              setAngularSpeed(speedBlade);
              // optionally confirm delay
              Serial.print("Step pulse delay now: ");
              Serial.print(stepDelayUs);
              Serial.println(" µs");
          }
      }
      } else {
      Serial.print("Unknown command: ");
      Serial.println(cmd);
    }
  }




//STEPPER MOTOR FUNCTION:
  //Rotates the stepper motor based on the angle theta provided:
    void rotateThetaRadians(float theta) {
      // Compute how many steps correspond to the desired absolute angle
      float stepsPerRad   = (pulsesPerRev * g) / (2.0 * M_PI);
      long  targetSteps   = lround(theta * stepsPerRad);

      // Read current step count
      long  currentSteps  = stepper.currentPosition();

      // Compute how many steps to move (can be negative)
      long  deltaSteps    = targetSteps - currentSteps;
      bool  dir           = (deltaSteps >= 0);

      // Set direction pin
      digitalWrite(DIR_PIN, dir ? HIGH : LOW);

      // Perform the move, updating the internal counter each pulse
      long stepsToMove = abs(deltaSteps);
      for (long i = 0; i < stepsToMove; ++i) {
        digitalWrite(STEP_PIN, HIGH);
        delayMicroseconds(stepDelayUs);
        digitalWrite(STEP_PIN, LOW);
        delayMicroseconds(stepDelayUs);

        if (strainData) {
          Serial.print("Steps, ");
          Serial.print(i);
          Serial.print(",");
          float v = readADCVoltageAvg(35);
          Serial.print("ADC voltage,");
          Serial.println(v, 6);  // 6 decimals
        } else{
          Serial.print("Steps, ");
          Serial.println(i);
        }



        // Mirror this pulse into the AccelStepper counter:
        // if dir==true we increment, else decrement
        if (dir) {
          stepper.setCurrentPosition(currentSteps + (i + 1));
        } else {
          stepper.setCurrentPosition(currentSteps - (i + 1));
        }
      }

      // Report what happened
      Serial.print("Moved ");
      Serial.print(deltaSteps);
      Serial.print(" steps, new position = ");
      Serial.println(stepper.currentPosition());
    }

    long stepperMotorPosition() {
    // If any AccelStepper move is active, let it tick once
    stepper.run();
    long pos = stepper.currentPosition();
    Serial.print("Current position (steps): ");
    Serial.println(pos);
    return pos;
  }

  // Physically move the motor back to the zero-angle (θ = 0) and reset its counter
  void goToZeroPosition() {
    long startPos = stepperMotorPosition();
    Serial.print("Moving back to zero from ");
    Serial.print(startPos);
    Serial.println(" steps…");

    rotateThetaRadians(0.0);

    Serial.println("Motor is now at zero position (θ = 0).");

    // <<< NEW: keep LCD showing this, no restore >>>
    lcdSayExpansionSet(1.0f);     // or compute and show the actual Ex at θ=0 if you prefer
  }

  // Set the current motor position as zero without any movement
  void zeroAndLogStepperPosition() {
    long current = stepperMotorPosition();
    stepper.setCurrentPosition(0);
    Serial.print("Internal counter reset to zero. Previous position was: ");
    Serial.println(current);
  }

  //Stepper Motor Calibration Function:
  void stepperMotorCalibration(){

      Serial.println("Starting calibration...");
      stepperMotorRotateSteps(0.7);
      zeroAndLogStepperPosition();

      Serial.println("Moving back in by -0.276 rad...");
      stepperMotorRotateSteps(-0.293);
      zeroAndLogStepperPosition();
      
      // 4) Reset this as the new zero
      Serial.println("Setting Zero");
      zeroAndLogStepperPosition();

      Serial.println("Calibration complete.");
  }

  //Rotates the motor by a specfic angle:
  void stepperMotorRotateSteps(float angle){

        float stepsPerRad   = (pulsesPerRev * g) / (2.0 * M_PI);
        long  targetSteps   = lround(angle * stepsPerRad);

        // Read current step count
        long  currentSteps  = stepper.currentPosition();

        // Compute how many steps to move (can be negative)
        long  deltaSteps    = targetSteps - currentSteps;
        bool  dir           = (deltaSteps >= 0);

        // Set direction pin
        digitalWrite(DIR_PIN, dir ? HIGH : LOW);

        // Perform the move, updating the internal counter each pulse
        long stepsToMove = abs(deltaSteps);
        for (long i = 0; i < stepsToMove; ++i) {
          digitalWrite(STEP_PIN, HIGH);
          delayMicroseconds(stepDelayUs);
          digitalWrite(STEP_PIN, LOW);
          delayMicroseconds(stepDelayUs);
          

          // Mirror this pulse into the AccelStepper counter:
          // if dir==true we increment, else decrement
          if (dir) {
            stepper.setCurrentPosition(currentSteps + (i + 1));
          } else {
            stepper.setCurrentPosition(currentSteps - (i + 1));
          }
        }
  }
  // Returns the needed step-pulse half-period (µs) for a desired angular speed ω (rad/s):
    unsigned int microsecondsForOmega(double bladeSpeed) {
      // convert linear blade speed into angular speed (rad/s)
      double omega = bladeSpeed / 13.6;
      if (omega <= 0.0) {
        return 0;  // no movement or invalid speed
      }
      // half‐period delay (µs) = (π * 1e6) / (ω * stepsPerRev * gearRatio)
      double delayUs = (M_PI*(1e6)) / (omega * pulsesPerRev * g);
      return (unsigned int)lround(delayUs);
    }

    // Sets the global stepDelayUs so the motor spins at the requested blade speed
    void setAngularSpeed(double bladeSpeed) {
      unsigned int newDelay = microsecondsForOmega(bladeSpeed);
      stepDelayUs = newDelay;
      Serial.print("Step pulse half‐period delay set to ");
      Serial.print(stepDelayUs);
      Serial.println(" µs");
    }

  // read N samples back-to-back, return the averaged voltage
  float readADCVoltageAvg(int N) {
    long sum = 0;
    for (int i = 0; i < N; i++) {
      while (!nau.available()) ;  // at 10 SPS this blocks ~100 ms
      sum += nau.read();
    }
    float avgCounts = float(sum) / N;
    return avgCounts * (NAU7802_REF_VOLTAGE / float(1UL << 23));
  }

//LOOP:
void loop() {

  //Continusly Reads through for commands:
    while (Serial.available() && !cmdReady) {
      char c = Serial.read();
      if (c == '\n' || c == '\r') {
        if (cmdIndex > 0) {
          commandBuffer[cmdIndex] = '\0';
          cmdReady = true;
        }
      } else if (cmdIndex < MAX_CMD_LEN - 1) {
        commandBuffer[cmdIndex++] = c;
      }
    }

    // ---- Button handling: PRESS => go to dialEx ----
    int reading = digitalRead(BUTTON_PIN);
    static int btnLastReading = LOW;
    static int btnStable      = LOW;
    static unsigned long btnLastChangeMs = 0;

    if (reading != btnLastReading) {
      btnLastChangeMs = millis();
      btnLastReading  = reading;
    }
    if ((millis() - btnLastChangeMs) > BUTTON_DEBOUNCE_MS) {
      if (reading != btnStable) {
        btnStable = reading;
        if (btnStable == HIGH) {
          // Compute theta for current dialEx and move
          double thetaLow  = 0.0001;
          double thetaHigh = 0.6;

          double angle = findThetaHighPrec(
            (double)dialEx, r0, rp, Y0, E0, thetaLow, thetaHigh
          );

          if (isnan(angle) || dialEx <= 1.001f || dialEx >= maxEx) {
            Serial.println("Error: no valid θ found for that dialEx");
          } else {
            Serial.print("Goto (button): Ex="); Serial.println(dialEx, 6);
            Serial.print("Computed θ (rad): ");  Serial.println(angle, 10);

            double predicted = computeEx(r0, rp, Y0, angle, E0, false);
            Serial.print("Predicted expansion: "); Serial.println(predicted, 6);

            rotateThetaRadians(angle);   // do the move
            lcdSayExpansionSet(dialEx);  // confirm on LCD
          }
        }
      }
    }

    // If a full command is ready, parse it
    if (cmdReady) {
      parseCommand();
      cmdIndex = 0;
      cmdReady = false;
    }

        // ---- Rotary encoder: update dialEx from ticks ----
    static unsigned long lastEncMs = 0;
    static long ticksConsumed = 0;

    if (millis() - lastEncMs >= 30) {  // ~33 Hz refresh
      lastEncMs = millis();

      long ticksNow;
      noInterrupts();
      ticksNow = encTicks;
      interrupts();

      long dt = ticksNow - ticksConsumed;
      if (dt != 0) {
        // convert ticks to detents
        float detents = (float)dt / (float)TICKS_PER_DETENT;
        dialEx += detents * STEP_EX_PER_DETENT;

        // Constrain to your valid range
        if (dialEx < 1.001f) dialEx = 1.001f;
        if (dialEx >  maxEx) dialEx = maxEx;

        ticksConsumed = ticksNow;

        // Show live dial value
        lcdShowDialExpansion(dialEx);
        Serial.print("Dial Ex: "); Serial.println(dialEx, 4);
      }
}

}


//Tejasvin Shrikanth

