% File: interp_parametric_double.m
% --------------------------------
% Force vs Expansion from multiple sheets.
% - Auto-detect sheets like "8 min CaSO₄ test 7"
% - Same color per "<minutes> min" group, different markers per replicate
% - MAKIMA with PCHIP fallback, dedupe near-duplicate voltages, clamp negatives

%% 1) Pick your Excel file
[fn, path] = uigetfile({'*.xlsx;*.xls','Excel Files (*.xlsx,*.xls)'}, ...
                       'Select your data file');
if isequal(fn,0), error('No file selected.'); end
filename = fullfile(path, fn);

%% 2) Read Force sheet (2 cols: Force, Voltage)
Tf = readtable(filename, 'Sheet', 'ForceVVoltage');
F_raw  = Tf{:,1};  Vf_raw = Tf{:,2};

%% 3) Find expansion sheets of the form "<number> min ..."
allSheets = sheetnames(filename);
isForce   = strcmpi(allSheets,'ForceVVoltage');
hasMin    = ~cellfun('isempty', regexpi(allSheets, '^\s*\d+\s*min')); % e.g., "8 min CaSO₄ test 7"
expSheets = allSheets(~isForce & hasMin);
if isempty(expSheets)
    error('No expansion sheets matching "<number> min ..." were found.');
end

% Read all expansion sheets (assume first col = Expansion, second = Voltage)
S = struct('name',{},'V_raw',{},'E_raw',{},'V',{},'E',{},'mins',{},'Eq',{});
for k = 1:numel(expSheets)
    T = readtable(filename, 'Sheet', expSheets{k});
    S(k).name  = expSheets{k};
    S(k).E_raw = T{:,1};
    S(k).V_raw = T{:,2};
    S(k).mins  = parseSoakMinutes(expSheets{k}); % e.g., "8" from "8 min CaSO₄ test 7"
end

%% 4) Dedupe within tolerance; ensure strictly increasing V
tol = 1e-6;  agg = @median;
[Vf, F] = dedupeTol(Vf_raw, F_raw, tol, agg);
assert(all(diff(Vf)>0), 'Force voltages not strictly increasing after dedupe.');

for k = 1:numel(S)
    [S(k).V, S(k).E] = dedupeTol(S(k).V_raw, S(k).E_raw, tol, agg);
    assert(all(diff(S(k).V)>0), 'Voltages not strictly increasing after dedupe in sheet %s.', S(k).name);
end

%% 5) Overlap range across all series
minsV = [min(Vf), arrayfun(@(q) min(q.V), S)];
maxsV = [max(Vf), arrayfun(@(q) max(q.V), S)];
Vmin  = max(minsV);
Vmax  = min(maxsV);
if ~(Vmin < Vmax), error('No common overlap in voltage ranges.'); end

%% 6) Grid spacing from smallest median step
medStep = @(v) median(diff(v(diff(v)>0)));
steps = medStep(Vf);
for k = 1:numel(S), steps(end+1) = medStep(S(k).V); end %#ok<AGROW>
steps = steps(isfinite(steps) & steps>0);
ds    = iff(isempty(steps), (Vmax-Vmin)/200, min(steps));
nInt  = max(50, ceil((Vmax - Vmin)/ds));
nInt  = ceil(nInt/10)*10;
nPts  = nInt + 1;

%% 7) Build grid & interpolate
Vgrid = linspace(Vmin, Vmax, nPts).';
Fq    = interp_makima_with_pchip_fallback(Vf, F, Vgrid);

for k = 1:numel(S)
    eq = interp_makima_with_pchip_fallback(S(k).V, S(k).E, Vgrid);
    eq(eq<0) = 0; % physical guardrail
    S(k).Eq = eq;
end

%% 8) Colors by minute group (all "8 min" same color, etc.)
minsList = [S.mins];
uniqMins = unique(minsList);
Cmap     = lines(max(numel(uniqMins), 3)); % group colors
groupColor = containers.Map('KeyType','double','ValueType','any');
for i = 1:numel(uniqMins)
    groupColor(uniqMins(i)) = Cmap(mod(i-1,size(Cmap,1))+1, :);
