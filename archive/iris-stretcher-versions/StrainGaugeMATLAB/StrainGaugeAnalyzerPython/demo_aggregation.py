"""
Demo script for aggregated strain gauge analysis
Generates plots showing individual, aggregated, and combined views
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.interpolate import Akima1DInterpolator, PchipInterpolator
import re

# Sample data file
SAMPLE_FILE = "~/Library/Mobile Documents/com~apple~CloudDocs/Course Resources/Research Expansion Microscopy/Code/StrainGaugeMATLAB/AggregateStrainGaugeDataSet.xlsx"
OUTPUT_DIR = "~/StrainGaugeAnalyzerPython/"


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
    """Interpolate with Akima; fallback to PCHIP if needed"""
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
    """Extract '<number> min' from sheet names"""
    match = re.search(r'(\d+)\s*min', name, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return np.nan


def main():
    print("Aggregated Strain Gauge Analysis - Demo")
    print("=" * 60)

    # Load data
    print(f"\nLoading data from: {SAMPLE_FILE}")
    excel_file = pd.ExcelFile(SAMPLE_FILE)
    sheet_names = excel_file.sheet_names

    # Read Force data
    force_df = pd.read_excel(SAMPLE_FILE, sheet_name='ForceVVoltage')
    force_raw = force_df.iloc[:, 0].values
    force_voltage_raw = force_df.iloc[:, 1].values

    # Read expansion sheets
    expansion_sheets = [s for s in sheet_names if s.lower() != 'forcevvoltage']
    print(f"Found {len(expansion_sheets)} expansion sheets")

    # Process data
    print("\nProcessing data...")
    tol = 1e-6

    force_voltage, force_data = dedupe_tolerance(force_voltage_raw, force_raw, tol)

    # Process expansion sheets and group by time
    expansion_data = []
    groups = {}

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

        data = {
            'name': sheet_name,
            'voltage': volt,
            'expansion': exp,
            'minutes': minutes,
            'group_key': group_key
        }
        expansion_data.append(data)

        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(data)

    # Print group summary
    print("\nGroup Summary:")
    for group_key in sorted(groups.keys()):
        print(f"  {group_key}: {len(groups[group_key])} replicates")

    # Create voltage grid
    all_min_v = [force_voltage.min()] + [d['voltage'].min() for d in expansion_data]
    all_max_v = [force_voltage.max()] + [d['voltage'].max() for d in expansion_data]
    v_min = max(all_min_v)
    v_max = min(all_max_v)

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

    # Interpolate
    print("\nInterpolating...")
    force_interp = interp_makima_with_pchip_fallback(force_voltage, force_data, voltage_grid)

    for data in expansion_data:
        exp_interp = interp_makima_with_pchip_fallback(data['voltage'], data['expansion'], voltage_grid)
        exp_interp[exp_interp < 0] = 0
        data['expansion_interp'] = exp_interp

    # Aggregate by group
    print("\nAggregating by time soak...")
    aggregated = {}
    for group_key, group_data_list in groups.items():
        expansions = np.array([d['expansion_interp'] for d in group_data_list])

        aggregated[group_key] = {
            'mean': np.mean(expansions, axis=0),
            'median': np.median(expansions, axis=0),
            'std': np.std(expansions, axis=0, ddof=1 if len(expansions) > 1 else 0),
            'sem': np.std(expansions, axis=0, ddof=1 if len(expansions) > 1 else 0) / np.sqrt(len(expansions)),
            'min': np.min(expansions, axis=0),
            'max': np.max(expansions, axis=0),
            'n': len(expansions),
            'group_data': group_data_list
        }

    # Generate plots
    print("\nGenerating plots...")

    # Color map
    unique_keys = sorted(groups.keys())
    cmap = plt.cm.tab10
    group_colors = {key: cmap(i % 10) for i, key in enumerate(unique_keys)}

    # Figure 1: Individual traces only
    print("  1. Individual traces...")
    fig1, ax1 = plt.subplots(figsize=(10, 6))

    markers = ['+', 'd', 'x', '^', 'v', '>', '<', 'p', 'h', '*', 'o', 's', '.']
    filled_markers = ['o', 'd', 's', '^', 'v', '>', '<', 'p', 'h']
    seen_count = {}

    for data in expansion_data:
        group_key = data['group_key']
        if group_key not in seen_count:
            seen_count[group_key] = 0
        seen_count[group_key] += 1
        rep_idx = seen_count[group_key]

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

        marker = markers[(rep_idx - 1) % len(markers)]

        if marker in filled_markers:
            ax1.plot(data['expansion_interp'], force_interp,
                    marker=marker, linestyle='', markersize=4, linewidth=1,
                    color=color, markerfacecolor=color, markeredgecolor=color,
                    label=data['name'])
        else:
            ax1.plot(data['expansion_interp'], force_interp,
                    marker=marker, linestyle='', markersize=4, linewidth=1,
                    color=color, markeredgecolor=color,
                    label=data['name'])

    ax1.set_xlabel('Expansion (units)', fontsize=11)
    ax1.set_ylabel('Force (N)', fontsize=11)
    ax1.set_title('Individual Traces Only', fontsize=12, fontweight='bold')
    ax1.legend(loc='best', fontsize=8)
    ax1.grid(True, alpha=0.4)
    ax1.grid(True, which='minor', alpha=0.3)
    ax1.minorticks_on()
    all_exp = np.concatenate([d['expansion_interp'] for d in expansion_data])
    ax1.set_xlim([all_exp.min(), all_exp.max()])
    plt.tight_layout()

    output1 = OUTPUT_DIR + "demo_individual_only.png"
    fig1.savefig(output1, dpi=300, bbox_inches='tight')
    print(f"     Saved: {output1}")

    # Figure 2: Aggregated only (with error bands)
    print("  2. Aggregated traces with error bands...")
    fig2, ax2 = plt.subplots(figsize=(10, 6))

    for group_key in sorted(aggregated.keys()):
        agg_data = aggregated[group_key]
        base_color = group_colors[group_key]

        expansion_mean = agg_data['mean']

        # Main line
        ax2.plot(expansion_mean, force_interp,
                linestyle='-', linewidth=2.5, color=base_color,
                marker='o', markersize=6, markerfacecolor=base_color,
                markeredgecolor='white', markeredgewidth=0.5,
                label=f"{group_key} (n={agg_data['n']}, mean)", zorder=10)

        # Error bands (SEM)
        if agg_data['n'] > 1:
            lower = expansion_mean - agg_data['sem']
            upper = expansion_mean + agg_data['sem']
            ax2.fill_betweenx(force_interp, lower, upper,
                            color=base_color, alpha=0.2, zorder=5)

    ax2.set_xlabel('Expansion (units)', fontsize=11)
    ax2.set_ylabel('Force (N)', fontsize=11)
    ax2.set_title('Aggregated Traces Only (Mean ± SEM)', fontsize=12, fontweight='bold')
    ax2.legend(loc='best', fontsize=9)
    ax2.grid(True, alpha=0.4)
    ax2.grid(True, which='minor', alpha=0.3)
    ax2.minorticks_on()
    ax2.set_xlim([all_exp.min(), all_exp.max()])
    plt.tight_layout()

    output2 = OUTPUT_DIR + "demo_aggregated_only.png"
    fig2.savefig(output2, dpi=300, bbox_inches='tight')
    print(f"     Saved: {output2}")

    # Figure 3: Both (individual + aggregated)
    print("  3. Combined view (individual + aggregated)...")
    fig3, ax3 = plt.subplots(figsize=(10, 6))

    # Individual traces (lighter)
    seen_count = {}
    for data in expansion_data:
        group_key = data['group_key']
        if group_key not in seen_count:
            seen_count[group_key] = 0
        seen_count[group_key] += 1
        rep_idx = seen_count[group_key]

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

        marker = markers[(rep_idx - 1) % len(markers)]

        if marker in filled_markers:
            ax3.plot(data['expansion_interp'], force_interp,
                    marker=marker, linestyle='', markersize=3, linewidth=0.5,
                    color=color, markerfacecolor=color, markeredgecolor=color,
                    alpha=0.3)
        else:
            ax3.plot(data['expansion_interp'], force_interp,
                    marker=marker, linestyle='', markersize=3, linewidth=0.5,
                    color=color, markeredgecolor=color,
                    alpha=0.3)

    # Aggregated traces
    for group_key in sorted(aggregated.keys()):
        agg_data = aggregated[group_key]
        base_color = group_colors[group_key]

        expansion_mean = agg_data['mean']

        ax3.plot(expansion_mean, force_interp,
                linestyle='-', linewidth=2.5, color=base_color,
                marker='o', markersize=6, markerfacecolor=base_color,
                markeredgecolor='white', markeredgewidth=0.5,
                label=f"{group_key} (n={agg_data['n']}, mean)", zorder=10)

        if agg_data['n'] > 1:
            lower = expansion_mean - agg_data['sem']
            upper = expansion_mean + agg_data['sem']
            ax3.fill_betweenx(force_interp, lower, upper,
                            color=base_color, alpha=0.15, zorder=5)

    ax3.set_xlabel('Expansion (units)', fontsize=11)
    ax3.set_ylabel('Force (N)', fontsize=11)
    ax3.set_title('Combined View: Individual (faded) + Aggregated (bold)', fontsize=12, fontweight='bold')
    ax3.legend(loc='best', fontsize=9)
    ax3.grid(True, alpha=0.4)
    ax3.grid(True, which='minor', alpha=0.3)
    ax3.minorticks_on()
    ax3.set_xlim([all_exp.min(), all_exp.max()])
    plt.tight_layout()

    output3 = OUTPUT_DIR + "demo_combined.png"
    fig3.savefig(output3, dpi=300, bbox_inches='tight')
    print(f"     Saved: {output3}")

    print("\n" + "=" * 60)
    print("Demo completed successfully!")
    print("\nGenerated plots:")
    print(f"  1. {output1}")
    print(f"  2. {output2}")
    print(f"  3. {output3}")
    print("\nTo run the full GUI application with aggregation, execute:")
    print("  python3 strain_gauge_aggregator.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
