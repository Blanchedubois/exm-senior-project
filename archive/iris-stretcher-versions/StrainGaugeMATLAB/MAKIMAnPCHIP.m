% File: interp_parametric_double.m
% --------------------------------
% Parametric Force vs Expansion from multiple sheets.
% - Dedupe near-duplicate voltages (tolerance bins) per sheet
% - Interpolate with MAKIMA; fallback to PCHIP if non-monotone on grid
% - Clamp negative expansions
% - Plot Expansion (x) vs Force (y)

%% 1) Pick your Excel file
[fn, path] = uigetfile({'*.xlsx;*.xls','Excel Files (*.xlsx,*.xls)'}, ...
                       'Select your data file');
if isequal(fn,0), error('No file selected.'); end
filename = fullfile(path, fn);

%% 2) Read sheets
Tf  = readtable(filename, 'Sheet', 'ForceVVoltage');     % cols: Force, Voltage
T3  = readtable(filename, 'Sheet', 'ExpVVoltage3');      % cols: Expansion, Voltage
T5  = readtable(filename, 'Sheet', 'ExpVVoltage5');
T6  = readtable(filename, 'Sheet', 'ExpVVoltage6');
T7  = readtable(filename, 'Sheet', 'ExpVVoltage7');
T8  = readtable(filename, 'Sheet', 'ExpVVoltage8');
T9  = readtable(filename, 'Sheet', 'ExpVVoltage9');
T10 = readtable(filename, 'Sheet', 'ExpVVoltage10');
T11 = readtable(filename, 'Sheet', 'ExpVVoltage11');

% Extract raw columns (Y first, then V)
F_raw   = Tf{:,1};   Vf_raw  = Tf{:,2};
E3_raw  = T3{:,1};   V3_raw  = T3{:,2};
E5_raw  = T5{:,1};   V5_raw  = T5{:,2};
E6_raw  = T6{:,1};   V6_raw  = T6{:,2};
E7_raw  = T7{:,1};   V7_raw  = T7{:,2};
E8_raw  = T8{:,1};   V8_raw  = T8{:,2};
E9_raw  = T9{:,1};   V9_raw  = T9{:,2};
E10_raw = T10{:,1};  V10_raw = T10{:,2};
E11_raw = T11{:,1};  V11_raw = T11{:,2};

%% 3) Dedupe near-duplicate voltages (tolerance bucket), aggregate Y by median
tol = 1e-6;                          % merge voltages within 1e-6 V
agg = @median;                       % robust against outliers

[Vf,  F]  = dedupeTol(Vf_raw,  F_raw,  tol, agg);
[V3,  E3] = dedupeTol(V3_raw,  E3_raw, tol, agg);
[V5,  E5] = dedupeTol(V5_raw,  E5_raw, tol, agg);
[V6,  E6] = dedupeTol(V6_raw,  E6_raw, tol, agg);
[V7,  E7] = dedupeTol(V7_raw,  E7_raw, tol, agg);
[V8,  E8] = dedupeTol(V8_raw,  E8_raw, tol, agg);
[V9,  E9] = dedupeTol(V9_raw,  E9_raw, tol, agg);
[V10, E10]= dedupeTol(V10_raw, E10_raw,tol, agg);
[V11, E11]= dedupeTol(V11_raw, E11_raw,tol, agg);

% Sanity: require strictly increasing X after dedupe
assert(all(diff(Vf)  > 0), 'Force voltages not strictly increasing after dedupe.');
assert(all(diff(V3)  > 0) && all(diff(V5)  > 0) && all(diff(V6)  > 0) && ...
       all(diff(V7)  > 0) && all(diff(V8)  > 0) && all(diff(V9)  > 0) && ...
       all(diff(V10) > 0) && all(diff(V11) > 0), 'Some Expansion voltages not strictly increasing.');

%% 4) Overlapping voltage range
Vmin = max([min(Vf),  min(V3),  min(V5),  min(V6),  min(V7),  min(V8),  min(V9),  min(V10), min(V11)]);
Vmax = min([max(Vf),  max(V3),  max(V5),  max(V6),  max(V7),  max(V8),  max(V9),  max(V10), max(V11)]);
if ~(Vmin < Vmax), error('No common overlap in voltage ranges.'); end

%% 5) Grid spacing (robust): smallest median positive step across series
medStep = @(v) median(diff(v(diff(v)>0)));
steps = [medStep(Vf), medStep(V3), medStep(V5), medStep(V6), ...
         medStep(V7), medStep(V8), medStep(V9), medStep(V10), medStep(V11)];
steps = steps(isfinite(steps) & steps > 0);
if isempty(steps)
    ds = (Vmax - Vmin)/200;           % fallback spacing
else
    ds = min(steps);
end
nInt = max(50, ceil((Vmax - Vmin)/ds));   % ≥ 50 intervals
nInt = ceil(nInt/10)*10;                  % round up to nearest 10
nPts = nInt + 1;

%% 6) Build common voltage grid
Vgrid = linspace(Vmin, Vmax, nPts).';

