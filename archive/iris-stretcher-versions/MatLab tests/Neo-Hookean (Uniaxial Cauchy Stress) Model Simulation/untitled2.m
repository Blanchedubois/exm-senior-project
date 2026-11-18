% ------------------------------------------------------------
% Neo-Hookean spring-mass simulation + animation
% ------------------------------------------------------------
clear; clc;

%% -----------------------------------------------------------
% 1.  Material / geometry / mass
A0  = 8e-6;          % undeformed area  [m^2]
l0  = 10e-3;         % rest length      [m]
G   = 5e3;           % shear modulus    [Pa] (5 kPa)

m   = 2e-3;          % mass             [kg]

%% -----------------------------------------------------------
% 2.  Initial conditions
x0  = 2e-3;          % initial extension (2 mm)
v0  = 0;             % initial velocity
y0  = [x0; v0];      % state vector

tEnd   = 2;          % total simulation time [s]
tSpan  = [0 tEnd];

%% -----------------------------------------------------------
% 3.  Force and ODE definition
springForce = @(x) -(A0*l0./(l0+x)) .* G .* ...
                   ((l0+x)./l0 - (l0./(l0+x)).^2);

odeFun = @(t,y) [ y(2);                % dx/dt = v
                  springForce(y(1))/m  % dv/dt = F/m
                ];

%% -----------------------------------------------------------
% 4.  Integrate
opts = odeset('RelTol',1e-8,'AbsTol',1e-10);
[t, Y] = ode45(odeFun, tSpan, y0, opts);

x = Y(:,1);             % extension
v = Y(:,2);             % velocity
F = springForce(x);     % force time-history
l = l0 + x;             % current length

%% -----------------------------------------------------------
% 5.  Static plots
figure('Name','Simulation results','Position',[100 100 600 700]);

subplot(3,1,1)
plot(t, x*1e3,'LineWidth',1.4);
ylabel('Extension  x  [mm]'); grid on

subplot(3,1,2)
plot(t, v,'LineWidth',1.4);
ylabel('Velocity  v  [m/s]'); grid on

subplot(3,1,3)
plot(t, F,'LineWidth',1.4);
ylabel('Force  F  [N]'); xlabel('Time  t  [s]'); grid on

sgtitle('Neo-Hookean spring–mass simulation');

%% -----------------------------------------------------------
% 6.  Animation setup
%   Anchor is fixed at x = 0, mass at x = l0 + x(t)
animFig = figure('Name','Spring-mass animation',...
                 'Position',[750 200 600 250]);
axis equal; axis([-0.002 0.03 -0.02 0.02]); axis off
title('Neo-Hookean spring-mass (½× real speed)')

% Pre-draw mass (filled rectangle) and a polyline spring
hold on
massW = 0.004; massH = 0.008;
massPatch = fill([0 0 0 0],[0 0 0 0],'b','EdgeColor','k');
springLine = plot([0 0],[0 0],'k','LineWidth',2);
hold off

% Zig-zag parameters for spring drawing
nCoils = 10; amp = 0.003;   % number of zig-zags & amplitude

% Pre-compute frame timing
frameDt = 1/60;             % 60 FPS
animT   = 0:frameDt:tEnd;
xInterp = interp1(t,x,animT,'pchip');
lInterp = l0 + xInterp;

% Optional GIF export
makeGIF   = false;          % set true to save
gifName   = 'neoHookeanSpring.gif';

%% -----------------------------------------------------------
% 7.  Run animation
for k = 1:numel(animT)
    % current length & mass position
    L  = lInterp(k);
    xm = L;                 % mass centre x-pos
    
    % --- update spring polyline (simple zig-zag) ---------------
    xs = linspace(0, xm, nCoils*2+2);
    ys = zeros(size(xs));
    ys(2:2:end-1) = amp;
    ys(3:2:end-2) = -amp;
    set(springLine,'XData',xs,'YData',ys);
    
    % --- update mass patch ------------------------------------
    xLeft = xm - massW/2;
    set(massPatch,'XData',[xLeft xLeft+massW xLeft+massW xLeft], ...
                  'YData',[-massH/2 -massH/2 massH/2 massH/2]);
    
    drawnow;
    
    % --- optional GIF output ----------------------------------
    if makeGIF
        frame = getframe(animFig);
        [im,cm] = rgb2ind(frame2im(frame),256);
        if k == 1
            imwrite(im,cm,gifName,'gif','Loopcount',inf,'DelayTime',frameDt*2);
        else
            imwrite(im,cm,gifName,'gif','WriteMode','append','DelayTime',frameDt*2);
        end
    else
        pause(frameDt*0.5);  % show at half real speed
    end
end

% -------------------------------------------------------------
% Done!  (Uncomment makeGIF=true above to produce neoHookeanSpring.gif)