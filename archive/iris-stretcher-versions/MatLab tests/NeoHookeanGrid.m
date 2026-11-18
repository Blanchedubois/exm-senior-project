% gridStretchPullUpMovingBC_LongTime.m
% -------------------------------------------------------------------------
% 2D grid of point-masses connected by corrected visco–NeoHookean springs/dashpots
% with diagonal triangulation, light global damping, and Velocity-Verlet
% integration. Bottom row fixed, top row pulled upward at constant speed.
% Total simulation time extended to 100 s.
% -------------------------------------------------------------------------

clear; clc; close all;

%% 1) PARAMETERS
Nx        = 10;          % # of rows
Ny        = 10;          % # of columns
dx        = 0.1;         % rest horizontal spacing [m]
dy        = 0.1;         % rest vertical spacing [m]
m         = 0.01;        % mass of each node [kg]
G         = 1e4;         % shear modulus [Pa]
eta       = 50;          % viscosity [Pa·s]
A0        = 1e-4;        % reference area of each spring [m^2]
vStretch  = 1;         % pull speed for top row [m/s]
t_end     = 100.0;       % total simulation time [s] ← extended to 100 s
dt        = 2e-4;        % time step [s]
c_global  = 0.5;         % light global damping [kg/s]

nSteps = floor(t_end/dt);

%% 2) INITIALIZE GRID POSITIONS & VELOCITIES
[Xg,Yg] = meshgrid((0:Ny-1)*dx, (0:Nx-1)*dy);
pos     = [Xg(:), Yg(:)];       % (Nx*Ny)×2 positions
origPos = pos;                  % keep for bottom-row BC
vel     = zeros(Nx*Ny,2);       % zero initial velocities

%% 3) BUILD SPRING LIST (horiz., vert., diagonals)
springs = zeros(0,2);
l0_list = zeros(0,1);
for j = 1:Ny
  for i = 1:Nx
    k = i + (j-1)*Nx;  % flatten index column-major
    if i < Nx
      k2 = (i+1) + (j-1)*Nx;           % right neighbor
      springs(end+1,:) = [k, k2];      l0_list(end+1) = dx;
    end
    if j < Ny
      k2 = i + j*Nx;                   % up neighbor
      springs(end+1,:) = [k, k2];      l0_list(end+1) = dy;
    end
    if i < Nx && j < Ny
      k_dr = (i+1) + j*Nx;             % up-right
      springs(end+1,:) = [k, k_dr];    l0_list(end+1) = sqrt(dx^2+dy^2);
      k_ul = i + (j-1)*Nx;             % down-left from the opposite cell
      k_br = (i+1) + (j-1)*Nx;
      springs(end+1,:) = [k_ul, k_br]; l0_list(end+1) = sqrt(dx^2+dy^2);
    end
  end
end
nSprings = size(springs,1);

%% 4) BOUNDARY INDICES
bottomIdx = 1:Nx:Nx*Ny;   % all nodes in first row (j=1)
topIdx    = Nx:Nx:Nx*Ny;  % all nodes in last row (j=Ny)

%% 5) INITIAL FORCE (zero, springs at rest)
F = zeros(Nx*Ny,2);

%% 6) SET UP FIGURE
figure('Name','Grid Pulling Up (100 s)','NumberTitle','off');
hSpr = gobjects(nSprings,1);
hold on;
for s = 1:nSprings
  i1 = springs(s,1); i2 = springs(s,2);
  hSpr(s) = plot(pos([i1,i2],1), pos([i1,i2],2), '-b', 'LineWidth', 1);
end
hNodes = scatter(pos(:,1), pos(:,2), 36, 'filled', 'r');
axis equal;
xlim([-dx, (Ny-1)*dx + dx]);
ylim([-dy, 5]);
xlabel('X (m)'); ylabel('Y (m)');
title('Visco–NeoHookean Grid Pulled Up over 100 s');
grid on;
drawnow;

%% 7) TIME-INTEGRATION LOOP (Velocity-Verlet)
for step = 1:nSteps
  t = step * dt;
  
  % 7.1) acceleration
  a = (F - c_global*vel) / m;
  
  % 7.2) position update
  pos_n   = pos + vel*dt + 0.5*a*dt^2;
  vel_mid = vel + 0.5*a*dt;
  
  % 7.3) enforce BC on bottom row (fixed)
  pos_n(bottomIdx,:)   = origPos(bottomIdx,:);
  vel_mid(bottomIdx,:) = 0;
  
  % 7.4) increment top-row Y (pull up)
  pos_n(topIdx,2)    = pos(topIdx,2) + vStretch*dt;
  vel_mid(topIdx,:)  = repmat([0, vStretch], length(topIdx), 1);
  
  % 7.5) recompute forces at mid-step
  F_new = zeros(Nx*Ny,2);
  for s = 1:nSprings
    i1 = springs(s,1); i2 = springs(s,2);
    x1 = pos_n(i1,:);   x2 = pos_n(i2,:);
    v1 = vel_mid(i1,:); v2 = vel_mid(i2,:);
    dX = x2 - x1;       L = norm(dX);    n = dX / L;
    dL = dot(v2 - v1, n);
    l0 = l0_list(s);
    Fmag = A0*( G*(L/l0 - (l0^2)/(L^2)) + eta*(dL/L) );
    Fspr = Fmag * n;
    F_new(i1,:) = F_new(i1,:) + Fspr;
    F_new(i2,:) = F_new(i2,:) - Fspr;
  end
  F_new(bottomIdx,:) = 0;
  F_new(topIdx,:)    = 0;
  
  % 7.6) velocity update
  a_new = (F_new - c_global*vel_mid) / m;
  vel_n = vel_mid + 0.5*a_new*dt;
  
  % 7.7) re-apply BC on vel & pos
  pos_n(bottomIdx,:) = origPos(bottomIdx,:);
  vel_n(bottomIdx,:) = 0;
  pos_n(topIdx,2)    = pos(topIdx,2) + vStretch*dt;
  vel_n(topIdx,:)    = repmat([0, vStretch], length(topIdx), 1);
  
  % 7.8) commit
  pos = pos_n;
  vel = vel_n;
  F   = F_new;
  
  % 7.9) update plot (every 50 steps to speed up)
  if mod(step,50)==0
    for s = 1:nSprings
      i1 = springs(s,1); i2 = springs(s,2);
      set(hSpr(s), 'XData', pos([i1,i2],1), 'YData', pos([i1,i2],2));
    end
    set(hNodes, 'XData', pos(:,1), 'YData', pos(:,2));
    drawnow;
  end
end