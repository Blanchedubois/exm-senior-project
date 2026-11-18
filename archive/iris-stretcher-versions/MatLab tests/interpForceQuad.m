% —————————————————————————————————————————————————————
% SCRIPT: load_and_interp.m
% Reads V & F from a spreadsheet, then interpolates at query voltages
% —————————————————————————————————————————————————————
% 1) Let the user pick the file (optional)
[fn, path] = uigetfile({'*.xlsx;*.xls;*.csv','Data Files (*.xlsx,*.xls,*.csv)'}, ...
                       'Select your data file');
if isequal(fn,0)
    error('No file selected.');
end
filename = fullfile(path,fn);

% 2) Read the table (works for .xlsx, .xls, or .csv)
%    Assumes your sheet has headers “Voltage” and “Force”
tbl = readtable(filename);

% 3) Extract vectors
Vdata = tbl.Voltage;   % e.g. [0.1;0.2;0.5;…]
Fdata = tbl.Force;     % e.g. [2;4;10;…] 

% 4) Define the voltages you want to query
Vin = linspace(min(Vdata), max(Vdata), 100)';  % 100 points between your min/max

% 5) Call the quadratic‐interpolation function
Finterp = interpForceQuad(Vdata, Fdata, Vin);

% 6) Plot to check
figure;
plot(Vdata, Fdata, 'ko','MarkerFaceColor','k'); hold on;
plot(Vin,     Finterp, 'b-','LineWidth',1.2);
xlabel('Voltage'); ylabel('Force');
legend('Measured','Interpolated','Location','Best');
grid on;