%% 7) Interpolate with MAKIMA; fallback to PCHIP if non-monotone on Vgrid
Fq   = interp_makima_with_pchip_fallback(Vf,  F,  Vgrid);
E3q  = interp_makima_with_pchip_fallback(V3,  E3, Vgrid);
E5q  = interp_makima_with_pchip_fallback(V5,  E5, Vgrid);
E6q  = interp_makima_with_pchip_fallback(V6,  E6, Vgrid);
E7q  = interp_makima_with_pchip_fallback(V7,  E7, Vgrid);
E8q  = interp_makima_with_pchip_fallback(V8,  E8, Vgrid);
E9q  = interp_makima_with_pchip_fallback(V9,  E9, Vgrid);
E10q = interp_makima_with_pchip_fallback(V10, E10,Vgrid);
E11q = interp_makima_with_pchip_fallback(V11, E11,Vgrid);

%% 8) Clamp negative expansion (physical guardrail)
E3q(E3q   < 0) = 0;
E5q(E5q   < 0) = 0;
E6q(E6q   < 0) = 0;
E7q(E7q   < 0) = 0;
E8q(E8q   < 0) = 0;
E9q(E9q   < 0) = 0;
E10q(E10q < 0) = 0;
E11q(E11q < 0) = 0;

%% 9) Plot parametric curves: Expansion (x) vs Force (y)
c15 = [0.80, 0.40, 0.40];   % muted red
c12 = [0.40, 0.60, 0.80];   % muted blue
c8  = [0.40, 0.80, 0.60];   % muted green
c9  = [0.70, 0.50, 0.80];   % muted purple

figure('Color','w'); hold on;

plot(E3q, Fq, 'o', ...
     'Color', c15, 'MarkerFaceColor', c15, 'MarkerEdgeColor', c15, ...
     'LineWidth', 1.5, 'MarkerSize', 4, 'DisplayName','15 min CaSO₄ test 3');

plot(E5q, Fq, 'd', ...
     'Color', c12, 'MarkerFaceColor', c12, 'MarkerEdgeColor', c12, ...
     'LineWidth', 1.5, 'MarkerSize', 4, 'DisplayName','12 min CaSO₄ test 5');

plot(E6q, Fq, 'x', ...
     'Color', c12, 'MarkerEdgeColor', c12, ...
     'LineWidth', 1.5, 'MarkerSize', 4, 'DisplayName','12 min CaSO₄ test 6');

plot(E7q, Fq, 'd', ...
     'Color', c8,  'MarkerFaceColor', c8, 'MarkerEdgeColor', c8, ...
     'LineWidth', 1.5, 'MarkerSize', 4, 'DisplayName','8 min CaSO₄ test 7');

plot(E8q, Fq, 'x', ...
     'Color', c8,  'MarkerEdgeColor', c8, ...
     'LineWidth', 1.5, 'MarkerSize', 4, 'DisplayName','8 min CaSO₄ test 8');

% New series 9,10,11 — generic labels (rename if you have soak times)
plot(E9q,  Fq, 'd', ...
     'Color', c9,  'MarkerFaceColor', c9, 'MarkerEdgeColor', c9, ...
     'LineWidth', 1.5, 'MarkerSize', 4, 'DisplayName','10 min CaSO₄ test 2');

plot(E10q, Fq, 'x', ...
     'Color', c9, 'MarkerFaceColor', c9, 'MarkerEdgeColor', c9, ...
     'LineWidth', 1.5, 'MarkerSize', 4, 'DisplayName','10 min CaSO₄ test 3');

plot(E11q, Fq, '^', ...
     'Color', c9, 'MarkerFaceColor', c9, 'MarkerEdgeColor', c9, ...
     'LineWidth', 1.5, 'MarkerSize', 4, 'DisplayName','10 min CaSO₄ test 4');

xlabel('Expansion (units)');
ylabel('Force (N)');
title('Hydrogel Force vs Expansion by Soak Time (MAKIMA with PCHIP fallback)');
legend('Location','best');
grid on; grid minor;
ax = gca; ax.GridAlpha = 0.4; ax.MinorGridAlpha = 0.3;

% Auto x-limits from data (remove if you prefer fixed [1 5])
allE = [E3q; E5q; E6q; E7q; E8q; E9q; E10q; E11q];
xlim([min(allE), max(allE)]);

%% ---------------- Local functions ----------------

function [Vout, Yout] = dedupeTol(V, Y, tol, aggfun)
% Merge consecutive voltages within <= tol into one bin.
% V becomes the bin mean; Y aggregated by aggfun (e.g., @median or @mean).
    if nargin < 4 || isempty(aggfun), aggfun = @median; end
    V = V(:); Y = Y(:);
    m = isfinite(V) & isfinite(Y);
    V = V(m); Y = Y(m);
    [Vs, ord] = sort(V); Ys = Y(ord);
    n = numel(Vs);
    if n == 0
        Vout = Vs; Yout = Ys; return;
    elseif n == 1
        Vout = Vs; Yout = Ys; return;
    end
    % define new group when the gap exceeds tolerance
    g = [true; diff(Vs) > tol];
    gid = cumsum(g);
    Vout = accumarray(gid, Vs, [], @mean);
    Yout = accumarray(gid, Ys, [], aggfun);
    % ensure strictly increasing
    if any(diff(Vout) <= 0)
        % If ties remain (pathological), jitter by tiny eps
        Vout = Vout + (0:numel(Vout)-1)'*eps(max(Vout));
    end
end

function Yq = interp_makima_with_pchip_fallback(X, Y, Xq)
% Interpolate with makima; if non-decreasing is violated on the query grid,
% re-compute with pchip (shape-preserving).
    Yq = interp1(X, Y, Xq, 'makima');
    if any(diff(Yq) < 0)
        Yq = interp1(X, Y, Xq, 'pchip');
    end
end