end
markers = {'o','+','x','^','v','>','<','p','h','+','x','*','.'};  % fillables + outline-only
isFilled = @(mk) any(strcmp(mk, {'o','d','s','^','v','>','<','p','h'})); % which support MarkerFaceColor
seenCount = containers.Map('KeyType','double','ValueType','double'); % minutes -> replicate idx

%% 9) Plot Expansion (x) vs Force (y)
figure('Color','w'); hold on;

for k = 1:numel(S)
    m = S(k).mins;                          % minute group
    if ~isKey(seenCount, m), seenCount(m) = 0; end
    seenCount(m) = seenCount(m) + 1;        % replicate index within this minute group

    baseC = groupColor(m);
    repIdx = seenCount(m);

    % Vary shade per replicate: alternate lighten/darken with gentle steps
    alphas = [0.00, 0.15, 0.25, 0.10, 0.20, 0.30];
    a = alphas(mod(repIdx-1, numel(alphas)) + 1);
    if mod(repIdx,2)==1
        target = [1 1 1];      % lighten
    else
        target = [0 0 0];      % darken
        a = a * 0.8;
    end
    c = (1 - a) * baseC + a * target;
    c = min(max(c,0),1);

    % cycle markers per replicate
    mk = markers{mod(repIdx-1, numel(markers)) + 1};
    label = S(k).name;                      % exact sheet name, e.g., "8 min CaSO₄ test 7"

    args = {'Color', c, 'LineWidth', 1.5, 'MarkerSize', 5, 'DisplayName', label};
    if isFilled(mk)
        args = [args, {'MarkerFaceColor', c, 'MarkerEdgeColor', c}];
    else
        args = [args, {'MarkerEdgeColor', c}];
    end

    plot(S(k).Eq, Fq, mk, args{:});
end

xlabel('Expansion (units)');
ylabel('Force (N)');
title('Hydrogel Force vs Expansion (MAKIMA with PCHIP fallback)');
legend('Location','best');
grid on; grid minor;
ax = gca; ax.GridAlpha = 0.4; ax.MinorGridAlpha = 0.3;

allE = vertcat(S.Eq);
xlim([min(allE), max(allE)]);
xlabel('Expansion (units)');
ylabel('Force (N)');
title('Hydrogel Force vs Expansion (MAKIMA with PCHIP fallback)');
legend('Location','best');
grid on; grid minor;
ax = gca; ax.GridAlpha = 0.4; ax.MinorGridAlpha = 0.3;

allE = vertcat(S.Eq);
xlim([1, 4.5]);
ylim([0, 2]);



%% ---------------- Local functions ----------------
function [Vout, Yout] = dedupeTol(V, Y, tol, aggfun)
    if nargin < 4 || isempty(aggfun), aggfun = @median; end
    V = V(:); Y = Y(:);
    m = isfinite(V) & isfinite(Y);
    V = V(m); Y = Y(m);
    [Vs, ord] = sort(V); Ys = Y(ord);
    n = numel(Vs);
    if n <= 1, Vout = Vs; Yout = Ys; return; end
    g = [true; diff(Vs) > tol];
    gid = cumsum(g);
    Vout = accumarray(gid, Vs, [], @mean);
    Yout = accumarray(gid, Ys, [], aggfun);
    if any(diff(Vout) <= 0)
        Vout = Vout + (0:numel(Vout)-1)'*eps(max(Vout));
    end
end

function Yq = interp_makima_with_pchip_fallback(X, Y, Xq)
    Yq = interp1(X, Y, Xq, 'makima');
    if any(diff(Yq) < 0)
        Yq = interp1(X, Y, Xq, 'pchip');
    end
end

function mins = parseSoakMinutes(name)
% Extract leading "<number> min" from names like "8 min CaSO₄ test 7"
    mins = NaN;
    tk = regexpi(name, '^\s*(\d+)\s*min', 'tokens'); % prefer leading match
    if ~isempty(tk)
        mins = str2double(tk{1}{1});
    end
end

function y = iff(cond, a, b), if cond, y = a; else, y = b; end, end