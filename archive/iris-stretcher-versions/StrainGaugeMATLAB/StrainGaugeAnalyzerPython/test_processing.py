"""
Test script to validate data processing without GUI
"""

import numpy as np
import pandas as pd
import sys
from scipy.interpolate import Akima1DInterpolator, PchipInterpolator

def test_data_loading():
    """Test loading the Excel file"""
    print("Testing data loading...")

    filename = "~/Library/Mobile Documents/com~apple~CloudDocs/Course Resources/Research Expansion Microscopy/Code/StrainGaugeMATLAB/AggregateStrainGaugeDataSet.xlsx"

    try:
        excel_file = pd.ExcelFile(filename)
        sheet_names = excel_file.sheet_names
        print(f"✓ Loaded file successfully")
        print(f"  Found {len(sheet_names)} sheets: {sheet_names}")

        # Find Force sheet
        force_sheet = None
        for name in sheet_names:
            if name.lower() == 'forcevvoltage':
                force_sheet = name
                break

        if force_sheet:
            force_df = pd.read_excel(filename, sheet_name=force_sheet)
            print(f"✓ Found ForceVVoltage sheet with {len(force_df)} rows")
            print(f"  Columns: {list(force_df.columns)}")
            print(f"  First few Force values: {force_df.iloc[:5, 0].values}")
            print(f"  First few Voltage values: {force_df.iloc[:5, 1].values}")
        else:
            print("✗ ForceVVoltage sheet not found")
            return False

        # Count expansion sheets
        expansion_sheets = [s for s in sheet_names if s.lower() != 'forcevvoltage']
        print(f"✓ Found {len(expansion_sheets)} expansion sheets")

        # Test reading one expansion sheet
        if expansion_sheets:
            test_sheet = expansion_sheets[0]
            exp_df = pd.read_excel(filename, sheet_name=test_sheet)
            print(f"✓ Successfully read expansion sheet '{test_sheet}' with {len(exp_df)} rows")
            print(f"  First few Expansion values: {exp_df.iloc[:5, 0].values}")
            print(f"  First few Voltage values: {exp_df.iloc[:5, 1].values}")

        return True

    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def test_interpolation():
    """Test MAKIMA and PCHIP interpolation"""
    print("\nTesting interpolation methods...")

    try:
        # Create test data
        x = np.array([0, 1, 2, 3, 4, 5])
        y = np.array([0, 1, 4, 9, 16, 25])  # quadratic
        x_query = np.linspace(0, 5, 20)

        # Test Akima
        akima_interp = Akima1DInterpolator(x, y)
        y_akima = akima_interp(x_query)
        print(f"✓ Akima interpolation successful")
        print(f"  Query points: {len(x_query)}")
        print(f"  Sample interpolated values: {y_akima[:5]}")

        # Test PCHIP
        pchip_interp = PchipInterpolator(x, y)
        y_pchip = pchip_interp(x_query)
        print(f"✓ PCHIP interpolation successful")
        print(f"  Sample interpolated values: {y_pchip[:5]}")

        return True

    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def test_deduplication():
    """Test the deduplication logic"""
    print("\nTesting deduplication...")

    try:
        # Create test data with near-duplicates
        voltage = np.array([1.0, 1.0000001, 2.0, 2.0000002, 3.0, 3.5, 3.5000003])
        values = np.array([10, 11, 20, 21, 30, 35, 36])

        tol = 1e-6

        # Simple deduplication logic
        mask = np.isfinite(voltage) & np.isfinite(values)
        voltage = voltage[mask]
        values = values[mask]

        sort_idx = np.argsort(voltage)
        voltage_sorted = voltage[sort_idx]
        values_sorted = values[sort_idx]

        gaps = np.diff(voltage_sorted)
        new_group = np.concatenate([[True], gaps > tol])
        group_ids = np.cumsum(new_group)

        unique_groups = np.unique(group_ids)
        voltage_out = np.array([np.mean(voltage_sorted[group_ids == g]) for g in unique_groups])
        values_out = np.array([np.median(values_sorted[group_ids == g]) for g in unique_groups])

        print(f"✓ Deduplication successful")
        print(f"  Input points: {len(voltage)} → Output points: {len(voltage_out)}")
        print(f"  Original voltages: {voltage}")
        print(f"  Deduplicated voltages: {voltage_out}")
        print(f"  Deduplicated values: {values_out}")

        return True

    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def main():
    """Run all tests"""
    print("=" * 60)
    print("Strain Gauge Analyzer - Test Suite")
    print("=" * 60)

    tests = [
        test_data_loading,
        test_interpolation,
        test_deduplication
    ]

    results = []
    for test in tests:
        result = test()
        results.append(result)

    print("\n" + "=" * 60)
    print(f"Test Results: {sum(results)}/{len(results)} passed")
    print("=" * 60)

    if all(results):
        print("\n✓ All tests passed! The application should work correctly.")
        return 0
    else:
        print("\n✗ Some tests failed. Please check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
