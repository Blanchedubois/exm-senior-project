# Iris stretcher: earlier versions

Firmware and analysis scripts for the tensile-expansion (TExM) iris stretcher
from its first prototypes, 2025 to early 2026. The current hardware is in
[projects/texm-iris-stretcher](../../projects/texm-iris-stretcher/).

- `Iris_1.0` to `Iris6.0`: successive ESP32 sketches driving the iris motor and
  reading strain gauges; `Iris3.0StrainDataCollection` adds logging.
- `IrisLCDMenuCode`: on-device menu for the LCD.
- `SingleStrainGaugeArduinoMeasurement`, `Voltmeter`, `sketch_may29a`, `Test`:
  single-channel bench tests.
- `StrainGaugeMATLAB`, `strainGaugeSimulationV_1`, `MatLab tests`,
  `NeoHookeanModelFracture.m`: MATLAB analysis of gauge data and a neo-Hookean
  model of hydrogel fracture.
