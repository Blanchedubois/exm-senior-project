# I2C Address Configuration for Iris Stretcher

## Detected Addresses (from your scan):
- **LCD Display:** `0x3F` ✓ Confirmed
- **Unknown Device:** `0x36` (probably a sensor or other I2C device)

## Updated Configuration:

### LCD Display
- **Address:** `0x3F` (hard-coded in firmware)
- **Config:** `AUTO_DETECT_LCD_ADDRESS = 0`
- **Status:** ✓ Fixed and ready to use

### TCA9548A Multiplexers (IMPORTANT - HARDWARE CHANGE REQUIRED!)

The multiplexer addresses have been changed to avoid conflicts:

| Multiplexer | Old Address | New Address | Hardware Config |
|-------------|-------------|-------------|-----------------|
| MUX1 | 0x70 | **0x74** | A2=1, A1=0, A0=0 |
| MUX2 | 0x71 | **0x75** | A2=1, A1=0, A0=1 |

### How to Configure TCA9548A Hardware:

Each TCA9548A multiplexer has three address pins (A0, A1, A2) that set its I2C address:

**Base address:** 0b1110xxx (0x70-0x77)

```
Address = 0x70 + (A2×4 + A1×2 + A0×1)
```

#### MUX1 Configuration (0x74):
- Connect A2 to **VCC** (HIGH)
- Connect A1 to **GND** (LOW)
- Connect A0 to **GND** (LOW)
- Result: 0x70 + (1×4 + 0×2 + 0×1) = **0x74**

#### MUX2 Configuration (0x75):
- Connect A2 to **VCC** (HIGH)
- Connect A1 to **GND** (LOW)
- Connect A0 to **VCC** (HIGH)
- Result: 0x70 + (1×4 + 0×2 + 1×1) = **0x75**

## I2C Bus Summary:

| Address | Device | Notes |
|---------|--------|-------|
| 0x2A | NAU7802 ADCs | Behind multiplexers (9 total) |
| 0x36 | Unknown | Detected in scan |
| 0x3F | LCD Display | 16x2 LCD with I2C backpack |
| 0x74 | MUX1 | TCA9548A - Channels 0-3 (ADCs 1-4) |
| 0x75 | MUX2 | TCA9548A - Channels 0-4 (ADCs 5-9) |

## Testing Steps:

1. **Configure multiplexer hardware** (set A2, A1, A0 pins as shown above)
2. **Upload I2C_Device_Scanner.ino** to verify addresses
3. **Check Serial Monitor** - you should see:
   - LCD at 0x3F ✓
   - MUX1 at 0x74 ✓
   - MUX2 at 0x75 ✓
   - 9 NAU7802 devices behind multiplexers ✓
4. **Upload main strain gauge code** (IrisModule1.0_StrainGauge9Ch.ino)
5. **Verify LCD displays** the splash screen

## Troubleshooting:

### If multiplexers are still at 0x70/0x71:
- Check A2 pin is connected to VCC (not floating)
- Verify all address pins are properly connected
- Some boards have solder jumpers instead of pins

### If LCD doesn't work:
- Verify it's at 0x3F using the scanner
- Check power to LCD (usually 5V)
- Check contrast potentiometer on I2C backpack
- Try adjusting backlight with potentiometer

### Alternative Multiplexer Addresses:
If you prefer different addresses, here are all options:

| A2 | A1 | A0 | Address |
|----|----|----|---------|
| 0  | 0  | 0  | 0x70    |
| 0  | 0  | 1  | 0x71    |
| 0  | 1  | 0  | 0x72    |
| 0  | 1  | 1  | 0x73    |
| 1  | 0  | 0  | **0x74** ← MUX1 |
| 1  | 0  | 1  | **0x75** ← MUX2 |
| 1  | 1  | 0  | 0x76    |
| 1  | 1  | 1  | 0x77    |

Just avoid 0x36 and 0x3F (already in use).
