% File: plot_force_vs_expansion.m
% ------------------------------------------
% Prompts for an Excel file containing TWO sheets:
%   • ForceVVoltage  (2 columns: Force, Voltage)
%   • ExpVVoltage    (2 columns: Expansion, Voltage)
% Then it:
%   1. Sorts each dataset by its Voltage column
%   2. Finds the overlapping Voltage range
%   3. Builds a “nice” common grid (multiple of 10 intervals)
%   4. Interpolates each onto that grid via interpForceQuad
%   5. Plots Expansion vs. Force (parametric curve)
%   6. Offers to export the (Voltage, Force, Expansion) table to CSV

function plot_force_vs_expansion()
    % 1) Pick your Excel file
    [fn, path] = uigetfile({'*.xlsx;*.xls','Excel Files (*.xlsx,*.xls)'}, ...
                           'Select your data file');
    if isequal(fn,0)
        error('No file selected.');
    end
    filename = fullfile(path,fn);

    % 2) Load Force vs. Voltage
    Tf  = readtable(filename, 'Sheet','ForceVVoltage');
    F   = Tf{:,1};   % Force
    Vf  = Tf{:,2};   % Voltage

    % 3) Load Expansion vs. Voltage
    Te  = readtable(filename, 'Sheet','ExpVVoltage');
    E   = Te{:,1};   % Expansion
    Ve  = Te{:,2};   % Voltage

    % 4) Sort each dataset by voltage
    [Vf, If] = sort(Vf); F = F(If);
    [Ve, Ie] = sort(Ve); E = E(Ie);

    % 5) Determine overlap
    Vmin = max(min(Vf), min(Ve));
    Vmax = min(max(Vf), max(Ve));
    if Vmin >= Vmax
        error('No overlap in voltage ranges: [%g,%g] vs [%g,%g]', ...
              min(Vf),max(Vf), min(Ve),max(Ve));
    end

    % 6) Build “nice” grid
    ds  = min(median(diff(Vf)), median(diff(Ve)));
    nInt = ceil((Vmax-Vmin)/ds/10)*10;  % round up to nearest 10
    nPts = nInt + 1;
    Vgrid = linspace(Vmin, Vmax, nPts).';

    % 7) Interpolate both curves
    Fq = interpForceQuad(Vf, F, Vgrid);
    Eq = interpForceQuad(Ve, E, Vgrid);

    % 8) Parametric plot: Expansion vs. Force
    figure;
    plot(Fq, Eq, '-o', 'LineWidth',1.5, 'MarkerSize',4);
    xlabel('Force');
    ylabel('Expansion');
    title('Parametric: Expansion vs. Force');
    grid on;

    % 9) Export option
    answer = questdlg('Export aligned data to CSV?', 'Export CSV', 'Yes','No','Yes');
    if strcmp(answer,'Yes')
        [csvn, csvp] = uiputfile('ParametricData.csv','Save CSV as');
        if ~isequal(csvn,0)
            Texp = table(Vgrid, Fq, Eq, ...
                         'VariableNames',{'Voltage','Force','Expansion'});
            writetable(Texp, fullfile(csvp,csvn));
            fprintf('--> Exported to %s\n', fullfile(csvp,csvn));
        end
    end
end