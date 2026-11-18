% viscoNeoHookeanAnimation.m
% -------------------------------------------------------------------------
% 1D Visco–NeoHookean bar with Kelvin–Voigt rheology, inertial mass, ODE45
% integration, plotting, and simple animation.
% -------------------------------------------------------------------------

clear; clc; close all;

%% 1) PARAMETERS (fill in your values)
m    = 0.1;        % mass [kg]
G    = 1e4;        % shear modulus [Pa]
eta  = 50;         % viscosity [Pa·s]
A0   = 1e-4;       % reference cross-sectional area [m^2]
l0   = 0.01;       % reference length [m]

% External force as a function of time (examples shown; pick one)
Fext = @(t) 0;                 % zero load
% Fext = @(t) 1.0 * (t>0.1);    % step of 1 N at t = 0.1 s
% Fext = @(t) 0.5*sin(2*pi*5*t);% 5 Hz sinusoidal

%% 2) INITIAL CONDITIONS
l_init = l0;   % start at rest length
v_init = 0;    % zero initial velocity
x0     = [l_init; v_init];

%% 3) DEFINE THE ODE SYSTEM
% State x = [ l ; v ]
odefun = @(t, x) [ 
    x(2);  % dl/dt = v
    ( Fext(t) ...
      - A0*G*(1 - (l0^2)/(x(1)^3)) ...   % elastic Neo-Hookean force
      - eta*A0*( x(2)/x(1) ) ...         % viscous dash‐pot force
    ) / m
];

%% 4) INTEGRATE WITH ODE45
tspan = [0, 100.0];  % simulate from 0 to 1 s
opts  = odeset('RelTol',1e-6,'AbsTol',1e-8);
[t, x] = ode45(odefun, tspan, x0, opts);

l = x(:,1);  % length vs time
v = x(:,2);  % velocity vs time

%% 5) PLOT RESULTS
figure(1);
subplot(2,1,1);
plot(t, l, 'LineWidth',1.5);
xlabel('Time (s)');
xlim([0, 2*l0*250])
ylabel('Length l(t) (m)');
title('Visco–NeoHookean Bar: Length vs Time');
grid on;

subplot(2,1,2);
plot(t, v, 'LineWidth',1.5);
xlabel('Time (s)');
xlim([0, 2*l0*250])
ylabel('Velocity \dot l(t) (m/s)');
title('Visco–NeoHookean Bar: Velocity vs Time');
grid on;

%% 6) UNIFORM‐TIME ANIMATION (e.g. 30 fps)
fps     = 30;                   % frames per second
dt_anim = 1/fps;                % uniform time step for animation
t_anim  = 0:dt_anim:t(end);     % from t=0 to t_final
l_anim  = interp1(t, l, t_anim);% stretch resampled at uniform times

figure(2);
hBar = plot([0, l_anim(1)], [0, 0], 'LineWidth', 12);
axis equal;
xlim([0, 2*l0*25]);    % or whatever you like
ylim([-0.1, 0.1]);
xlabel('Length (m)');
grid on;

for k = 1:numel(t_anim)
    set(hBar, 'XData', [0, l_anim(k)]);
    title(sprintf('t = %.2f s', t_anim(k)));
    drawnow;
    pause(dt_anim);
end

%% 7) OPTIONAL: RECORD AN MP4 VIDEO
% Uncomment this block if you want to save the animation to 'bar_stretch.mp4'.
%
% vw = VideoWriter('bar_stretch.mp4','MPEG-4');
% open(vw);
% figure(3);
% hBar2 = plot([0, l(1)], [0, 0], 'LineWidth', 12);
% axis equal; xlim([0, 1.5*l0]); ylim([-0.1, 0.1]);
% xlabel('Length (m)'); grid on;
% for k = 1:length(t)
%     set(hBar2, 'XData', [0, l(k)]);
%     title(sprintf('t = %.2f s', t(k)));
%     frame = getframe(gcf);
%     writeVideo(vw, frame);
% end
% close(vw);