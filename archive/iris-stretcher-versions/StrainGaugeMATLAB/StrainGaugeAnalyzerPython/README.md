# Strain Gauge Analyzer - Python GUI Application

A Python-based GUI application that converts MATLAB MakimaNPCHIP functionality for analyzing strain gauge data from expansion microscopy experiments.

## Features

- **GUI Interface**: User-friendly interface with file upload capability
- **Excel File Support**: Reads .xls and .xlsx files
- **Advanced Interpolation**: Uses MAKIMA (Akima) interpolation with PCHIP fallback
- **Data Processing**:
  - Deduplicates near-duplicate voltage readings
  - Ensures monotonically increasing data
  - Clamps negative expansion values
- **Intelligent Plotting**:
  - Groups data by soak time (e.g., "8 min", "12 min")
  - Assigns consistent colors per group
  - Uses different markers for replicates
  - Automatic shade variation for visual distinction
- **Export Capability**: Save plots as PNG, PDF, or SVG

## Installation

1. Install Python 3.7 or higher

2. Install required packages:
```bash
pip install -r requirements.txt
```

Or install manually:
```bash
pip install numpy pandas matplotlib scipy openpyxl
```

## Usage

1. Run the application:
```bash
python strain_gauge_analyzer.py
```

2. Click "Upload Excel File" to select your data file

3. Click "Generate Plot" to process data and create the visualization

4. Use "Export Plot" to save the figure

## Excel File Format

Your Excel file should contain:

1. **ForceVVoltage** sheet (required):
   - Column 1: Force (N)
   - Column 2: Voltage (V)

2. **Expansion sheets** (any other sheet names):
   - Column 1: Expansion (units)
   - Column 2: Voltage (V)

   Sheet names containing "<number> min" (e.g., "8 min CaSO₄ test 7") will be grouped together with the same color.

## Algorithm Details

1. **Deduplication**: Merges voltage readings within 1e-6 V tolerance using median aggregation
2. **Grid Generation**: Creates uniform voltage grid based on smallest median step size
3. **Interpolation**:
   - Primary: MAKIMA (Akima1DInterpolator) for smooth curves
   - Fallback: PCHIP for monotonicity preservation
4. **Physical Constraints**: Clamps negative expansion values to zero

## MATLAB Equivalence

This application replicates the functionality of:
- `MAKIMAnPCHIP.m`
- `UpdatedMakimaNPCHIP.m`
- `AllowAnySheetNameMakimaNPCHIP.m`

### Key Conversions:
- MATLAB `makima` → SciPy `Akima1DInterpolator`
- MATLAB `pchip` → SciPy `PchipInterpolator`
- MATLAB `accumarray` → Python grouping with NumPy
- MATLAB `uigetfile` → tkinter `filedialog`

## Requirements

- Python >= 3.7
- numpy >= 1.21.0
- pandas >= 1.3.0
- matplotlib >= 3.4.0
- scipy >= 1.7.0
- openpyxl >= 3.0.0

## Author

Converted from MATLAB to Python with GUI enhancement
