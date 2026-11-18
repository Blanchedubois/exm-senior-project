# Strain Gauge Aggregator - Time Soak Analysis

Advanced Python GUI application for analyzing and aggregating strain gauge data by time soak groups. This application extends the basic analyzer with powerful aggregation capabilities.

## Key Features

### 1. **Flexible Display Modes**
- **Individual Traces Only**: Show all individual measurements with color grouping
- **Aggregated Only**: Display mean/median curves with error bands
- **Combined View**: Show both individual (faded) and aggregated (bold) traces

### 2. **Aggregation Methods**
- **Mean**: Average across replicates
- **Median**: Robust to outliers

### 3. **Error Visualization**
- **Standard Deviation (SD)**: Shows full data spread
- **Standard Error of Mean (SEM)**: Shows precision of the mean estimate
- **Min/Max Range**: Shows the full range of variation

### 4. **Intelligent Grouping**
- Automatically groups data by soak time (e.g., "8 min", "10 min", "12 min")
- Consistent colors per time group
- Clear replicate identification

### 5. **Interactive Controls**
- Adjustable opacity for individual traces
- Real-time plot regeneration
- Export to PNG, PDF, or SVG

## Installation

```bash
cd ~/StrainGaugeAnalyzerPython
pip3 install -r requirements.txt
```

## Usage

### Run the GUI Application

```bash
python3 strain_gauge_aggregator.py
```

### Application Workflow

1. **Upload Excel File**: Click "Upload Excel File" and select your data
2. **Configure Display**:
   - Choose display mode (individual/aggregated/both)
   - Select aggregation method (mean/median)
   - Toggle error bands and select error type
   - Adjust individual trace opacity
3. **Generate Plot**: Click "Generate Plot" to visualize
4. **Export**: Save your plot in various formats

### Run Demo (Command Line)

```bash
python3 demo_aggregation.py
```

This generates three example plots:
- `demo_individual_only.png` - All individual traces
- `demo_aggregated_only.png` - Aggregated curves with SEM bands
- `demo_combined.png` - Combined view

## Excel File Format

Same as the basic analyzer:

1. **ForceVVoltage** sheet (required):
   - Column 1: Force (N)
   - Column 2: Voltage (V)

2. **Expansion sheets** (any other sheet names):
   - Column 1: Expansion (units)
   - Column 2: Voltage (V)

Sheet names containing "<number> min" (e.g., "8 min CaSO₄ test 7", "10 min CaSO₄ test 2") will be automatically grouped together.

## Example Data Summary

From the demo file:
- **8 min group**: 2 replicates (8 min CaSO₄ test 7, 8 min CaSO₄ test 8)
- **10 min group**: 3 replicates (10 min CaSO₄ test 2, test 3, test 4)
- **12 min group**: 2 replicates (12 min CaSO₄ test 5, test 6)
- **15 min group**: 1 replicate (15MinSoakCaSO4Test1)

## Statistical Methods

### Aggregation
- Data from all replicates at each time point are combined
- Central tendency computed using mean or median
- All calculations performed on interpolated, aligned data

### Error Bands
- **Standard Deviation**: `σ = sqrt(Σ(xi - μ)² / (n-1))`
- **Standard Error**: `SEM = σ / sqrt(n)`
- **Min/Max**: Simple range across all replicates

The shaded bands represent ± 1 error unit (SD or SEM) or the full min/max range.

## Use Cases

### Research Applications
1. **Compare time soaks**: Visualize how different soak times affect force-expansion behavior
2. **Assess variability**: Use error bands to understand measurement precision
3. **Publication-ready figures**: Clean, professional plots with customizable styles
4. **Replicate analysis**: Easily identify outliers or trends across replicates

### Data Exploration
- Start with "Both" mode to see all data and aggregates simultaneously
- Use "Aggregated only" for clean presentation figures
- Adjust individual trace opacity to emphasize aggregated trends

## GUI Controls Reference

### Display Mode
- **Individual traces only**: Best for examining individual replicate behavior
- **Aggregated by time soak**: Best for publication figures showing group trends
- **Both**: Best for data exploration and quality checking

### Aggregation Method
- **Mean**: Use when data is normally distributed
- **Median**: Use when outliers are present or data is skewed

### Error Visualization
- **Standard deviation**: Shows biological/experimental variability
- **Standard error (SEM)**: Shows precision of group mean (smaller bands)
- **Min/Max range**: Shows full extent of variation (larger bands)

### Individual Trace Opacity
- Set to 1.0 for equal emphasis on individual and aggregated traces
- Set to 0.1-0.3 for faded individual traces that don't overwhelm aggregates

## Technical Details

### Data Processing Pipeline
1. Load raw data from Excel sheets
2. Deduplicate near-duplicate voltage readings (1e-6 V tolerance)
3. Verify monotonically increasing voltages
4. Find common voltage range across all datasets
5. Create uniform voltage grid
6. Interpolate using MAKIMA (Akima) with PCHIP fallback
7. Clamp negative expansion values to zero
8. Group by time soak
9. Compute aggregated statistics
10. Generate plots with error bands

### Interpolation Strategy
- Primary: MAKIMA (Akima1DInterpolator) for smooth, low-oscillation curves
- Fallback: PCHIP (PchipInterpolator) if MAKIMA produces non-monotonic results
- This ensures physically reasonable force-expansion relationships

## Comparison to MATLAB Version

This Python application replicates and extends:
- `AllowAnySheetNameMakimaNPCHIP.m`

### Python Advantages
1. **GUI Interface**: No command-line interaction needed
2. **Interactive Controls**: Real-time parameter adjustment
3. **Aggregation Options**: Multiple statistical methods
4. **Error Visualization**: Built-in uncertainty quantification
5. **Cross-Platform**: Runs on macOS, Windows, Linux

## Requirements

- Python >= 3.7
- numpy >= 1.21.0
- pandas >= 1.3.0
- matplotlib >= 3.4.0
- scipy >= 1.7.0
- openpyxl >= 3.0.0

## Tips for Best Results

1. **Consistent Naming**: Use consistent sheet naming with time soaks (e.g., "8 min test 1", "8 min test 2")
2. **Sufficient Replicates**: At least 3 replicates per time group for meaningful error bands
3. **Data Quality**: Ensure voltage ranges overlap across all datasets
4. **Export Settings**: Use PDF or SVG for publications (vector graphics), PNG for presentations

## Troubleshooting

**Problem**: Error bands are very large
- **Solution**: Check for outlier replicates; consider using median instead of mean

**Problem**: Aggregated curves look jagged
- **Solution**: This indicates insufficient voltage overlap or interpolation issues; check raw data quality

**Problem**: No error bands shown
- **Solution**: Error bands only appear when n > 1 for a group; ensure multiple replicates exist

**Problem**: Sheet not grouping correctly
- **Solution**: Ensure sheet name contains "<number> min" (e.g., "8 min", "10 min")

## Author

Converted from MATLAB to Python with aggregation enhancements
