"""
Demo script to generate a plot from sample data without GUI
This validates that all the data processing and plotting works correctly
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.interpolate import Akima1DInterpolator, PchipInterpolator
import re

# Sample data file
SAMPLE_FILE = "~/Library/Mobile Documents/com~apple~CloudDocs/Course Resources/Research Expansion Microscopy/Code/StrainGaugeMATLAB/AggregateStrainGaugeDataSet.xlsx"
OUTPUT_FILE = "~/StrainGaugeAnalyzerPython/demo_output.png"


def dedupe_tolerance(voltage, values, tol=1e-6, agg_func=np.median):
    """Deduplicate near-duplicate voltages"""
    mask = np.isfinite(voltage) & np.isfinite(values)
    voltage = voltage[mask]
    values = values[mask]

    if len(voltage) <= 1:
        return voltage, values

    sort_idx = np.argsort(voltage)
    voltage_sorted = voltage[sort_idx]
    values_sorted = values[sort_idx]

    gaps = np.diff(voltage_sorted)
    new_group = np.concatenate([[True], gaps > tol])
    group_ids = np.cumsum(new_group)

    unique_groups = np.unique(group_ids)
    voltage_out = np.array([np.mean(voltage_sorted[group_ids == g]) for g in unique_groups])
    values_out = np.array([agg_func(values_sorted[group_ids == g]) for g in unique_groups])

    if np.any(np.diff(voltage_out) <= 0):
        voltage_out = voltage_out + np.arange(len(voltage_out)) * np.finfo(float).eps * np.max(voltage_out)

    return voltage_out, values_out


def interp_makima_with_pchip_fallback(x, y, x_query):
    """Interpolate with Akima (MAKIMA); fallback to PCHIP if needed"""
    try:
        interpolator = Akima1DInterpolator(x, y)
        y_query = interpolator(x_query)

        if np.any(np.diff(y_query) < 0):
            interpolator = PchipInterpolator(x, y)
            y_query = interpolator(x_query)
    except Exception:
        interpolator = PchipInterpolator(x, y)
        y_query = interpolator(x_query)

    return y_query


def parse_soak_minutes(name):
    """Extract leading '<number> min' from sheet names"""
    match = re.match(r'^\s*(\d+)\s*min', name, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return np.nan


def main():
    print("Strain Gauge Analyzer - Demo Plot Generator")
    print("=" * 60)

    # Load data
    print(f"\nLoading data from: {SAMPLE_FILE}")
    excel_file = pd.ExcelFile(SAMPLE_FILE)
    sheet_names = excel_file.sheet_names
    print(f"Found {len(sheet_names)} sheets")

    # Read Force data
    force_df = pd.read_excel(SAMPLE_FILE, sheet_name='ForceVVoltage')
    force_raw = force_df.iloc[:, 0].values
    force_voltage_raw = force_df.iloc[:, 1].values
    print(f"Loaded Force data: {len(force_raw)} points")

    # Read expansion sheets
    expansion_sheets = [s for s in sheet_names if s.lower() != 'forcevvoltage']
    print(f"Found {len(expansion_sheets)} expansion sheets")

    # Process data
    print("\nProcessing data...")
    tol = 1e-6

    # Dedupe Force
    force_voltage, force_data = dedupe_tolerance(force_voltage_raw, force_raw, tol)
    print(f"Force data: {len(force_raw)} → {len(force_data)} points after deduplication")

    # Process expansion sheets
    expansion_data = []
    for sheet_name in expansion_sheets:
        exp_df = pd.read_excel(SAMPLE_FILE, sheet_name=sheet_name)
        exp_raw = exp_df.iloc[:, 0].values
        volt_raw = exp_df.iloc[:, 1].values

        volt, exp = dedupe_tolerance(volt_raw, exp_raw, tol)

        minutes = parse_soak_minutes(sheet_name)
        if np.isfinite(minutes):
            group_key = f"{int(minutes)} min"
        else:
            group_key = f"sheet: {sheet_name}"

        expansion_data.append({
            'name': sheet_name,
            'voltage': volt,
            'expansion': exp,
            'minutes': minutes,
            'group_key': group_key
        })

    # Find overlapping voltage range
    all_min_v = [force_voltage.min()] + [d['voltage'].min() for d in expansion_data]
    all_max_v = [force_voltage.max()] + [d['voltage'].max() for d in expansion_data]
    v_min = max(all_min_v)
    v_max = min(all_max_v)
    print(f"Voltage range: [{v_min:.6f}, {v_max:.6f}]")

    # Create grid
    def compute_median_step(v):
        diffs = np.diff(v)
        pos_diffs = diffs[diffs > 0]
        return np.median(pos_diffs) if len(pos_diffs) > 0 else np.nan

    steps = [compute_median_step(force_voltage)] + [compute_median_step(d['voltage']) for d in expansion_data]
    steps = [s for s in steps if np.isfinite(s) and s > 0]
    ds = min(steps) if steps else (v_max - v_min) / 200

    n_intervals = max(50, int(np.ceil((v_max - v_min) / ds)))
    n_intervals = int(np.ceil(n_intervals / 10) * 10)
    n_points = n_intervals + 1

    voltage_grid = np.linspace(v_min, v_max, n_points)
    print(f"Grid: {n_points} points")

    # Interpolate
    print("\nInterpolating...")
    force_interp = interp_makima_with_pchip_fallback(force_voltage, force_data, voltage_grid)

    for data in expansion_data:
        exp_interp = interp_makima_with_pchip_fallback(data['voltage'], data['expansion'], voltage_grid)
        exp_interp[exp_interp < 0] = 0  # Clamp negatives
        data['expansion_interp'] = exp_interp

    # Generate plot
    print("\nGenerating plot...")
    fig, ax = plt.subplots(figsize=(10, 6))

    # Get unique group keys
    group_keys = [d['group_key'] for d in expansion_data]
    unique_keys = sorted(set(group_keys), key=lambda x: group_keys.index(x))

    # Color map
    cmap = plt.cm.tab10
    group_colors = {key: cmap(i % 10) for i, key in enumerate(unique_keys)}

    # Markers
    markers = ['+', 'd', 'x', '^', 'v', '>', '<', 'p', 'h', '*', 'o', 's', '.']
    filled_markers = ['o', 'd', 's', '^', 'v', '>', '<', 'p', 'h']

    # Track replicates
    seen_count = {}

    # Plot each series
    for data in expansion_data:
        group_key = data['group_key']

        if group_key not in seen_count:
            seen_count[group_key] = 0
        seen_count[group_key] += 1
        rep_idx = seen_count[group_key]

        # Color variation
        base_color = np.array(group_colors[group_key][:3])
        alphas = [0.00, 0.15, 0.25, 0.10, 0.20, 0.30]
        alpha = alphas[(rep_idx - 1) % len(alphas)]

        if rep_idx % 2 == 1:
            target = np.array([1, 1, 1])
        else:
            target = np.array([0, 0, 0])
            alpha *= 0.8

        color = (1 - alpha) * base_color + alpha * target
        color = np.clip(color, 0, 1)

        # Marker
        marker = markers[(rep_idx - 1) % len(markers)]

        # Plot
        if marker in filled_markers:
            ax.plot(data['expansion_interp'], force_interp,
                   marker=marker, linestyle='', markersize=5, linewidth=1.5,
                   color=color, markerfacecolor=color, markeredgecolor=color,
                   label=data['name'])
        else:
            ax.plot(data['expansion_interp'], force_interp,
                   marker=marker, linestyle='', markersize=5, linewidth=1.5,
                   color=color, markeredgecolor=color,
                   label=data['name'])

    # Format
    ax.set_xlabel('Expansion (units)', fontsize=11)
    ax.set_ylabel('Force (N)', fontsize=11)
    ax.set_title('Hydrogel Force vs Expansion (MAKIMA with PCHIP fallback)',
                fontsize=12, fontweight='bold')
    ax.legend(loc='best', fontsize=8)
    ax.grid(True, alpha=0.4)
    ax.grid(True, which='minor', alpha=0.3)
    ax.minorticks_on()

    # Auto limits
    all_exp = np.concatenate([d['expansion_interp'] for d in expansion_data])
    ax.set_xlim([all_exp.min(), all_exp.max()])

    plt.tight_layout()

    # Save
    print(f"\nSaving plot to: {OUTPUT_FILE}")
    fig.savefig(OUTPUT_FILE, dpi=300, bbox_inches='tight')
    print("✓ Plot saved successfully!")

    print("\n" + "=" * 60)
    print("Demo completed successfully!")
    print(f"\nYou can view the plot at: {OUTPUT_FILE}")
    print("\nTo run the full GUI application, execute:")
    print("  python3 strain_gauge_analyzer.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
