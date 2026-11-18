% File: load_and_interp.m
% ------------------------------------------
% 1) Pick your file
[fn, path] = uigetfile({'*.xlsx;*.xls;*.csv','Data Files (*.xlsx,*.xls,*.csv)'}, ...
                       'Select StraingGaugeMATLABtest.xlsx');
if isequal(fn,0)
    error('No file selected.');
end
filename = fullfile(path,fn);

% 2) Read your sheet into a table
T = readtable(filename, 'Sheet', 'ForceVVoltage');

% assume the first column is force, second is voltage regardless of header names
Fdata = T{:,1};   % force measurements
Vdata = T{:,2};   % voltage measurements

% 3) Sort ascending by voltage
[ Vdata, I ] = sort(Vdata);
Fdata       = Fdata(I);

% 4) Ask for your desired interval
Vmin = min(Vdata);
Vmax = max(Vdata);
fprintf('Measured voltage range: [%.6f, %.6f] V\n', Vmin, Vmax);
Vstart  = input(sprintf('  Start voltage (≥ %.6f): ', Vmin));
Vend    = input(sprintf('    End voltage (≤ %.6f): ', Vmax));
nPoints = input(' Number of interp points: ');
if ~(Vstart >= Vmin && Vend <= Vmax && Vend > Vstart)
    error('Invalid interval: must satisfy %.6f ≤ Vstart < Vend ≤ %.6f', Vmin, Vmax);
end

% 5) Build query vector and interpolate
Vin     = linspace(Vstart, Vend, nPoints).';
Finterp = interpForceQuad(Vdata, Fdata, Vin);

% 6) Plot
figure;
plot(Vdata, Fdata, 'o','MarkerFaceColor','k','DisplayName','Measured'); hold on;
plot(Vin,    Finterp, 'b','LineWidth',1.5,'DisplayName','Interpolated');
xlabel('Voltage (V)');
ylabel('Force (N)');
title(sprintf('Force vs. Voltage\nInterpolated over [%.6f, %.6f] V (%d points)', ...
              Vstart, Vend, nPoints));
legend('Location','Best');
grid on;