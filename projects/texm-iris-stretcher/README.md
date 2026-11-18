# TExM iris stretcher

Hardware for tensile expansion microscopy: a motorised iris that grips a
hydrogel at nine points and stretches it radially, with a strain gauge on each
arm so the applied force is known. Expansion factor is set by iris position,
which is what lets TExM be compared with MAGNIFY at a matched factor in the
[proposal](../../docs/proposal/).

## Folders

- `cad/`: the stretcher mechanics, by version. `Iris Stretcher V9` is the
  current body; `Iris Stretcher Gripper*` and `Gripper Mount*` are the arm
  grippers and mounts; `Primary` and `Secondary Iris Stretcher Box` are the
  enclosures; `STL/` and `3D PRINT FILES/` are the printable exports;
  `StrainGaugePCB3DModel/` is the gauge amplifier board. Printer toolpaths
  (gcode) are not committed; regenerate them from the STL or 3MF files.
- `firmware/`: ESP32-S3 Feather code.
  - `IrisModule1.0_base/`: the iris motor controller without gauges.
  - `IrisModule1.0wStrainGauge/`: the controller with the nine-channel readout.
  - `9_Arm_StrainGaugeCode/`, `NAU7802_9ADC_Reader/`, `working_9ch_reader/`:
    readers for nine NAU7802 24-bit ADCs behind two TCA9548A I2C multiplexers.
  - `diagnostic_read/`, `direct_adc_reader/`, `focused_test/`, `i2c_scan_10khz/`,
    `reinit_per_read/`, `advanced_debug/`: bench sketches from the readout investigation.
  - [`README.md`](firmware/README.md), [`INVESTIGATION_FINDINGS.md`](firmware/INVESTIGATION_FINDINGS.md),
    `NAU7802_Documentation.md`, `hardware_specs.txt`, `quick_reference.txt`, `debugging_log.txt`:
    what was learned. The short version: the ADC boards answer at the
    non-standard I2C address 0x36 and return valid data only on the first read,
    so the standard NAU7802 libraries do not work and the readout is still being
    resolved.

Earlier firmware versions and the MATLAB analysis are in
[archive/iris-stretcher-versions](../../archive/iris-stretcher-versions/).
The mechanics are derived in
[docs/reports/iris-stretcher-mathematical-calculations.pdf](../../docs/reports/iris-stretcher-mathematical-calculations.pdf).
