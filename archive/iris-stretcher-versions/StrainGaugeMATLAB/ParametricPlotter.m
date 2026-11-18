% File: interp_parametric_double.m
% ------------------------------------------
% Reads three sheets from an Excel file:
%   • ForceVVoltage     (2 cols: Force, Voltage)
%   • ExpVVoltage1      (2 cols: Expansion1, Voltage)
%   • ExpVVoltage2      (2 cols: Expansion2, Voltage)
% Builds a common voltage grid, interpolates all three onto it,
% and plots two parametric curves: Expansion1 vs. Force and
% Expansion2 vs. Force on the same axes.

% 1) Pick your Excel file
[fn, path] = uigetfile({'*.xlsx;*.xls','Excel Files (*.xlsx,*.xls)'}, ...
                       'Select your data file');
if isequal(fn,0), error('No file selected.'); end
filename = fullfile(path, fn);

% 2) Load Force vs. Voltage
Tf  = readtable(filename, 'Sheet','ForceVVoltage');
F   = Tf{:,1};    % Force
Vf  = Tf{:,2};    % Voltage

% 3) Load Expansion1 vs. Voltage
T1  = readtable(filename, 'Sheet','ExpVVoltage1');
E1  = T1{:,1};    % Expansion1
V1  = T1{:,2};    % Voltage

% 4) Load Expansion2 vs. Voltage
T2  = readtable(filename, 'Sheet','ExpVVoltage2');
E2  = T2{:,1};    % Expansion2
V2  = T2{:,2};    % Voltage

% 5) Sort & drop duplicates
[Vf, If] = sort(Vf); F  = F(If);

[V1, I1s] = sort(V1); E1 = E1(I1s);
[ V1, iu1 ] = unique(V1, 'stable'); E1 = E1(iu1);

[V2, I2s] = sort(V2); E2 = E2(I2s);
[ V2, iu2 ] = unique(V2, 'stable'); E2 = E2(iu2);

% 6) Determine the overlapping voltage range
Vmin = max([min(Vf), min(V1), min(V2)]);
Vmax = min([max(Vf), max(V1), max(V2)]);
if Vmin >= Vmax
    error('No common overlap in voltage ranges.');
end

% 7) Compute a “nice” number of intervals
ds1 = median(diff(Vf));
ds2 = median(diff(V1));
ds3 = median(diff(V2));
ds  = min([ds1, ds2, ds3]);
nInt = ceil((Vmax - Vmin)/ds/10)*10;  % multiple of 10
nPts = nInt + 1;

% 8) Build the common voltage grid
Vgrid = linspace(Vmin, Vmax, nPts).';

% 9) Interpolate each dataset onto Vgrid
Fq  = interpForceQuad(Vf,  F,  Vgrid);           % quadratic for force
Eq1 = interp1(V1,   E1, Vgrid, 'pchip');          % PCHIP for expansion1
Eq2 = interp1(V2,   E2, Vgrid, 'pchip');          % PCHIP for expansion2

% clamp any negative artifacts
Eq1(Eq1 < 0) = 0;
Eq2(Eq2 < 0) = 0;


% 10) Plot both parametric curves
figure;
plot(Eq1, Fq, 'o', 'LineWidth',1.5, 'MarkerSize',4, ...
     'DisplayName','UnStretched Hydrogel Force (Unknown composition)'); hold on;
plot(Eq2, Fq, 's', 'LineWidth',1.5, 'MarkerSize',4, ...
     'DisplayName','Pre-Stretched 10 min soaking in calcium 20hrs DMEM Hydrogel Force');
xlabel('Expansion degree');
ylabel('Force (N)');
title('Parametric: Force vs. Expansion (Two Datasets)');
legend('Location','Best');
grid on;