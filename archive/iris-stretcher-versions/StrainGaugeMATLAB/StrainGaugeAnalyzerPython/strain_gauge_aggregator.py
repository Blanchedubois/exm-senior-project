"""
Strain Gauge Aggregator - Python GUI Application with Time Soak Aggregation
Converts MATLAB AllowAnySheetNameMakimaNPCHIP functionality to Python

Reads Excel files, aggregates data by soak time, and creates parametric plots
with optional aggregation of replicates.
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
        """Extract '<number> min' from sheet names like '8 min CaSO₄ test 7'"""
        match = re.search(r'(\d+)\s*min', self.name, re.IGNORECASE)
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

    @staticmethod
    def interp_makima_with_pchip_fallback(x: np.ndarray, y: np.ndarray,
                                          x_query: np.ndarray) -> np.ndarray:
        """
        Interpolate with Akima (MAKIMA); if non-decreasing is violated on query grid,
        re-compute with PCHIP (shape-preserving).
        """
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

    @staticmethod
    def compute_median_step(voltage: np.ndarray) -> float:
        """Compute median of positive voltage steps"""
        diffs = np.diff(voltage)
        positive_diffs = diffs[diffs > 0]
        if len(positive_diffs) > 0:
            return np.median(positive_diffs)
        return np.nan


class AggregatedStrainGaugeAnalyzer:
    """Main application class with aggregation capabilities"""

    def __init__(self, root):
        self.root = root
        self.root.title("Strain Gauge Aggregator - Time Soak Analysis")
        self.root.geometry("1300x850")

        # Data storage
        self.force_data = None
        self.force_voltage = None
        self.expansion_data_list: List[StrainGaugeData] = []
        self.current_file = None
        self.voltage_grid = None
        self.force_interpolated = None

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
        main_frame.columnconfigure(0, weight=3)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)

        # Title
        title_label = ttk.Label(main_frame, text="Hydrogel Force vs Expansion - Aggregated Analysis",
                               font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=2, pady=10)

        # Control panel
        control_frame = ttk.LabelFrame(main_frame, text="File Controls", padding="10")
        control_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=10, padx=(0, 5))

        # File selection button
        self.upload_button = ttk.Button(control_frame, text="Upload Excel File",
                                       command=self.load_file)
        self.upload_button.grid(row=0, column=0, padx=5)

        # File label
        self.file_label = ttk.Label(control_frame, text="No file loaded",
                                    foreground="gray")
        self.file_label.grid(row=0, column=1, padx=5)

        # Plot button
        self.plot_button = ttk.Button(control_frame, text="Generate Force vs Exp",
                                     command=self.generate_plot, state='disabled')
        self.plot_button.grid(row=0, column=2, padx=5)

        # Voltage plot button
        self.voltage_plot_button = ttk.Button(control_frame, text="Voltage vs Exp Plot",
                                             command=self.generate_voltage_plot, state='disabled')
        self.voltage_plot_button.grid(row=0, column=3, padx=5)

        # Export button
        self.export_button = ttk.Button(control_frame, text="Export Plot",
                                       command=self.export_plot, state='disabled')
        self.export_button.grid(row=0, column=4, padx=5)

        # Options panel
        options_frame = ttk.LabelFrame(main_frame, text="Display Options", padding="10")
        options_frame.grid(row=1, column=1, rowspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10, padx=(5, 0))

        # Display mode
        ttk.Label(options_frame, text="Display Mode:", font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky=tk.W, pady=(0, 5))

        self.display_mode = tk.StringVar(value="both")
        ttk.Radiobutton(options_frame, text="Individual traces only",
                       variable=self.display_mode, value="individual").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Radiobutton(options_frame, text="Aggregated by time soak",
                       variable=self.display_mode, value="aggregated").grid(row=2, column=0, sticky=tk.W, pady=2)
        ttk.Radiobutton(options_frame, text="Both (individual + aggregated)",
                       variable=self.display_mode, value="both").grid(row=3, column=0, sticky=tk.W, pady=2)

        ttk.Separator(options_frame, orient='horizontal').grid(row=4, column=0, sticky=(tk.W, tk.E), pady=10)

        # Aggregation method
        ttk.Label(options_frame, text="Aggregation Method:", font=('Arial', 10, 'bold')).grid(row=5, column=0, sticky=tk.W, pady=(0, 5))

        self.agg_method = tk.StringVar(value="mean")
        ttk.Radiobutton(options_frame, text="Mean",
                       variable=self.agg_method, value="mean").grid(row=6, column=0, sticky=tk.W, pady=2)
        ttk.Radiobutton(options_frame, text="Median",
                       variable=self.agg_method, value="median").grid(row=7, column=0, sticky=tk.W, pady=2)

        ttk.Separator(options_frame, orient='horizontal').grid(row=8, column=0, sticky=(tk.W, tk.E), pady=10)

        # Error bands
        ttk.Label(options_frame, text="Error Visualization:", font=('Arial', 10, 'bold')).grid(row=9, column=0, sticky=tk.W, pady=(0, 5))

        self.show_error = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Show error bands",
                       variable=self.show_error).grid(row=10, column=0, sticky=tk.W, pady=2)

        self.error_type = tk.StringVar(value="std")
        ttk.Radiobutton(options_frame, text="Standard deviation",
                       variable=self.error_type, value="std").grid(row=11, column=0, sticky=tk.W, pady=2, padx=(20, 0))
        ttk.Radiobutton(options_frame, text="Standard error (SEM)",
                       variable=self.error_type, value="sem").grid(row=12, column=0, sticky=tk.W, pady=2, padx=(20, 0))
        ttk.Radiobutton(options_frame, text="Min/Max range",
                       variable=self.error_type, value="minmax").grid(row=13, column=0, sticky=tk.W, pady=2, padx=(20, 0))

        ttk.Separator(options_frame, orient='horizontal').grid(row=14, column=0, sticky=(tk.W, tk.E), pady=10)

        # Individual trace options
        ttk.Label(options_frame, text="Individual Traces:", font=('Arial', 10, 'bold')).grid(row=15, column=0, sticky=tk.W, pady=(0, 5))

        self.individual_alpha = tk.DoubleVar(value=0.3)
        ttk.Label(options_frame, text="Opacity:").grid(row=16, column=0, sticky=tk.W, pady=2)
        ttk.Scale(options_frame, from_=0.1, to=1.0, variable=self.individual_alpha,
                 orient='horizontal').grid(row=17, column=0, sticky=(tk.W, tk.E), pady=2)

        ttk.Separator(options_frame, orient='horizontal').grid(row=18, column=0, sticky=(tk.W, tk.E), pady=10)

        # Data summary
        self.summary_text = tk.Text(options_frame, height=8, width=30, wrap=tk.WORD, font=('Courier', 9))
        self.summary_text.grid(row=19, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        self.summary_text.insert('1.0', "Load a file to see summary...")
        self.summary_text.config(state='disabled')

        # Plot frame
        plot_frame = ttk.LabelFrame(main_frame, text="Plot", padding="10")
        plot_frame.grid(row=2, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5))
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
        self.status_label.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(5, 0))

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
            self.voltage_plot_button.config(state='normal')

            # Update summary
            self.update_summary()

            self.status_label.config(text=f"Loaded {len(self.expansion_data_list)} expansion sheets")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load file:\n{str(e)}")
            self.status_label.config(text="Error loading file")

    def update_summary(self):
        """Update the data summary text box"""
        if not self.expansion_data_list:
            return

        # Group by time soak
        groups = {}
        for data in self.expansion_data_list:
            key = data.group_key
            if key not in groups:
                groups[key] = []
            groups[key].append(data.name)

        summary = "DATA SUMMARY\n"
        summary += "=" * 30 + "\n\n"
        summary += f"Total sheets: {len(self.expansion_data_list)}\n"
        summary += f"Time soak groups: {len(groups)}\n\n"

        for group_key in sorted(groups.keys()):
            sheets = groups[group_key]
            summary += f"{group_key}:\n"
            summary += f"  Replicates: {len(sheets)}\n"
            for sheet in sheets:
                summary += f"  - {sheet}\n"
            summary += "\n"

        self.summary_text.config(state='normal')
        self.summary_text.delete('1.0', tk.END)
        self.summary_text.insert('1.0', summary)
        self.summary_text.config(state='disabled')

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
            n_intervals = int(np.ceil(n_intervals / 10) * 10)
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
                exp_interp[exp_interp < 0] = 0
                data.expansion_interpolated = exp_interp

            self.status_label.config(text="Data processed successfully")
            return True

        except Exception as e:
            messagebox.showerror("Error", f"Failed to process data:\n{str(e)}")
            self.status_label.config(text="Error processing data")
            return False

    def aggregate_by_group(self) -> Dict:
        """Aggregate expansion data by time soak groups"""
        groups = {}

        for data in self.expansion_data_list:
            key = data.group_key
            if key not in groups:
                groups[key] = {
                    'expansions': [],
                    'data_objects': [],
                    'minutes': data.minutes
                }
            groups[key]['expansions'].append(data.expansion_interpolated)
            groups[key]['data_objects'].append(data)

        # Compute aggregated statistics for each group
        aggregated = {}
        agg_func = np.mean if self.agg_method.get() == "mean" else np.median

        for key, group_data in groups.items():
            expansions = np.array(group_data['expansions'])  # shape: (n_replicates, n_points)

            aggregated[key] = {
                'mean': np.mean(expansions, axis=0),
                'median': np.median(expansions, axis=0),
                'std': np.std(expansions, axis=0, ddof=1 if len(expansions) > 1 else 0),
                'sem': np.std(expansions, axis=0, ddof=1 if len(expansions) > 1 else 0) / np.sqrt(len(expansions)),
                'min': np.min(expansions, axis=0),
                'max': np.max(expansions, axis=0),
                'n': len(expansions),
                'minutes': group_data['minutes'],
                'data_objects': group_data['data_objects']
            }

        return aggregated

    def generate_plot(self):
        """Generate the parametric plot with aggregation options"""
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

            display_mode = self.display_mode.get()
            show_individual = display_mode in ["individual", "both"]
            show_aggregated = display_mode in ["aggregated", "both"]

            # Get unique group keys for color assignment
            group_keys = [data.group_key for data in self.expansion_data_list]
            unique_keys = sorted(set(group_keys), key=lambda x: group_keys.index(x))

            # Create color map
            cmap = plt.cm.tab10
            group_colors = {key: cmap(i % 10) for i, key in enumerate(unique_keys)}

            # Markers
            markers = ['+', 'd', 'x', '^', 'v', '>', '<', 'p', 'h', '*', 'o', 's', '.']
            filled_markers = ['o', 'd', 's', '^', 'v', '>', '<', 'p', 'h']

            # Plot individual traces
            if show_individual:
                seen_count = {}
                individual_alpha = self.individual_alpha.get() if show_aggregated else 1.0

                for data in self.expansion_data_list:
                    group_key = data.group_key

                    if group_key not in seen_count:
                        seen_count[group_key] = 0
                    seen_count[group_key] += 1
                    rep_idx = seen_count[group_key]

                    base_color = np.array(group_colors[group_key][:3])

                    # Shade variation
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

                    label = data.name if not show_aggregated else None

                    if marker in filled_markers:
                        self.ax.plot(data.expansion_interpolated, self.force_interpolated,
                                   marker=marker, linestyle='', markersize=4, linewidth=1,
                                   color=color, markerfacecolor=color, markeredgecolor=color,
                                   alpha=individual_alpha, label=label)
                    else:
                        self.ax.plot(data.expansion_interpolated, self.force_interpolated,
                                   marker=marker, linestyle='', markersize=4, linewidth=1,
                                   color=color, markeredgecolor=color,
                                   alpha=individual_alpha, label=label)

            # Plot aggregated traces
            if show_aggregated:
                aggregated = self.aggregate_by_group()
                agg_method = self.agg_method.get()

                for group_key in sorted(aggregated.keys()):
                    agg_data = aggregated[group_key]
                    base_color = group_colors[group_key]

                    # Use mean or median
                    expansion_agg = agg_data[agg_method]

                    # Calculate standard deviation at maximum expansion
                    max_idx = np.argmax(expansion_agg)
                    std_at_max = agg_data['std'][max_idx]

                    # Plot main line
                    label = f"{group_key} (n={agg_data['n']}, {agg_method}, SD={std_at_max:.3f})"
                    self.ax.plot(expansion_agg, self.force_interpolated,
                               linestyle='-', linewidth=2.5, color=base_color,
                               marker='o', markersize=6, markerfacecolor=base_color,
                               markeredgecolor='white', markeredgewidth=0.5,
                               label=label, zorder=10)

                    # Add error bands
                    if self.show_error.get() and agg_data['n'] > 1:
                        error_type = self.error_type.get()

                        if error_type == "std":
                            lower = expansion_agg - agg_data['std']
                            upper = expansion_agg + agg_data['std']
                            error_label = "± SD"
                        elif error_type == "sem":
                            lower = expansion_agg - agg_data['sem']
                            upper = expansion_agg + agg_data['sem']
                            error_label = "± SEM"
                        else:  # minmax
                            lower = agg_data['min']
                            upper = agg_data['max']
                            error_label = "min/max"

                        # Add label for each soak time's shaded region
                        band_label = f"{group_key} {error_label}"

                        self.ax.fill_betweenx(self.force_interpolated, lower, upper,
                                             color=base_color, alpha=0.2, zorder=5, label=band_label)

            # Format plot
            title = 'Hydrogel Force vs Expansion'
            if show_aggregated:
                title += f' ({self.agg_method.get().capitalize()} Aggregation)'

            self.ax.set_xlabel('Expansion (units)', fontsize=11)
            self.ax.set_ylabel('Force (N)', fontsize=11)
            self.ax.set_title(title, fontsize=12, fontweight='bold')
            self.ax.legend(loc='best', fontsize=8, framealpha=0.9)
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
            import traceback
            traceback.print_exc()

    def generate_voltage_plot(self):
        """Generate Voltage vs Expansion plot with aggregation by soak time"""
        if self.force_data is None:
            messagebox.showwarning("Warning", "Please load a file first")
            return

        # Process data
        if not self.process_data():
            return

        try:
            self.status_label.config(text="Generating voltage plot...")
            self.root.update()

            # Clear previous plot
            self.ax.clear()

            # Get unique group keys for color assignment
            group_keys = [data.group_key for data in self.expansion_data_list]
            unique_keys = sorted(set(group_keys), key=lambda x: group_keys.index(x))

            # Create color map
            cmap = plt.cm.tab10
            group_colors = {key: cmap(i % 10) for i, key in enumerate(unique_keys)}

            # Aggregate by group
            aggregated = self.aggregate_by_group()
            agg_method = self.agg_method.get()

            # Plot aggregated traces with standard deviation
            for group_key in sorted(aggregated.keys()):
                agg_data = aggregated[group_key]
                base_color = group_colors[group_key]

                # Use mean or median
                expansion_agg = agg_data[agg_method]

                # Calculate standard deviation at maximum expansion
                max_idx = np.argmax(expansion_agg)
                std_at_max = agg_data['std'][max_idx]

                # Plot main line (Voltage vs Expansion)
                label = f"{group_key} (n={agg_data['n']}, {agg_method}, SD={std_at_max:.3f})"
                self.ax.plot(self.voltage_grid, expansion_agg,
                           linestyle='-', linewidth=2.5, color=base_color,
                           marker='o', markersize=6, markerfacecolor=base_color,
                           markeredgecolor='white', markeredgewidth=0.5,
                           label=label, zorder=10)

                # Add error bands
                if self.show_error.get() and agg_data['n'] > 1:
                    error_type = self.error_type.get()

                    if error_type == "std":
                        lower = expansion_agg - agg_data['std']
                        upper = expansion_agg + agg_data['std']
                        error_label = "± SD"
                    elif error_type == "sem":
                        lower = expansion_agg - agg_data['sem']
                        upper = expansion_agg + agg_data['sem']
                        error_label = "± SEM"
                    else:  # minmax
                        lower = agg_data['min']
                        upper = agg_data['max']
                        error_label = "min/max"

                    # Add label for each soak time's shaded region
                    band_label = f"{group_key} {error_label}"

                    self.ax.fill_between(self.voltage_grid, lower, upper,
                                        color=base_color, alpha=0.2, zorder=5, label=band_label)

            # Format plot
            title = f'ADC Voltage vs Expansion by Soak Time ({self.agg_method.get().capitalize()} Aggregation)'

            self.ax.set_xlabel('ADC Voltage (V)', fontsize=11, fontweight='bold')
            self.ax.set_ylabel('Expansion (units)', fontsize=11, fontweight='bold')
            self.ax.set_title(title, fontsize=12, fontweight='bold')
            self.ax.legend(loc='best', fontsize=8, framealpha=0.9)
            self.ax.grid(True, alpha=0.4)
            self.ax.grid(True, which='minor', alpha=0.3)
            self.ax.minorticks_on()

            # Refresh canvas
            self.figure.tight_layout()
            self.canvas.draw()

            self.export_button.config(state='normal')
            self.status_label.config(text="Voltage plot generated successfully")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate voltage plot:\n{str(e)}")
            self.status_label.config(text="Error generating voltage plot")
            import traceback
            traceback.print_exc()

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
    app = AggregatedStrainGaugeAnalyzer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
