# NAU7802 at 0x36 - Investigation Findings

**Date:** 2026-01-01
**Hardware:** 9x NAU7802SGI ADCs, ESP32-S3 Feather, 2x TCA9548A MUX
**Issue:** Unable to get continuous ADC readings

---

## Executive Summary

The NAU7802 chips at I2C address 0x36 (non-standard) exhibit highly unusual behavior that prevents standard operation:
- Only the first read after power-on returns valid data
- Subsequent reads return 0xFFFF (all bits high)
- Different I2C clock speeds return different data patterns
- Standard NAU7802 register protocol doesn't work

**Conclusion:** These boards require either:
1. Manufacturer-specific protocol documentation
2. Hardware modifications (RST pin control, level shifter bypass)
3. Alternative reading method (possibly SPI if available)
4. Different ADC chips entirely

---

## Detailed Findings

### 1. Device Detection
✅ **WORKING**
- Devices respond at I2C address **0x36** (not standard 0x2A)
- TCA9548A multiplexers at 0x71 and 0x73 work correctly
- Each MUX channel shows different device data
- All 9 ADCs detected successfully

### 2. I2C Communication Patterns

#### Clock Speed Effects
Different I2C speeds return **different data**:

| Speed   | Bytes Read              | Notes                    |
|---------|-------------------------|--------------------------|
| 1 kHz   | No response             | Too slow                 |
| 10 kHz  | `0xFF 0xFF 0xCA 0x50`   | Bytes 4-5 change         |
| 50 kHz  | `0x60 0xB6 0x00 0x00`   | Bytes 0-1 change         |
| 100 kHz | `0x00 0x12 0x80 0x30`   | Different pattern        |
| 400 kHz | `0x97 0x1C 0xFF 0xFF`   | Different pattern        |

**This behavior is NOT normal for NAU7802!**

### 3. Byte Duplication Pattern
ALL reads show byte duplication:
```
Read:     0x97 0x1C 0x97 0x1C 0xFF 0xFF 0xFF 0xFF
Pattern:  [A]  [B]  [A]  [B]  [C]  [D]  [C]  [D]
```

Every byte appears twice in sequence. This suggests:
- Hardware level shifter doubling data
- Non-standard I2C implementation
- Buffer/FIFO design quirk

### 4. First Read Success
**Only the first read after power-on works:**

First cycle:
```
ADC1: 53216  (valid data)
ADC2: 0      (valid data)
ADC3: 32816  (valid data)
...
```

All subsequent cycles:
```
ADC1-9: 65535 (0xFFFF) - invalid
```

### 5. Register Access Failures
Standard NAU7802 registers don't respond:
- Register 0x00 (PU_CTRL): Returns 0xFF instead of status
- Register 0x12-0x14 (ADC output): Returns 0xFF, 0xFF, 0x00
- Write operations ACK but don't affect device state

### 6. Tested Solutions (All Failed)
❌ Different I2C speeds (1kHz - 400kHz)
❌ Register-based reads
❌ Bulk reads with/without register address
❌ Repeated START vs STOP conditions
❌ I2C bus reinitialization between reads
❌ Various read byte counts (1, 3, 8, 12, 16, 24 bytes)
❌ Standard NAU7802 initialization sequences

---

## Test Code Provided

All code saved to iCloud folder:

1. **diagnostic_read/** - Comprehensive I2C diagnostics
2. **advanced_debug/** - Multiple test approaches
3. **focused_test/** - 10kHz optimized test
4. **reinit_per_read/** - Full reinit between reads
5. **working_9ch_reader/** - Best attempt at continuous reading
6. **direct_adc_reader/** - Original standard approach

---

## Recommendations

### Immediate Next Steps:

1. **Check Hardware Documentation**
   - Contact board manufacturer for I2C protocol specs
   - Request example code if available
   - Ask about address 0x36 vs 0x2A

2. **Hardware Inspection**
   - Check for level shifters on SDA/SCL lines
   - Look for address configuration resistors/jumpers
   - Verify NAU7802 RST pin connections
   - Check if AVDD is actually 3.3V or different

3. **Try Alternative Approaches**
   - If NAU7802 has SPI capability, try SPI mode
   - Add hardware RST pin control (toggle before each read)
   - Try extremely slow clock (500 Hz)
   - Use logic analyzer to capture working communication

4. **Consider Replacements**
   - Standard NAU7802 breakout boards (Adafruit/SparkFun)
   - HX711 (24-bit ADC, similar application)
   - ADS1232 (24-bit ADC, TI)

### Questions for Manufacturer:

1. Why do these NAU7802s respond at 0x36 instead of 0x2A?
2. What is the correct I2C read protocol for continuous operation?
3. Are there level shifters or buffers on the I2C lines?
4. Why does only the first read work after power-on?
5. Is there a required initialization sequence not in the datasheet?

---

## Technical Details

**Chip Marking:** NAU7802SGI 518GBFA
**I2C Address:** 0x36 (not standard 0x2A)
**Supply Voltage:** 3.3V (verified with scope)
**I2C Signal Quality:** Clean 3.3V levels, no capacitance issues
**ESP32 I2C:** Working correctly with other devices

---

## Files Generated

- All Arduino sketches (.ino files)
- This investigation report
- Hardware specifications document
- Debugging log with timestamps

---

## Conclusion

These NAU7802 boards have non-standard behavior that cannot be resolved through software alone. Hardware documentation from the manufacturer is essential to proceed. The ESP32, multiplexers, and I2C communication are all working correctly - the issue is specific to these NAU7802 boards.

Contact manufacturer with this report and request proper protocol documentation.
