% File: interp_parametric_double.m
% --------------------------------
% Reads seven sheets from an Excel file:
%   • ForceVVoltage     (2 cols: Force, Voltage)
%   • ExpVVoltage1      (2 cols: Expansion1, Voltage)
%   • ExpVVoltage2      (2 cols: Expansion2, Voltage)
%   • ExpVVoltage5      (2 cols: Expansion5, Voltage)
%   • ExpVVoltage6      (2 cols: Expansion6, Voltage)
%   • ExpVVoltage7      (2 cols: Expansion7, Voltage)
%   • ExpVVoltage8      (2 cols: Expansion8, Voltage)
% Builds a common voltage grid, interpolates all onto it,
% and plots six parametric curves: ExpansionX vs. Force.

% 1) Pick your Excel file
[fn, path] = uigetfile({'*.xlsx;*.xls','Excel Files (*.xlsx,*.xls)'}, ...
                       'Select your data file');
if isequal(fn,0)
    error('No file selected.');
end
filename = fullfile(path, fn);

% 2) Load Force vs. Voltage
Tf  = readtable(filename, 'Sheet', 'ForceVVoltage');
F   = Tf{:,1};    % Force (N)
Vf  = Tf{:,2};    % Voltage (V)

% 3) Load Expansion3
T1  = readtable(filename, 'Sheet', 'ExpVVoltage3');  E1 = T1{:,1};  V1 = T1{:,2};

% 4) Load Expansion5–8
T5  = readtable(filename, 'Sheet', 'ExpVVoltage5');  E5 = T5{:,1};  V5 = T5{:,2};
T6  = readtable(filename, 'Sheet', 'ExpVVoltage6');  E6 = T6{:,1};  V6 = T6{:,2};
T7  = readtable(filename, 'Sheet', 'ExpVVoltage7');  E7 = T7{:,1};  V7 = T7{:,2};
T8  = readtable(filename, 'Sheet', 'ExpVVoltage8');  E8 = T8{:,1};  V8 = T8{:,2};

% 5) Sort & drop duplicates for each dataset
[Vf, If]  = sort(Vf);  F  = F(If);

[V1, I1]  = sort(V1);  E1 = E1(I1);
[ V1, u1] = unique(V1,'stable'); E1 = E1(u1);

[V5, I5]  = sort(V5);  E5 = E5(I5);
[ V5, u5] = unique(V5,'stable'); E5 = E5(u5);

[V6, I6]  = sort(V6);  E6 = E6(I6);
[ V6, u6] = unique(V6,'stable'); E6 = E6(u6);

[V7, I7]  = sort(V7);  E7 = E7(I7);
[ V7, u7] = unique(V7,'stable'); E7 = E7(u7);

[V8, I8]  = sort(V8);  E8 = E8(I8);
[ V8, u8] = unique(V8,'stable'); E8 = E8(u8);

% 6) Determine the overlapping voltage range
Vmin = max([min(Vf), min(V1), min(V5), min(V6), min(V7), min(V8)]);
Vmax = min([max(Vf), max(V1), max(V5), max(V6), max(V7), max(V8)]);
if Vmin >= Vmax
    error('No common overlap in voltage ranges.');
end

% 7) Compute a “nice” number of intervals for the grid
dsF = median(diff(Vf));
ds1 = median(diff(V1));
ds5 = median(diff(V5));
ds6 = median(diff(V6));
ds7 = median(diff(V7));
ds8 = median(diff(V8));
ds  = min([dsF, ds1, ds5, ds6, ds7, ds8]);
nInt = ceil((Vmax - Vmin) / ds / 10) * 10;  % round up to nearest 10
nPts = nInt + 1;

% 8) Build the common voltage grid
Vgrid = linspace(Vmin, Vmax, nPts).';

% 9) Interpolate each dataset onto Vgrid
Fq  = interpForceQuad(Vf, F, Vgrid);        % quadratic interp for force
Eq1 = interpForceQuad(V1, E1, Vgrid);       % exp1      % exp2
Eq5 = interpForceQuad(V5, E5, Vgrid);       % exp5
Eq6 = interpForceQuad(V6, E6, Vgrid);       % exp6
Eq7 = interpForceQuad(V7, E7, Vgrid);       % exp7
Eq8 = interpForceQuad(V8, E8, Vgrid);       % exp8

% 10) Clamp any negative artifacts
Eq1(Eq1 < 0) = 0;
Eq5(Eq5 < 0) = 0;
Eq6(Eq6 < 0) = 0;
Eq7(Eq7 < 0) = 0;
Eq8(Eq8 < 0) = 0;

% 11) Plot all six parametric curves

% muted group colors (RGB)
c15 = [0.80, 0.40, 0.40];   % muted red
c12 = [0.40, 0.60, 0.80];   % muted blue
c8  = [0.40, 0.80, 0.60];   % muted green

figure; hold on;

plot(Eq1, Fq, 'o', ...
     'Color',          c15, ...
     'MarkerEdgeColor',c15, ...
     'MarkerFaceColor',c15, ...
     'LineWidth',1.5, 'MarkerSize',4, ...
     'DisplayName','15 min CaSO₄ test 3');

plot(Eq5, Fq, 'd', ...
     'Color',          c12, ...
     'MarkerEdgeColor',c12, ...
     'MarkerFaceColor',c12, ...
     'LineWidth',1.5, 'MarkerSize',4, ...
     'DisplayName','12 min CaSO₄ test 5');

plot(Eq6, Fq, 'x', ...
     'Color',          c12, ...
     'MarkerEdgeColor',c12, ...
     'MarkerFaceColor',c12, ...
     'LineWidth',1.5, 'MarkerSize',4, ...
     'DisplayName','12 min CaSO₄ test 6');

plot(Eq7, Fq, 'd', ...
     'Color',          c8,  ...
     'MarkerEdgeColor',c8,  ...
     'MarkerFaceColor',c8,  ...
     'LineWidth',1.5, 'MarkerSize',4, ...
     'DisplayName','8 min CaSO₄ test 7');

plot(Eq8, Fq, 'x', ...
     'Color',          c8,  ...
     'MarkerEdgeColor',c8,  ...
     'LineWidth',1.5, 'MarkerSize',4, ...
     'DisplayName','8 min CaSO₄ test 8');

xlabel('Expansion degree');
ylabel('Force (N)');
title('Hydrogel Force vs Expansion by Soak Time');
legend('Location','Best');
grid on; grid minor;
ax = gca;
ax.GridAlpha      = 0.4;
ax.MinorGridAlpha = 0.3;
xlim([1 5]);