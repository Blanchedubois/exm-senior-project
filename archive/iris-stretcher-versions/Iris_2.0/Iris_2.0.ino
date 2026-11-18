#include "USB.h"
#include <math.h>
#include <AccelStepper.h>

#define MAX_CMD_LEN  32
#define STEP_PIN 13
#define DIR_PIN 12

//Baud-Rate
  const float baudrate = 115200;
  const float verBuf = 2.1;


//Defining the dimensions of the stretcher:
  //Defining Math Constants:
    const float r0        = 7.1;
    const float rp        = 5.25;
    const float Y0        = -6.1; //Radial distance from the center to the pin (has to be negative)
    const float E0        = r0 -rp;
    const float g         = 15;   //gear ratio
    const float rPin      = 0.5; //pin offset
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

  Serial.println("Ready for commands. Prefix each with 'X':");
  pinMode(13, OUTPUT);  // Replace 13 with your LED pin if different
  
  //Intialising the Step and Direction Pins
    pinMode(STEP_PIN, OUTPUT);
    pinMode(DIR_PIN, OUTPUT);

}


//MATH FUNCTIONS:
  //Finds the degree of expansion of the cell by inputting the theta
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

    // choose the “–√” root
    float x = (-b - sqrt_disc) / (2.0f * A);

    // final Eₓ
    float underRoot = A * x * x + 2.0f * mu * y0 * x + y0 * y0;
    Serial.print("Computed expansion: ");
    Serial.println( sqrt(underRoot) / E0);
    return sqrt(underRoot) / E0;

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
        double thetaHigh = M_PI; 

        double angle = findThetaHighPrec(
          targetEx, r0, rp, Y0, E0,
          thetaLow, thetaHigh
        );

        if (targetEx <= 1.001 ) {
          Serial.println("Error: no valid θ found for that targetEx");
        } else if (targetEx >= 2.6 ) {
          Serial.println("Error: no valid θ found for that targetEx");
        }else {
          Serial.print("Computed θ (rad): ");
          Serial.println(angle, 10);

          double actualEx = computeEx(r0, rp, Y0, angle, E0);
          Serial.print("Resulting expansion: ");
          Serial.println(actualEx, 10);

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

    // rotateThetaRadians(0) computes delta = 0 - currentPosition and steps back
    rotateThetaRadians(0.0);

    Serial.println("Motor is now at zero position (θ = 0).");
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
      stepperMotorRotateSteps(-0.276);
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
      double delayUs = (1e6) / (omega * pulsesPerRev * g);
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

    // If a full command is ready, parse it
    if (cmdReady) {
      parseCommand();
      cmdIndex = 0;
      cmdReady = false;
    }
}
//Tejasvin Shrikanth

