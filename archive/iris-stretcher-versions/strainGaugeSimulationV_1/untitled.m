% 1) Read in your calibration sheets
forceTbl = readtable('V1-13Jul-Expansion.xlsx','Sheet','ForceVVolt');
expTbl   = readtable('V1-13Jul-Expansion.xlsx','Sheet','ExpVVolt');

V_F   = forceTbl.Voltage;    % volts for force sensor
Force = forceTbl.Force;      % corresponding force (N)

V_E      = expTbl.Voltage;   % volts for expansion sensor
Expansion = expTbl.Expansion;% corresponding expansion (units)

% 2) Fit cubic polynomials to each calibration
pF = polyfit(V_F,   Force,     3);   % [a3 a2 a1 a0], Force ≈ a3·V^3 + a2·V^2 + a1·V + a0
pE = polyfit(V_E,   Expansion, 3);   % [b3 b2 b1 b0], Expansion ≈ b3·V^3 + b2·V^2 + b1·V + b0

% 3) Display the coefficients
fprintf('Force poly coeffs [a3 a2 a1 a0]:\n');  disp(pF);
fprintf('Expansion poly coeffs [b3 b2 b1 b0]:\n'); disp(pE);

% 4) (Optional) Map your measured voltages into real units:
%    Assume you have vectors VF_meas and VE_meas of the same size:
%    Force_est     = polyval(pF, VF_meas);
%    Expansion_est = polyval(pE, VE_meas);

% 5) Plot each calibration with its fit
figure;

subplot(1,2,1)
plot(V_F, Force, 'ko', V_F, polyval(pF, V_F), 'r-','LineWidth',1.5)
xlabel('Voltage (V)'), ylabel('Force (N)')
title('Force vs. Voltage Calibration')
legend('Data','Cubic Fit','Location','best')
grid on

subplot(1,2,2)
plot(V_E, Expansion, 'ko', V_E, polyval(pE, V_E), 'r-','LineWidth',1.5)
xlabel('Voltage (V)'), ylabel('Expansion (units)')
title('Expansion vs. Voltage Calibration')
legend('Data','Cubic Fit','Location','best')
grid on