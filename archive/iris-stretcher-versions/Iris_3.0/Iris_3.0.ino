#include "USB.h"
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// I²C LCD address and dimensions (change if needed)
LiquidCrystal_I2C lcd(0x27, 16, 2);

// Reference voltage for ADC conversion (change if your board uses 3.3V)
const float VREF = 5.0;

void setup() {
  // Give USB time to settle
  delay(1000);
  USB.begin();

  // Start serial for debugging
  Serial.begin(115200);
  while (!Serial);
  Serial.println("Ready.");

  // LED pin setup
  pinMode(13, OUTPUT);  // onboard LED on many boards

  // Initialize the LCD
  lcd.init();
  lcd.backlight();

  // Display a welcome message
  lcd.setCursor(0, 0);
  lcd.print("System Ready");
  lcd.setCursor(0, 1);
  lcd.print("Hello, I2C LCD");
  delay(2000);
  lcd.clear();
}

void loop() {
  static unsigned long counter = 0;

  // --- Blink the onboard LED ---
  digitalWrite(13, HIGH);
  delay(10);
  digitalWrite(13, LOW);
  delay(10);

  // --- Read analog voltage at A1 ---
  int raw = analogRead(A1);
  float voltage = raw * VREF / 1023.0;

  // --- Serial output ---
  Serial.print("Loop count: ");
  Serial.print(counter);
  Serial.print(" | A1 raw: ");
  Serial.print(raw);
  Serial.print(" | V: ");
  Serial.println(voltage, 3);  // three decimal places

  // --- Update LCD ---
  // Line 1: loop counter and uptime
  lcd.setCursor(0, 0);
  lcd.print("Cnt:");
  lcd.print(counter);
  lcd.print(" T:");
  lcd.print(millis() / 1000);     // uptime in seconds
  lcd.print("s");

  // Line 2: voltage reading
  lcd.setCursor(0, 1);
  lcd.print("A1 V=");
  lcd.print(voltage, 2);           // two decimal places
  lcd.print("   ");                // clear any leftover chars

  counter++;
  delay(480);  // adjust so total loop ~500 ms
}