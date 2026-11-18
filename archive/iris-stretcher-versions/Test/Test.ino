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
  Serial.println("Loop...");
  digitalWrite(13, HIGH);
  delay(10);
  digitalWrite(13, LOW);
  delay(10);
}