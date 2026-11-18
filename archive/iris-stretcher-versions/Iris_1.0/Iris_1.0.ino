//Stretcher Command with Command Line inverface
float Version = 0.1;

#include <AccelStepper.h>

//#define debug // uncomment to display debug data
#define displayPosition // uncomment to display position as the stretcher moves

//Defining the dimensions of the stretcher:
  //Defining Math Constants:
    const float r0        = 7.1;
    const float rp        = 5.4;
    const float Y0        = -6.2; //Radial distance from the center to the pin (has to be negative)
    const float E0        = r0 -rp;
    const float g         = 12.701;
    float targetEx  = 0.123456; 
    float theta = 0.0; 


//#define showParsedData

const int stepPin = 13;
const int dirPin  = 12;
const int irqPin = 27;    // interrupt capable
const int zeroPinA = 25;  // safe input

const int pulsesPerRev = 1600;
const float microsteps = 800; // number of microsteps set on motor driver/rotation
//const float screwPitch = 2; // mm/rotation
const float gear_ratio = 12.701; // change this to the correct gear ratio. 
const float baudrate = 115200;

double currentPosition = 0;// absolute position of the tracker

volatile bool irq_state = 0;

#define debug

int MOVE = -6000;
unsigned int SPD = 600;  
unsigned int ACCEL = 1600;


const byte numChars = 32;
char receivedChars[numChars];
char tempChars[numChars];        // temporary array for use when parsing

      // variables to hold the parsed data
char CommandfromPC[numChars] = {0};
float unit = 0;
//float floatFromPC = 0.0;


boolean newData = false;

void recvWithStartEndMarkers();
void parseData(); 
void stepperOne(float cmd);

AccelStepper stepper(AccelStepper::DRIVER, stepPin, dirPin);
#include "USB.h"

void setup() {
  delay(1000); // Give USB time to settle
  USB.begin();
  Serial.begin(115200);
  while (!Serial);
  Serial.println("Ready.");
  pinMode(13, OUTPUT);  // Replace 13 with your LED pin if different
}

void loop() {
  irq_state = 0;
  recvWithStartEndMarkers();
  if (newData == true) {
        strcpy(tempChars, receivedChars);
            // this temporary copy is necessary to protect the original data
            //   because strtok() used in parseData() replaces the " " with \0
        parseData();
          #ifdef showParsedData
            showParsedData();
          #endif
        newData = false;
    }

  if (strcmp(CommandfromPC, "zero") == 0){ // eventually will find the zero position
    CommandfromPC[0] = 0;
  }

  else if (strcmp(CommandfromPC, "setZero") == 0){ // sets the zero to current position
    stepper.setCurrentPosition(0);
    Serial.print("Current position is 0.00 mm");
    CommandfromPC[0] = 0;
  }

  else if (strcmp(CommandfromPC, "goto") == 0){ 
    Serial.print("goto: ");
    Serial.println(unit);
    double thetaLow  = 0.0;          // lower bound in radians
    double thetaHigh = PI / 2.0;     // upper bound
    double angle =  findThetaHighPrec(targetEx, r0,  rp,  Y0,  E0, thetaLow, thetaHigh );
    long steps = rotateThetaRadians(angle);
    Serial.println(steps);  
    stepperOne(steps);
  }

  else if (strcmp(CommandfromPC, "move") == 0){
    double temp_pos = unit + convert_steps_to_radius(stepper.currentPosition());
    //double temp_pos = unit + stepper.currentPosition(); //if you want to direcly input steps, comment above line and uncomment this line;
    Serial.print("move: ");
    //Serial.println(unit);
    stepperOne(temp_pos);
    Serial.print("Position: ");
    Serial.println(convert_steps_to_radius(stepper.currentPosition()));
    CommandfromPC[0] = 0;
  }

  else if (strcmp(CommandfromPC, "position") == 0){
      Serial.print(convert_steps_to_radius(stepper.currentPosition()));
      Serial.println(" mm");
      CommandfromPC[0] = 0;
  }

  else if (strcmp(CommandfromPC, "speed") == 0){
      //SPD = unit*(1/screwPitch)*microsteps; // need to write a new speed function
      Serial.print("New speed = ");
      Serial.println(SPD);

    CommandfromPC[0] = 0;
  }

  else if (strcmp(CommandfromPC, "test")==0){

    CommandfromPC[0] = 0;


  }

  else if (strcmp(CommandfromPC, "help") == 0){
    
    Serial.println("\n");
    Serial.print("Membrane Stretcher Code Version: "); Serial.println(Version);
    Serial.print("\n");
    Serial.println("List of Commands:");
    Serial.println("  goto x: Goes to specified position. Replace 'x' with position required"); 
    Serial.println("  zero: Runs the Zeroing function so that the focal plane is zero");
    Serial.println("  setZero: Sets the current position as zero, useful for fine tuning zero");
    Serial.println("  position: displays current position");
    Serial.println("  speed x: changes the speed of the motors in mm/sec");
    Serial.println("  move x: moves by specified distance.");

    Serial.println("\nIn order to execute a command, type 'X' followed by intended command");
    Serial.println("In order to see the live stepper position as it moves, uncomment '#define displayPosition'.");


    CommandfromPC[0] = 0;


  }
  
}


