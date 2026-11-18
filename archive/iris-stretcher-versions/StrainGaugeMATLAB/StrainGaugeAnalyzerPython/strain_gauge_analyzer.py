"""
Strain Gauge Analyzer - Python GUI Application
Converts MATLAB MakimaNPCHIP functionality to Python with GUI

Reads Excel files with Force and Expansion data, performs interpolation,
and creates parametric plots of Force vs Expansion.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from scipy.interpolate import Akima1DInterpolator, PchipInterpolator
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import re
from typing import Tuple, Callable, List, Dict


class StrainGaugeData:
    """Container for strain gauge data from one sheet"""
    def __init__(self, name: str, expansion_raw: np.ndarray, voltage_raw: np.ndarray):
        self.name = name
        self.expansion_raw = expansion_raw
        self.voltage_raw = voltage_raw
        self.expansion = None
        self.voltage = None
        self.expansion_interpolated = None
        self.minutes = self._parse_soak_minutes()
        self.group_key = self._create_group_key()

    def _parse_soak_minutes(self) -> float:
        """Extract leading '<number> min' from sheet names like '8 min CaSO₄ test 7'"""
        match = re.match(r'^\s*(\d+)\s*min', self.name, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return np.nan

    def _create_group_key(self) -> str:
        """Create grouping key for color assignment"""
        if np.isfinite(self.minutes):
            return f"{int(self.minutes)} min"
        else:
            return f"sheet: {self.name}"


class DataProcessor:
    """Handles data processing operations"""

    @staticmethod
    def dedupe_tolerance(voltage: np.ndarray, values: np.ndarray,
                         tol: float = 1e-6, agg_func: Callable = np.median) -> Tuple[np.ndarray, np.ndarray]:
        """
        Merge consecutive voltages within tolerance into one bin.
        Voltage becomes the bin mean; values aggregated by agg_func.
        """
        # Remove non-finite values
        mask = np.isfinite(voltage) & np.isfinite(values)
        voltage = voltage[mask]
        values = values[mask]

        if len(voltage) <= 1:
            return voltage, values

        # Sort by voltage
        sort_idx = np.argsort(voltage)
        voltage_sorted = voltage[sort_idx]
        values_sorted = values[sort_idx]

        # Define new group when gap exceeds tolerance
        gaps = np.diff(voltage_sorted)
        new_group = np.concatenate([[True], gaps > tol])
        group_ids = np.cumsum(new_group)

        # Aggregate by group
        unique_groups = np.unique(group_ids)
        voltage_out = np.array([np.mean(voltage_sorted[group_ids == g]) for g in unique_groups])
        values_out = np.array([agg_func(values_sorted[group_ids == g]) for g in unique_groups])

        # Ensure strictly increasing
        if np.any(np.diff(voltage_out) <= 0):
            voltage_out = voltage_out + np.arange(len(voltage_out)) * np.finfo(float).eps * np.max(voltage_out)

        return voltage_out, values_out

    @staticmethod
    def interp_makima_with_pchip_fallback(x: np.ndarray, y: np.ndarray,
                                          x_query: np.ndarray) -> np.ndarray:
        """
        Interpolate with Akima (MAKIMA); if non-decreasing is violated on query grid,
        re-compute with PCHIP (shape-preserving).
        """
        try:
            # Try Akima interpolation (MATLAB's makima equivalent)
            interpolator = Akima1DInterpolator(x, y)
            y_query = interpolator(x_query)

            # Check if result is monotone
            if np.any(np.diff(y_query) < 0):
                # Fallback to PCHIP
                interpolator = PchipInterpolator(x, y)
                y_query = interpolator(x_query)
        except Exception:
            # If Akima fails, use PCHIP directly
            interpolator = PchipInterpolator(x, y)
            y_query = interpolator(x_query)

        return y_query

    @staticmethod
    def compute_median_step(voltage: np.ndarray) -> float:
        """Compute median of positive voltage steps"""
        diffs = np.diff(voltage)
        positive_diffs = diffs[diffs > 0]
        if len(positive_diffs) > 0:
            return np.median(positive_diffs)
        return np.nan


class StrainGaugeAnalyzer:
    """Main application class"""

    def __init__(self, root):
        self.root = root
        self.root.title("Strain Gauge Analyzer")
        self.root.geometry("1200x800")

        # Data storage
        self.force_data = None
        self.force_voltage = None
        self.expansion_data_list: List[StrainGaugeData] = []
        self.current_file = None

        # Setup UI
        self.setup_ui()

    def setup_ui(self):
        """Create the user interface"""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(2, weight=1)

        # Title
        title_label = ttk.Label(main_frame, text="Hydrogel Force vs Expansion Analyzer",
                               font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, pady=10)

        # Control panel
        control_frame = ttk.LabelFrame(main_frame, text="Controls", padding="10")
        control_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=10)

        # File selection button
        self.upload_button = ttk.Button(control_frame, text="Upload Excel File",
                                       command=self.load_file)
        self.upload_button.grid(row=0, column=0, padx=5)

        # File label
        self.file_label = ttk.Label(control_frame, text="No file loaded",
                                    foreground="gray")
        self.file_label.grid(row=0, column=1, padx=5)

        # Plot button
        self.plot_button = ttk.Button(control_frame, text="Generate Plot",
                                     command=self.generate_plot, state='disabled')
        self.plot_button.grid(row=0, column=2, padx=5)

        # Export button
        self.export_button = ttk.Button(control_frame, text="Export Plot",
                                       command=self.export_plot, state='disabled')
        self.export_button.grid(row=0, column=3, padx=5)

        # Plot frame
        plot_frame = ttk.LabelFrame(main_frame, text="Plot", padding="10")
        plot_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        plot_frame.columnconfigure(0, weight=1)
        plot_frame.rowconfigure(0, weight=1)

        # Create matplotlib figure
        self.figure = Figure(figsize=(10, 6), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel('Expansion (units)')
        self.ax.set_ylabel('Force (N)')
        self.ax.set_title('Hydrogel Force vs Expansion')
        self.ax.grid(True, alpha=0.4)
        self.ax.grid(True, which='minor', alpha=0.3)

        # Canvas for matplotlib
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Toolbar
        toolbar_frame = ttk.Frame(plot_frame)
        toolbar_frame.grid(row=1, column=0, sticky=(tk.W, tk.E))
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame)
        self.toolbar.update()

        # Status bar
        self.status_label = ttk.Label(main_frame, text="Ready", relief=tk.SUNKEN)
        self.status_label.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(5, 0))

    def load_file(self):
        """Load Excel file and process data"""
        filename = filedialog.askopenfilename(
            title="Select Excel File",
            filetypes=[("Excel Files", "*.xlsx *.xls"), ("All Files", "*.*")]
        )

        if not filename:
            return

        try:
            self.status_label.config(text="Loading file...")
            self.root.update()

            # Read all sheets
            excel_file = pd.ExcelFile(filename)
            sheet_names = excel_file.sheet_names

            # Find Force sheet
            force_sheet = None
            for name in sheet_names:
                if name.lower() == 'forcevvoltage':
                    force_sheet = name
                    break

            if force_sheet is None:
                messagebox.showerror("Error", "Could not find 'ForceVVoltage' sheet in the Excel file.")
                self.status_label.config(text="Error: Missing ForceVVoltage sheet")
                return

            # Read Force data
            force_df = pd.read_excel(filename, sheet_name=force_sheet)
            self.force_data = force_df.iloc[:, 0].values
            self.force_voltage = force_df.iloc[:, 1].values

            # Read expansion sheets (all except Force sheet)
            self.expansion_data_list = []
            for sheet_name in sheet_names:
                if sheet_name.lower() != 'forcevvoltage':
                    exp_df = pd.read_excel(filename, sheet_name=sheet_name)
                    expansion = exp_df.iloc[:, 0].values
                    voltage = exp_df.iloc[:, 1].values
                    self.expansion_data_list.append(
                        StrainGaugeData(sheet_name, expansion, voltage)
                    )

            if not self.expansion_data_list:
                messagebox.showerror("Error", "No expansion sheets found (sheets other than ForceVVoltage).")
                self.status_label.config(text="Error: No expansion sheets")
                return

            self.current_file = filename
            self.file_label.config(text=f"Loaded: {filename.split('/')[-1]}", foreground="green")
            self.plot_button.config(state='normal')
            self.status_label.config(text=f"Loaded {len(self.expansion_data_list)} expansion sheets")

            messagebox.showinfo("Success",
                              f"Loaded file successfully!\n\n"
                              f"Force data points: {len(self.force_data)}\n"
                              f"Expansion sheets: {len(self.expansion_data_list)}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load file:\n{str(e)}")
            self.status_label.config(text="Error loading file")

    def process_data(self):
        """Process the loaded data"""
        try:
            self.status_label.config(text="Processing data...")
            self.root.update()

            tol = 1e-6

            # Dedupe Force data
            self.force_voltage, self.force_data = DataProcessor.dedupe_tolerance(
                self.force_voltage, self.force_data, tol, np.median
            )

            # Check strictly increasing
            if not np.all(np.diff(self.force_voltage) > 0):
                raise ValueError("Force voltages not strictly increasing after deduplication")

            # Dedupe expansion data
            for data in self.expansion_data_list:
                data.voltage, data.expansion = DataProcessor.dedupe_tolerance(
                    data.voltage_raw, data.expansion_raw, tol, np.median
                )

                if not np.all(np.diff(data.voltage) > 0):
                    raise ValueError(f"Voltages not strictly increasing in sheet '{data.name}'")

            # Find overlapping voltage range
            all_min_voltages = [self.force_voltage.min()] + [d.voltage.min() for d in self.expansion_data_list]
            all_max_voltages = [self.force_voltage.max()] + [d.voltage.max() for d in self.expansion_data_list]

            v_min = max(all_min_voltages)
            v_max = min(all_max_voltages)

            if v_min >= v_max:
                raise ValueError("No common overlap in voltage ranges")

            # Determine grid spacing
            steps = [DataProcessor.compute_median_step(self.force_voltage)]
            for data in self.expansion_data_list:
                steps.append(DataProcessor.compute_median_step(data.voltage))

            steps = [s for s in steps if np.isfinite(s) and s > 0]

            if len(steps) == 0:
                ds = (v_max - v_min) / 200
            else:
                ds = min(steps)

            n_intervals = max(50, int(np.ceil((v_max - v_min) / ds)))
            n_intervals = int(np.ceil(n_intervals / 10) * 10)  # Round to nearest 10
            n_points = n_intervals + 1

            # Build common voltage grid
            self.voltage_grid = np.linspace(v_min, v_max, n_points)

            # Interpolate Force
            self.force_interpolated = DataProcessor.interp_makima_with_pchip_fallback(
                self.force_voltage, self.force_data, self.voltage_grid
            )

            # Interpolate expansion data
            for data in self.expansion_data_list:
                exp_interp = DataProcessor.interp_makima_with_pchip_fallback(
                    data.voltage, data.expansion, self.voltage_grid
                )
                # Clamp negative expansions
                exp_interp[exp_interp < 0] = 0
                data.expansion_interpolated = exp_interp

            self.status_label.config(text="Data processed successfully")
            return True

        except Exception as e:
            messagebox.showerror("Error", f"Failed to process data:\n{str(e)}")
            self.status_label.config(text="Error processing data")
            return False

    def generate_plot(self):
        """Generate the parametric plot"""
        if self.force_data is None:
            messagebox.showwarning("Warning", "Please load a file first")
            return

        # Process data
        if not self.process_data():
            return

        try:
            self.status_label.config(text="Generating plot...")
            self.root.update()

            # Clear previous plot
            self.ax.clear()

            # Get unique group keys for color assignment
            group_keys = [data.group_key for data in self.expansion_data_list]
            unique_keys = sorted(set(group_keys), key=lambda x: group_keys.index(x))

            # Create color map
            cmap = plt.cm.tab10
            group_colors = {key: cmap(i % 10) for i, key in enumerate(unique_keys)}

            # Markers (mix of filled and outline)
            markers = ['+', 'd', 'x', '^', 'v', '>', '<', 'p', 'h', '*', 'o', 's', '.']
            filled_markers = ['o', 'd', 's', '^', 'v', '>', '<', 'p', 'h']

            # Track replicates per group
            seen_count = {}

            # Plot each expansion series
            for data in self.expansion_data_list:
                group_key = data.group_key

                # Get replicate index for this group
                if group_key not in seen_count:
                    seen_count[group_key] = 0
                seen_count[group_key] += 1
                rep_idx = seen_count[group_key]

                # Base color for this group
                base_color = np.array(group_colors[group_key][:3])

                # Vary shade per replicate
                alphas = [0.00, 0.15, 0.25, 0.10, 0.20, 0.30]
                alpha = alphas[(rep_idx - 1) % len(alphas)]

                if rep_idx % 2 == 1:
                    target = np.array([1, 1, 1])  # lighten
                else:
                    target = np.array([0, 0, 0])  # darken
                    alpha *= 0.8

                color = (1 - alpha) * base_color + alpha * target
                color = np.clip(color, 0, 1)

                # Select marker
                marker = markers[(rep_idx - 1) % len(markers)]

                # Plot
                if marker in filled_markers:
                    self.ax.plot(data.expansion_interpolated, self.force_interpolated,
                               marker=marker, linestyle='', markersize=5, linewidth=1.5,
                               color=color, markerfacecolor=color, markeredgecolor=color,
                               label=data.name)
                else:
                    self.ax.plot(data.expansion_interpolated, self.force_interpolated,
                               marker=marker, linestyle='', markersize=5, linewidth=1.5,
                               color=color, markeredgecolor=color,
                               label=data.name)

            # Format plot
            self.ax.set_xlabel('Expansion (units)', fontsize=11)
            self.ax.set_ylabel('Force (N)', fontsize=11)
            self.ax.set_title('Hydrogel Force vs Expansion (MAKIMA with PCHIP fallback)',
                            fontsize=12, fontweight='bold')
            self.ax.legend(loc='best', fontsize=8)
            self.ax.grid(True, alpha=0.4)
            self.ax.grid(True, which='minor', alpha=0.3)
            self.ax.minorticks_on()

            # Auto x-limits from data (capped at 4.5Ex max)
            all_expansions = np.concatenate([d.expansion_interpolated for d in self.expansion_data_list])
            self.ax.set_xlim([all_expansions.min(), min(all_expansions.max(), 4.5)])

            # Refresh canvas
            self.figure.tight_layout()
            self.canvas.draw()

            self.export_button.config(state='normal')
            self.status_label.config(text="Plot generated successfully")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate plot:\n{str(e)}")
            self.status_label.config(text="Error generating plot")

    def export_plot(self):
        """Export the current plot to a file"""
        if self.force_data is None:
            messagebox.showwarning("Warning", "No plot to export")
            return

        filename = filedialog.asksaveasfilename(
            title="Save Plot",
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("PDF Document", "*.pdf"),
                      ("SVG Image", "*.svg"), ("All Files", "*.*")]
        )

        if filename:
            try:
                self.figure.savefig(filename, dpi=300, bbox_inches='tight')
                messagebox.showinfo("Success", f"Plot saved to:\n{filename}")
                self.status_label.config(text=f"Plot exported to {filename.split('/')[-1]}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save plot:\n{str(e)}")


def main():
    """Main entry point"""
    root = tk.Tk()
    app = StrainGaugeAnalyzer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
