# Quick Start Guide - Strain Gauge Analysis Tools

This folder contains two Python GUI applications for analyzing strain gauge data from expansion microscopy experiments.

## Which Application Should I Use?

### 🔹 Basic Analyzer (`strain_gauge_analyzer.py`)
**Best for**: Viewing all individual measurements with color-coded grouping

**Use when you want to**:
- See every individual test result
- Compare individual traces side-by-side
- Create plots showing all raw measurements
- Group data by soak time with consistent colors

**Run with**:
```bash
python3 strain_gauge_analyzer.py
# or
./run_analyzer.sh
```

**MATLAB Equivalent**: MAKIMAnPCHIP.m, UpdatedMakimaNPCHIP.m

---

### 🔹 Aggregator (`strain_gauge_aggregator.py`) ⭐ RECOMMENDED
**Best for**: Aggregating replicates by time soak with statistical analysis

**Use when you want to**:
- Combine multiple replicates into mean/median curves
- Show error bands (SD, SEM, or min/max)
- Create publication-ready figures
- Compare aggregated performance across different soak times
- Toggle between individual and aggregated views

**Run with**:
```bash
python3 strain_gauge_aggregator.py
# or
./run_aggregator.sh
```

**MATLAB Equivalent**: AllowAnySheetNameMakimaNPCHIP.m (plus aggregation features)

---

## Installation (One Time Setup)

```bash
# Navigate to the folder
cd ~/StrainGaugeAnalyzerPython

# Install dependencies
pip3 install -r requirements.txt
```

## Quick Demos

### Test Basic Analyzer
```bash
python3 demo_plot.py
# Generates: demo_output.png
```

### Test Aggregator
```bash
python3 demo_aggregation.py
# Generates: demo_individual_only.png
#            demo_aggregated_only.png
#            demo_combined.png
```

## File Structure

```
StrainGaugeAnalyzerPython/
├── strain_gauge_analyzer.py         Main basic analyzer
├── strain_gauge_aggregator.py       Main aggregator (with stats)
├── run_analyzer.sh                  Launcher for basic
├── run_aggregator.sh                Launcher for aggregator
├── requirements.txt                 Python dependencies
├── README.md                        Basic analyzer docs
├── README_AGGREGATOR.md             Aggregator docs (detailed)
├── QUICK_START.md                   This file
├── test_processing.py               Unit tests
├── demo_plot.py                     Demo for basic analyzer
├── demo_aggregation.py              Demo for aggregator
└── demo_*.png                       Example outputs
```

## Typical Workflow

### For Individual Measurements
1. Run `strain_gauge_analyzer.py`
2. Upload your Excel file
3. Click "Generate Plot"
4. Export as PNG/PDF

### For Aggregated Analysis (Recommended)
1. Run `strain_gauge_aggregator.py`
2. Upload your Excel file
3. Review the data summary (shows groups and replicates)
4. Choose display mode:
   - **"Both"** - See all data + aggregates (great for exploration)
   - **"Aggregated"** - Clean mean/median curves (for publications)
   - **"Individual"** - All traces (for detailed inspection)
5. Select aggregation method (mean or median)
6. Toggle error bands and select type (SEM recommended)
7. Adjust individual trace opacity if using "Both" mode
8. Click "Generate Plot"
9. Export as PNG/PDF/SVG

## Excel File Format

Your Excel file should have:

1. **ForceVVoltage** sheet:
   - Column 1: Force (N)
   - Column 2: Voltage (V)

2. **Expansion sheets** (any names):
   - Column 1: Expansion (units)
   - Column 2: Voltage (V)

**Naming tip**: Use format like "8 min test 1", "8 min test 2", "10 min test 1", etc.
The number before "min" is automatically used for grouping.

## Example Data Groups

With the demo file, you get:
- 8 min: 2 replicates → averaged together
- 10 min: 3 replicates → averaged together
- 12 min: 2 replicates → averaged together
- 15 min: 1 replicate → shown as-is

Each group gets a distinct color, and the aggregator computes statistics across replicates.

## Troubleshooting

**"No file loaded"**
- Make sure your Excel file has a "ForceVVoltage" sheet
- Check that other sheets have expansion data

**"No common overlap in voltage ranges"**
- Your datasets don't have overlapping voltage measurements
- Check that all sheets measure similar voltage ranges

**Error bands too large**
- High variability between replicates
- Consider using median instead of mean
- Check for outlier measurements

**Plots look wrong**
- Verify your Excel file format matches the specification
- Try running the demo scripts first to confirm installation

## Support Files

### Test Your Installation
```bash
python3 test_processing.py
```
Should show "✓ All tests passed!"

### Generate Example Plots
```bash
python3 demo_plot.py
python3 demo_aggregation.py
```

## Tips for Best Results

1. **Consistent Naming**: Keep time soak naming consistent across sheets
2. **Multiple Replicates**: Aim for 3+ replicates per time group
3. **Data Quality**: Remove obviously bad measurements before analysis
4. **Export Format**:
   - PNG (300 dpi) for presentations and web
   - PDF/SVG for publications (vector graphics, scalable)

## Need Help?

1. Read `README_AGGREGATOR.md` for detailed documentation
2. Run the demo scripts to see examples
3. Check that test_processing.py passes all tests
4. Verify your Excel file format matches the specification

## Summary

- **Just want to see all your data?** → Use `strain_gauge_analyzer.py`
- **Want statistics and publication figures?** → Use `strain_gauge_aggregator.py` ⭐
- **Not sure?** → Start with the aggregator, it can show both!

Both tools use the same advanced interpolation (MAKIMA with PCHIP fallback) and handle data preprocessing automatically.