void recvWithStartEndMarkers() {
    static boolean recvInProgress = false;
    static byte ndx = 0;
    char startMarker = 'X';
    char endMarker = '\n';
    char rc;

    while (Serial.available() > 0 && newData == false) {
        rc = Serial.read();

        if (recvInProgress == true) {
            if (rc != endMarker) {
                receivedChars[ndx] = rc;
                ndx++;
                if (ndx >= numChars) {
                    ndx = numChars - 1;
                }
            }
            else {
                receivedChars[ndx] = '\0'; // terminate the string
                recvInProgress = false;
                ndx = 0;
                newData = true;
            }
        }

        else if (rc == startMarker) {
            recvInProgress = true;
        }
    }
}

void parseData() {
  char * strtokIndx;

  strtokIndx = strtok(tempChars," ");
  if (strtokIndx != NULL) {
    strcpy(CommandfromPC, strtokIndx);
  } else {
    CommandfromPC[0] = 0;
    return;
  }

  strtokIndx = strtok(NULL, " ");
  if (strtokIndx != NULL) {
    unit = atof(strtokIndx);
  } else {
    unit = 0;  // default or error value
  }
}

  void showParsedData() {
    Serial.print("Command ");
    Serial.println(CommandfromPC);
    Serial.print("unit ");
    Serial.println(unit);

}

void stepperOne(float cmd) {
  stepper.setMaxSpeed(SPD);
  stepper.setSpeed(SPD);
  stepper.setAcceleration(ACCEL);

  //stepper.setCurrentPosition(0); //looses zero position everytime command is run
  //long steps = -cmd/(2/microsteps);
  long steps = convert_radius_to_steps(cmd);

#ifdef debug
  Serial.print( "steps = ");
  Serial.println(steps);
#endif

  stepper.moveTo(steps);
  //stepper.moveTo(cmd);

  while (stepper.distanceToGo() != 0) {
      if(irq_state == 1){
        irq_state = 0;
        break;
      }
    stepper.setSpeed(SPD);
    stepper.runSpeedToPosition();

    #ifdef displayPosition
    //Serial.println(convert_steps_to_radius(stepper.currentPosition())); //tells how much the steppers moved by
    Serial.println(convert_steps_to_radius(stepper.currentPosition()));
    #endif
  } 
}
//MATH TO DERIVE EXPANSION TO ANGLE OF THE IRIS:
  //Finds the degree of expansion of the cell by inputing the theta
  float computeEx(float r0, float rp, float y0, float theta, float E0) {
    // slope μ
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
    return sqrt(underRoot) / E0;
  }

  // Derives the theta from the expansion chosen
    double findThetaHighPrec(double targetEx,
      double r0, double rp, double y0, double E0,
      double thetaLow,
      double thetaHigh
    ) {
      // 1) bracket check (Resolves quickly whether there is a root present)
      //guarantees to start Newton with a valid bracket (so the ESP32 does not diverge)
      double fLow  = computeEx(r0,rp,y0,thetaLow, E0) - targetEx;
      double fHigh = computeEx(r0,rp,y0,thetaHigh,E0) - targetEx;
      if (fLow * fHigh > 0) return NAN;

      // 2) do ~25 bisection iters to shrink bracket
      for (int i = 0; i < 25; i++) {
        double mid  = 0.5*(thetaLow + thetaHigh);
        double fmid = computeEx(r0,rp,y0,mid, E0) - targetEx;
        if (fLow * fmid <= 0) {
          thetaHigh = mid;
          fHigh = fmid;
        } else {
          thetaLow = mid;
          fLow = fmid;
        }
      }

      // 3) Newton–Raphson method of resolving the root
      double theta = 0.5*(thetaLow + thetaHigh);
      const double tol_f     = 1e-10;    // desired Ex-error
      const double tol_theta = 1e-10;    // desired θ-step
      const double eps       = 1e-8;     // derivative delta
      for (int iter = 0; iter < 50; iter++) {
        double f = computeEx(r0,rp,y0,theta, E0) - targetEx;
        if (fabs(f) < tol_f) break;

        // numerical solution of the derivative f'(θ)
        double f1 = computeEx(r0,rp,y0,theta+eps, E0);
        double f2 = computeEx(r0,rp,y0,theta-eps, E0);
        double fp = (f1 - f2)/(2.0*eps);

        // Newton step
        double dtheta = -f/fp;
        theta += dtheta;

        if (fabs(dtheta) < tol_theta) break;
      }
      return theta;
    }

double rotateThetaRadians(float theta) {
  // Compute steps non-blocking and print position
  double phiRad = g * theta;
  long steps = (long)((phiRad / (2.0 * M_PI)) * pulsesPerRev);
  return steps;
}

void interruptflag(){
  irq_state = 1;
  delay(10);
}

// converts intended radius change into the steps needed to move that far. 
int convert_radius_to_steps(float radius_change){
  //float angle = 8.02568*(radius_change) - 6.71107; // conver radius change to an angle;
  //int steps = (int)((angle/((360/microsteps)*gear_ratio)+0.5f));
  //int steps = (int)(8.40413*radius_change);
  int steps = radius_change * 62.5; // (31.25 * 2), matches full-step scaling
  return steps;
}

// converts steps to the radius change to display how far the device has moved. 
float convert_steps_to_radius(int steps){
  //float radius = 0.1246*(steps*(360/microsteps)*gear_ratio)+0.8362;
  float radius = steps/(8*31.25); //based on rough approximation that there are 5 steps for every millimeter
  return radius;
}
