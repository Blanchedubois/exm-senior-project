# NAU7802 9-ADC System Documentation

## Hardware Configuration

### Components
- **Microcontroller:** ESP32-S3 Feather
- **ADCs:** 9x NAU7802 24-bit ADCs (address: 0x36)
- **Multiplexers:** 2x TCA9548A I2C multiplexers
  - MUX 0x71: 4 ADCs on channels 0-3
  - MUX 0x73: 5 ADCs on channels 0-4

### I2C Configuration
- **SDA:** GPIO 3
- **SCL:** GPIO 4
- **Clock Speed:** 100 kHz (can use 10 kHz for high capacitance)
- **Pull-up Resistors:** 2.2kΩ - 4.7kΩ to 3.3V (ESP32 is 3.3V logic!)

### Wiring
```
ESP32-S3 Feather
├── GPIO 3 (SDA) ──┬── MUX 0x71 (SDA)
│                   └── MUX 0x73 (SDA)
├── GPIO 4 (SCL) ──┬── MUX 0x71 (SCL)
│                   └── MUX 0x73 (SCL)
└── GND ───────────┴── Common Ground

MUX 0x71 (Address: 0x71)
├── Channel 0 ── NAU7802 #1 (0x36)
├── Channel 1 ── NAU7802 #2 (0x36)
├── Channel 2 ── NAU7802 #3 (0x36)
└── Channel 3 ── NAU7802 #4 (0x36)

MUX 0x73 (Address: 0x73)
├── Channel 0 ── NAU7802 #5 (0x36)
├── Channel 1 ── NAU7802 #6 (0x36)
├── Channel 2 ── NAU7802 #7 (0x36)
├── Channel 3 ── NAU7802 #8 (0x36)
└── Channel 4 ── NAU7802 #9 (0x36)
```

## NAU7802 Specifications

### Key Features
- **Resolution:** 24-bit
- **Channels:** Differential (positive and negative inputs)
- **Gain:** 1x, 2x, 4x, 8x, 16x, 32x, 64x, 128x
- **Sample Rate:** 10, 20, 40, 80, 320 SPS
- **Internal LDO:** 2.4V to 4.5V (typically 3.3V for ESP32)
- **Typical Use:** Load cells, strain gauges, bridge sensors

### Input Voltage Range
- **With Gain = 1:** ±(AVDD/2) = ±1.65V for 3.3V supply
- **With Gain = 128:** ±12.9mV full scale

### Register Map (Important)
```
0x00: PU_CTRL    - Power up control
0x01: CTRL1      - Gain selection
0x02: CTRL2      - Conversion rate, LDO
0x12: ADCO_B2    - ADC output byte 2 (MSB)
0x13: ADCO_B1    - ADC output byte 1
0x14: ADCO_B0    - ADC output byte 0 (LSB)
```

## Current Status

### Issue Identified
**All ADC inputs are tied to 3.3V**, resulting in:
- Raw value: 16776960 (0xFFFF00)
- Voltage: 3.2999V

This is **correct behavior** - the ADCs are working properly but reading the rail voltage.

### For Strain Gauge Measurements
Strain gauges require:
1. **Wheatstone bridge configuration**
2. **Excitation voltage** (typically 2.5V or 5V)
3. **Differential measurement** between bridge output terminals
4. **Proper gain setting** (often 64x or 128x for small signals)

### Expected Raw Values
For a properly connected strain gauge at zero load:
- **Mid-scale:** ~8388608 (0x800000) = 0V differential
- **With load:** Values will vary above/below mid-scale
- **With gain 128x:** Very sensitive, small voltages create large readings

## Voltage Conversion Formula

```cpp
// For 24-bit NAU7802
int32_t raw = readNAU7802();  // 0 to 16777215

// Convert to voltage (signed, centered at mid-scale)
float voltage = (raw - 8388608.0) / 8388607.0 * (VREF / GAIN);

// Where:
// VREF = 3.3V (or your LDO voltage)
// GAIN = 1, 2, 4, 8, 16, 32, 64, or 128
```

## Calibration

NAU7802 requires two calibrations:
1. **Internal Offset Calibration:** Removes internal offsets
2. **System Offset Calibration:** Removes offset from your sensor/wiring

```cpp
nau.calibrate(NAU7802_CALMOD_INTERNAL);  // Internal
nau.calibrate(NAU7802_CALMOD_OFFSET);    // System offset
```

**Important:** Calibrate with **no load** on strain gauges!

## Troubleshooting

### All readings are 3.3V (0xFFFF00)
- ✓ ADCs are working correctly
- → Inputs are tied to positive rail
- → Check if sensors are connected
- → Verify excitation voltage is present

### All readings are 0V (0x000000)
- → Inputs are grounded
- → Or ADCs not initialized

### Readings timeout or error
- → Check I2C connections
- → Verify pull-up resistors
- → Reduce I2C clock speed to 10kHz
- → Check multiplexer channel switching

### Oscilloscope shows triangle waves
- → Too much capacitance on I2C lines
- → Use lower value pull-ups (2.2kΩ)
- → Reduce wire length
- → Lower I2C clock speed to 10kHz or 1kHz

## Code Files

1. **NAU7802_9ADC_Reader.ino** - Main measurement code
2. **NAU7802_Diagnostic_Detailed.ino** - Diagnostic tool
3. **Find_Multiplexers.ino** - Multiplexer identification tool

## Arduino Library Required

```
Adafruit NAU7802
```

Install via: Sketch → Include Library → Manage Libraries → Search "NAU7802"

## Typical Initialization Sequence

```cpp
1. Enable multiplexer channel
2. Initialize NAU7802 (nau.begin())
3. Set LDO voltage (nau.setLDO(NAU7802_3V3))
4. Set gain (nau.setGain(NAU7802_GAIN_128))
5. Set sample rate (nau.setRate(NAU7802_RATE_320SPS))
6. Calibrate internal offset
7. Calibrate system offset
8. Read values (nau.read())
```

## Next Steps for Strain Gauge Setup

1. **Connect strain gauges in Wheatstone bridge**
2. **Apply excitation voltage** (2.5V or 5V)
3. **Connect bridge outputs to NAU7802:**
   - VIN+ → Bridge positive output
   - VIN- → Bridge negative output
4. **Set appropriate gain** (start with 64x or 128x)
5. **Calibrate with zero load**
6. **Apply known load and verify readings**

## Contact Info

- ESP32-S3 Documentation: https://www.espressif.com/
- NAU7802 Datasheet: Available from Nuvoton
- TCA9548A Datasheet: Available from Texas Instruments

---

**Document created:** 2026-01-01
**System:** ESP32-S3 Feather with 9x NAU7802 ADCs
**Status:** Hardware verified, ready for sensor connection
