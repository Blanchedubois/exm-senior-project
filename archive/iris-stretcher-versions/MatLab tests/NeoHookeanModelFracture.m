% gridStretchTwoRowsFractureCorrected.m
% -------------------------------------------------------------------------
% 2D grid of point-masses with corrected visco–NeoHookean springs/dashpots,
% diagonal triangulation, light damping, Velocity-Verlet integration.
% Bottom row fixed; top TWO rows pulled upward at constant speed.
% Springs break when U_fracture > E_break.
% -------------------------------------------------------------------------

clear; clc; close all;

%% 1) PARAMETERS
Nx        = 15;           % # of rows
Ny        = 15;           % # of columns
dx        = 0.1;          % rest horizontal spacing [m]
dy        = 0.1;          % rest vertical spacing [m]
m         = 0.01;         % mass per node [kg]
G         = 1e4;          % shear modulus [Pa]
eta       = 50;           % viscosity [Pa·s]
A0        = 1e-4;         % spring cross-section [m^2]
vStretch  = 5;          % pull speed [m/s]
t_end     = 100.0;          % sim duration [s]
dt        = 2e-4;         % time step [s]
c_global  = 0.2;          % damping [kg/s]
E_break   = 5e-1;         % fracture energy threshold [J]

nSteps    = floor(t_end/dt);

%% 2) INITIALIZE GRID & DYNAMICS
[Xg,Yg] = meshgrid((0:Ny-1)*dx, (0:Nx-1)*dy);
pos     = [Xg(:), Yg(:)];       % (Nx*Ny)x2 current positions
origPos = pos;                  % reference for bottom row BC
vel     = zeros(Nx*Ny,2);       % initial velocities

%% 3) BUILD SPRINGS (horiz., vert., diagonals)
springs = zeros(0,2);
l0_list = zeros(0,1);
for j = 1:Ny
  for i = 1:Nx
    k = i + (j-1)*Nx;           % flatten index
    if i < Nx                    % right neighbor
      k2 = (i+1)+(j-1)*Nx;
      springs(end+1,:) = [k,k2];
      l0_list(end+1)   = dx;
    end
    if j < Ny                    % up neighbor
      k2 = i + j*Nx;
      springs(end+1,:) = [k,k2];
      l0_list(end+1)   = dy;
    end
    if i<Nx && j<Ny              % two diagonals
      k_dr = (i+1) + j*Nx;       % up-right
      springs(end+1,:) = [k,k_dr];
      l0_list(end+1)   = sqrt(dx^2+dy^2);
      k_ul = i + (j-1)*Nx;       % down-left of neighbor
      k_br = (i+1) + (j-1)*Nx;   % down-right
      springs(end+1,:) = [k_ul,k_br];
      l0_list(end+1)   = sqrt(dx^2+dy^2);
    end
  end
end
nSprings = size(springs,1);

%% 4) DEFINE BOUNDARIES
bottomIdx    = 1:Nx:Nx*Ny;               % row i=1 fixed
topIdx       = Nx:Nx:Nx*Ny;              % row i=Nx
secondTopIdx = (Nx-1):Nx:(Nx*Ny-1);      % row i=Nx-1
pulledIdx    = [topIdx, secondTopIdx];   % pull these two rows

%% 5) FRACTURE FLAGS
broken = false(nSprings,1);

%% 6) INITIAL FORCE
F = zeros(Nx*Ny,2);

%% 7) SET UP PLOT
figure('Name','Grid: Top 2 Rows Pulled & Fracture','NumberTitle','off');
hold on;
hSpr = gobjects(nSprings,1);
for s = 1:nSprings
  i1 = springs(s,1); i2 = springs(s,2);
  hSpr(s) = plot(pos([i1,i2],1), pos([i1,i2],2), '-b','LineWidth',1);
end
hNodes = scatter(pos(:,1), pos(:,2), 36, 'filled','r');
axis equal;
xlim([-dx, (Ny-1)*dx + dx]);
ylim([-dy, 5]);
xlabel('X (m)'); ylabel('Y (m)');
title('Visco–NeoHookean Grid: Top 2 Rows Pulled & Fracture');
grid on; drawnow;

%% 8) TIME-INTEGRATION LOOP
for step = 1:nSteps
  t = step*dt;
  % 8.1) compute accel
  a = (F - c_global*vel)/m;
  % 8.2) Verlet update
  pos_n   = pos + vel*dt + 0.5*a*dt^2;
  vel_mid = vel + 0.5*a*dt;
  % 8.3) enforce bottom fixed
  pos_n(bottomIdx,:)   = origPos(bottomIdx,:);
  vel_mid(bottomIdx,:) = 0;
  % 8.4) pull top two rows
  pos_n(pulledIdx,2)   = pos(pulledIdx,2) + vStretch*dt;
  vel_mid(pulledIdx,:) = repmat([0, vStretch], length(pulledIdx),1);
  % 8.5) recompute forces & fracture
  F_new = zeros(Nx*Ny,2);
  for s = 1:nSprings
    if broken(s), continue; end
    i1 = springs(s,1); i2 = springs(s,2);
    x1 = pos_n(i1,:); x2 = pos_n(i2,:);
    v1 = vel_mid(i1,:); v2 = vel_mid(i2,:);
    dX = x2 - x1; L = norm(dX); n = dX/L;
    dL=dot(v2-v1,n); l0=l0_list(s);
    % fracture energy
    U_fracture = A0*G*( L + (l0^3)/(2*L^2) );
    if U_fracture > E_break
      broken(s)=true;
      set(hSpr(s),'Visible','off');
      continue;
    end
    % spring force
    lambda = L/l0;
    Fmag   = A0*( G*(lambda - lambda^(-2)) + eta*(dL/L) );
    Fspr   = Fmag * n;
    F_new(i1,:) = F_new(i1,:) + Fspr;
    F_new(i2,:) = F_new(i2,:) - Fspr;
  end
  % 8.6) clamp BC forces
  F_new(bottomIdx,:) = 0;
  F_new(pulledIdx,:) = 0;
  % 8.7) velocity update
  a_new = (F_new - c_global*vel_mid)/m;
  vel_n = vel_mid + 0.5*a_new*dt;
  % 8.8) reapply BCs
  pos_n(bottomIdx,:) = origPos(bottomIdx,:);
  vel_n(bottomIdx,:) = 0;
  pos_n(pulledIdx,2) = pos(pulledIdx,2) + vStretch*dt;
  vel_n(pulledIdx,:) = repmat([0, vStretch], length(pulledIdx),1);
  % 8.9) commit
  pos = pos_n; vel = vel_n; F = F_new;
  % 8.10) update plot every 20 steps
  if mod(step,20)==0
    for s = 1:nSprings
      if ~broken(s)
        i1=springs(s,1); i2=springs(s,2);
        set(hSpr(s),'XData',pos([i1,i2],1),'YData',pos([i1,i2],2));
      end
    end
    set(hNodes,'XData',pos(:,1),'YData',pos(:,2));
    drawnow;
  end
end