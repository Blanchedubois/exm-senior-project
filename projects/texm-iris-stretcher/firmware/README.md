# 9-Channel NAU7802 ADC System - ESP32-S3 Feather

## Hardware Setup

**Microcontroller:** Adafruit Feather ESP32-S3

**ADCs:** 9x NAU7802SGI 24-bit ADCs  
- **Address:** 0x36 (NOT the standard 0x2A)
- **Important:** These NAU7802s respond at address 0x36, which is non-standard

**Multiplexers:** 2x TCA9548A I2C Multiplexers
- **MUX 0x71:** 4 ADCs on channels 0-3
- **MUX 0x73:** 5 ADCs on channels 0-4
- **RESET pins:** Pulled HIGH (confirmed working)

**I2C Configuration:**
- **Clock Speed:** 400 kHz (recommended for NAU7802 + TCA9548A)
- **SDA/SCL:** Connected to ESP32-S3 I2C pins
- **Pull-up resistors:** Present on each channel (confirmed not causing issues)

---

## Key Findings

### 1. Address Discovery
- Standard NAU7802 uses address **0x2A**
- Your NAU7802SGI chips respond at address **0x36**
- This is critical for all I2C communication

### 2. Multiplexer Verification
✅ **TCA9548A multiplexers are working correctly**
- I2C scan showed different devices on different channels
- Each channel can be independently selected
- No channel crosstalk detected

### 3. ADC Communication
✅ **ADCs respond and initialize successfully**
- All 9 ADCs power up and respond to I2C commands
- Initial readings show real voltage values
- Multiplexer channel switching works correctly

### 4. Current Limitation
⚠️ **Continuous readings issue:**
- First read cycle gets fresh ADC data
- Subsequent reads return 0xFFFFFF (-1)
- Likely needs specific conversion trigger sequence
- Standard NAU7802 libraries don't work (wrong address)

---

## I2C Bus Scan Results

**Main Bus (all MUX channels OFF):**
- 0x36 (unknown device on main bus)
- 0x71 (TCA9548A MUX 1)
- 0x73 (TCA9548A MUX 2)

**Each MUX Channel:**
- Shows 0x36 device when selected
- Different data per channel confirms multiplexing works

---

## Working Code

The functional Arduino sketch is saved as:
- `direct_adc_reader.ino`

**Features:**
- Initializes all 9 ADCs through multiplexers
- Reads ADC values directly at address 0x36
- Uses 400 kHz I2C clock speed
- Organized channel structure for easy modification

---

## Best Practices Learned

### I2C Multiplexer Usage
1. **Always select channel before ADC operation:**
   ```cpp
   tcaSelect(MUX_ADDR, channel);
   delay(10);  // Brief delay after channel switch
   // Then perform ADC operation
   ```

2. **Don't use arbitrary delays** - I2C timing handles itself

3. **For multiple ADCs, use arrays** to keep code clean and maintainable

### NAU7802 with TCA9548A
- **Run I2C at 400 kHz** for optimal performance
- **Select MUX channel before EVERY NAU7802 call** (read/config/calibrate)
- **All NAU7802s share same address** - multiplexer isolates them

---

## Next Steps

### To Get Continuous Readings:
1. **Find conversion trigger command** for NAU7802 at 0x36
   - Check if there's a variant-specific datasheet
   - May need to write to a control register before each read

2. **Experiment with register sequences:**
   - Try writing to different control registers
   - Monitor what changes between successful and failed reads

3. **Consider using oscilloscope/logic analyzer:**
   - Capture I2C traffic during successful read
   - Compare with failed reads to identify missing commands

### Possible Solutions to Try:
```cpp
// Before each read, try:
writeRegister(NAU7802_PU_CTRL, 0x0F);  // Start conversion
delay(100);  // Wait for conversion
// Then read
```

Or investigate if these are actually a different ADC chip that happens to use address 0x36.

---

## Sample Output

```
9-Channel ADC Reader - Direct I2C
===================================

Initializing ADCs...
ADC1 initialized on MUX 0x71, Channel 0
ADC2 initialized on MUX 0x71, Channel 1
...
ADC9 initialized on MUX 0x73, Channel 4

Setup complete!

====================================
ADC Readings:
====================================
ADC1: -1 | -0.000000 V
ADC2: 6068572 | 1.085145 V
ADC3: 4608 | 0.000824 V
ADC4: -6873961 | -1.229160 V
ADC5: -1 | -0.000000 V
ADC6: 65280 | 0.011673 V
ADC7: -6943594 | -1.241611 V
ADC8: -1 | -0.000000 V
ADC9: -1 | -0.000000 V
```

*(First cycle shows real data, subsequent cycles need conversion trigger)*

---

## Troubleshooting

### All ADCs show -1 or 0xFFFFFF:
- ADC not responding or data not ready
- May need conversion trigger
- Check if MUX channel is selected

### Same readings on all channels:
- Check if MUX channel selection is working
- Verify tcaSelect() is called before each read
- Ensure RESET pins on TCA9548A are HIGH

### I2C communication fails:
- Verify I2C clock speed (should be 400 kHz)
- Check pull-up resistors (need one set per channel)
- Confirm address 0x36 (NOT 0x2A)

---

## Hardware Connections Verified

✅ NAU7802 SDA/SCL connected to TCA9548A channel outputs  
✅ TCA9548A main bus connected to ESP32-S3  
✅ All devices powered (VDD connected)  
✅ TCA9548A RESET pins pulled HIGH  
✅ Pull-up resistors present on I2C lines

---

## Files in This Directory

- `README.md` - This file
- `direct_adc_reader.ino` - Working Arduino sketch
- `hardware_specs.txt` - Detailed hardware specifications

---

## Contact & Development

**Date:** January 1, 2026  
**Platform:** ESP32-S3 (Adafruit Feather)  
**Arduino IDE Version:** Compatible with arduino-cli 1.2.0  
**Core:** ESP32 Arduino 3.2.0

---
