# 9-Channel Strain Gauge System

Arduino code for reading 9 strain gauges using NAU7802 ADCs multiplexed through two TCA9548A I2C multiplexers.

## Hardware Requirements

- Arduino board (Uno, Mega, Nano, etc.)
- 2x TCA9548A I2C Multiplexers
- 9x NAU7802 24-bit ADC boards
- 9x Strain gauges in Wheatstone bridge configuration
- Pull-up resistors for I2C (4.7kΩ recommended if not built-in)

## Hardware Configuration

### TCA9548A Multiplexer Addressing

The TCA9548A uses address pins (A0, A1, A2) to set its I2C address:

| A2 | A1 | A0 | Address |
|----|----|----|---------|
| 0  | 0  | 0  | 0x70    |
| 0  | 0  | 1  | 0x71    |
| 0  | 1  | 0  | 0x72    |
| 0  | 1  | 1  | 0x73    |
| 1  | 0  | 0  | 0x74    |
| 1  | 0  | 1  | 0x75    |
| 1  | 1  | 0  | 0x76    |
| 1  | 1  | 1  | 0x77    |

**Default Configuration:**
- Multiplexer 1: 0x70 (all address pins LOW)
- Multiplexer 2: 0x71 (A0 HIGH, A1 and A2 LOW)

### Wiring Diagram

```
Arduino                  TCA9548A (Mux 1 - 0x70)
  SDA  ←──────────────→  SDA
  SCL  ←──────────────→  SCL
  5V   ───────────────→  VIN
  GND  ───────────────→  GND

                         SD0 ←→ NAU7802 #1 (SDA/SCL)
                         SD1 ←→ NAU7802 #2 (SDA/SCL)
                         SD2 ←→ NAU7802 #3 (SDA/SCL)
                         SD3 ←→ NAU7802 #4 (SDA/SCL)

Arduino                  TCA9548A (Mux 2 - 0x71)
  SDA  ←──────────────→  SDA
  SCL  ←──────────────→  SCL
  5V   ───────────────→  VIN
  GND  ───────────────→  GND

                         SD0 ←→ NAU7802 #5 (SDA/SCL)
                         SD1 ←→ NAU7802 #6 (SDA/SCL)
                         SD2 ←→ NAU7802 #7 (SDA/SCL)
                         SD3 ←→ NAU7802 #8 (SDA/SCL)
                         SD4 ←→ NAU7802 #9 (SDA/SCL)
```

## Software Requirements

### Arduino Libraries

Install the following library via Arduino Library Manager:

1. **SparkFun Qwiic Scale NAU7802 Arduino Library**
   - Open Arduino IDE
   - Go to: Sketch → Include Library → Manage Libraries
   - Search: "SparkFun NAU7802"
   - Install: "SparkFun Qwiic Scale NAU7802 Arduino Library" by SparkFun Electronics

## Configuration

### Multiplexer Addresses

In `NineChannel_StrainGauge.ino`, modify these lines if you've changed the multiplexer addresses:

```cpp
#define MUX1_ADDRESS 0x70  // First multiplexer (4 ADCs)
#define MUX2_ADDRESS 0x71  // Second multiplexer (5 ADCs)
```

### NAU7802 Settings

Adjust gain and sample rate as needed:

```cpp
#define NAU7802_GAIN 128  // Options: 1, 2, 4, 8, 16, 32, 64, 128
#define NAU7802_SPS 80    // Options: 10, 20, 40, 80, 320
```

**Gain Selection Guide:**
- Higher gain = better resolution for small signals
- Lower gain = larger input range
- For strain gauges: 64-128 recommended

**Sample Rate:**
- 10 SPS: Lowest noise, slowest response
- 320 SPS: Fastest response, more noise
- 80 SPS: Good balance (recommended)

### Voltage Reference

In the `convertToVoltage()` function, adjust AVDD based on your power supply:

```cpp
float AVDD = 3.3;  // Change to 5.0 if using 5V reference
```

## Usage

1. **Upload the code** to your Arduino
2. **Open Serial Monitor** (Tools → Serial Monitor)
3. **Set baud rate** to 115200
4. The system will automatically:
   - Scan for both multiplexers
   - Detect all connected NAU7802 ADCs
   - Initialize and calibrate each ADC
   - Begin continuous measurements

### Serial Output Format

```
Time(ms)    SG1(V)      SG2(V)      SG3(V)      ...     SG9(V)
1000        0.000125    0.000098    0.000156    ...     0.000201
1100        0.000127    0.000099    0.000158    ...     0.000203
```

## Calibration for Strain Gauges

### Wheatstone Bridge Configuration

Each NAU7802 measures the differential voltage from a Wheatstone bridge:

```
         +AVDD
           |
          [R1]────────┐
           |          |
      Vout(+)         |
           |          |
    [Strain Gauge]   [R3]
           |          |
      Vout(-)         |
           |          |
          [R2]────────┘
           |
          GND
```

### Converting Voltage to Strain

The relationship between voltage and strain (ε) is:

```
ε = (4 * ΔV/V_excitation) / (GF * V_bridge_balance)
```

Where:
- ΔV = Measured differential voltage
- V_excitation = Bridge excitation voltage (AVDD)
- GF = Gauge factor (typically 2.0-2.1 for metal foil gauges)
- V_bridge_balance = Bridge balance factor (usually 1 for quarter bridge)

### Calibration Procedure

1. **Zero Load Calibration:**
   - Remove all load from the strain gauges
   - Record baseline voltage readings
   - Subtract these from all future measurements

2. **Known Load Calibration:**
   - Apply known loads
   - Record voltage vs. load
   - Calculate calibration factor (V/kg or V/N)

3. **Update Code:**
   - Add calibration factors to the code
   - Convert raw voltage to engineering units

## Troubleshooting

### No Multiplexers Detected
- Check I2C wiring (SDA, SCL)
- Verify power supply (3.3V or 5V)
- Check I2C pull-up resistors (4.7kΩ to VCC)
- Verify multiplexer addresses are correct

### ADCs Not Found
- Check connections between multiplexers and NAU7802s
- Ensure each NAU7802 has power
- All NAU7802s use address 0x2A (cannot be changed)

### Noisy Readings
- Reduce sample rate (lower SPS)
- Increase gain for better resolution
- Check for proper grounding
- Add capacitors near ADC power pins (0.1µF)
- Keep wiring short and away from noise sources

### Unstable Readings
- Ensure proper Wheatstone bridge balance
- Check strain gauge connections
- Verify excitation voltage is stable
- Allow ADCs to warm up (1-2 minutes)

## Advanced Configuration

### Custom Channel Labels

Modify the `setupADCChannels()` function to customize strain gauge names:

```cpp
adcChannels[index].label = "Bicep_Left";  // Instead of "SG1"
```

### Reading Rate

Adjust in the `loop()` function:

```cpp
unsigned long interval = 100; // 100ms = 10Hz
```

### Data Logging

To log data to SD card or send to computer, modify the `loop()` function to format output as CSV or JSON.

## License

Open source - modify as needed for your application.

## Support

For issues with:
- **SparkFun NAU7802 Library**: https://github.com/sparkfun/SparkFun_Qwiic_Scale_NAU7802_Arduino_Library
- **TCA9548A**: Check Adafruit or SparkFun documentation
