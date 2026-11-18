const int analogPin = 34;           // ADC1_6 — safe analog input
const float referenceVoltage = 3.3; // ADC range is 0 to 3.3V
const int adcResolution = 4095;     // 12-bit ADC (0–4095)

void setup() {
  Serial.begin(115200);
}

void loop() {
  int raw = analogRead(analogPin);                    // Read raw ADC value
  float voltage = (raw / float(adcResolution)) * referenceVoltage; // Convert to volts

  Serial.print("Raw ADC: ");
  Serial.print(raw);
  Serial.print("  Voltage: ");
  Serial.print(voltage, 3); // 3 decimal places
  Serial.println(" V");


}