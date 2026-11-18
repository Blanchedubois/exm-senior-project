% gridStretchTopTwoRowsFractureWithVideo.m
% -------------------------------------------------------------------------
% 2D grid of point-masses connected by visco–NeoHookean springs/dashpots
% with diagonal triangulation, light damping, Velocity-Verlet integration.
% Bottom row is fixed; top TWO rows are pulled upward at constant speed;
% all interior nodes move naturally. Springs fracture when U_fracture > E_break.
% The animation is saved as an MP4.
% -------------------------------------------------------------------------

clear; clc; close all;

%% 1) PARAMETERS
Nx        = 15;           % # of rows
Ny        = 15;           % # of columns
dx        = 0.1;          % rest spacing in X [m]
dy        = 0.1;          % rest spacing in Y [m]
m         = 0.01;         % mass per node [kg]
G         = 1e4;          % shear modulus [Pa]
eta       = 50;           % viscosity [Pa·s]
A0        = 1e-4;         % spring cross-section [m^2]
vStretch  = 2;            % pull speed for top rows [m/s]
t_end     = 100.0;        % total simulation time [s]
dt        = 2e-4;         % time step [s]
c_global  = 0.1;          % air damping [kg/s]
E_break   = 0.5;          % fracture energy threshold [J]

nSteps    = floor(t_end/dt);

%% 2) INITIALIZE GRID POSITIONS & VELOCITIES
[Xg,Yg] = meshgrid((0:Ny-1)*dx, (0:Nx-1)*dy);  % size Nx×Ny
pos     = [Xg(:), Yg(:)];                     % (Nx*Ny)×2
origPos = pos;                                % for fixed bottom BC
vel     = zeros(Nx*Ny,2);                     % initial velocities

%% 3) BUILD SPRINGS (horizontal, vertical, diagonals)
springs = zeros(0,2);
l0_list = zeros(0,1);
for j = 1:Ny
  for i = 1:Nx
    k = i + (j-1)*Nx;         % linear index
    if i < Nx                  % horizontal spring
      springs(end+1,:) = [k, k+1];
      l0_list(end+1)   = dx;
    end
    if j < Ny                  % vertical spring
      springs(end+1,:) = [k, k+Nx];
      l0_list(end+1)   = dy;
    end
    if i < Nx && j < Ny        % two diagonals
      springs(end+1,:) = [k,      k+Nx+1];  l0_list(end+1) = sqrt(dx^2+dy^2);
      springs(end+1,:) = [k+1,    k+Nx];    l0_list(end+1) = sqrt(dx^2+dy^2);
    end
  end
end
nSprings = size(springs,1);

%% 4) DEFINE BOUNDARY INDICES
indexMap       = reshape(1:(Nx*Ny), Nx, Ny);  
bottomRowIdx   = indexMap(1,   :);    % row i=1 (fixed)
secondTopIdx   = indexMap(Nx-1, :);   % row i=Nx-1
topRowIdx      = indexMap(Nx,   :);   % row i=Nx
pulledIdx      = [secondTopIdx, topRowIdx];  % these two rows get pulled
fixedIdx       = bottomRowIdx;               % only bottom row is fixed

%% 5) FRACTURE FLAGS & INITIAL FORCE
broken = false(nSprings,1);
F      = zeros(Nx*Ny,2);

%% 6) SET UP FIGURE & VIDEO
fig = figure('Name','Grid: Top 2 Rows Pulled & Fracture','NumberTitle','off');
hold on;
hSpr   = gobjects(nSprings,1);
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

vw = VideoWriter('gridTopTwoRowsFracture.mp4','MPEG-4');
vw.FrameRate = 30;
open(vw);

%% 7) TIME-INTEGRATION LOOP WITH VIDEO CAPTURE
for step = 1:nSteps
  % current time
  t = step * dt;
  % a) compute acceleration
  a = (F - c_global*vel) / m;
  % b) Verlet position update
  pos_n   = pos + vel*dt + 0.5*a*dt^2;
  vel_mid = vel + 0.5*a*dt;
  % c) enforce bottom row fixed
  pos_n(fixedIdx,:)   = origPos(fixedIdx,:);
  vel_mid(fixedIdx,:) = 0;
  % d) pull top two rows upward
  pos_n(pulledIdx,2)   = pos(pulledIdx,2) + vStretch*dt;
  vel_mid(pulledIdx,:) = repmat([0, vStretch], numel(pulledIdx),1);
  % e) recompute forces & fracture-check
  F_new = zeros(Nx*Ny,2);
  for s = 1:nSprings
    if broken(s), continue; end
    i1 = springs(s,1); i2 = springs(s,2);
    x1 = pos_n(i1,:);   x2 = pos_n(i2,:);
    v1 = vel_mid(i1,:); v2 = vel_mid(i2,:);
    dX = x2 - x1; L = norm(dX); n = dX/L;
    dL = dot(v2-v1,n); l0 = l0_list(s);
    % fracture energy
    U_fracture = A0*G*( L + (l0^3)/(2*L^2) );
    if U_fracture > E_break
      broken(s) = true;
      set(hSpr(s),'Visible','off');
      continue;
    end
    % spring force (elastic+viscous)
    lambda = L/l0;
    Fmag   = A0*( G*(lambda - lambda^(-2)) + eta*(dL/L) );
    Fspr   = Fmag * n;
    F_new(i1,:) = F_new(i1,:) + Fspr;
    F_new(i2,:) = F_new(i2,:) - Fspr;
  end
  % f) clamp forces on BC nodes
  F_new(fixedIdx,:)  = 0;
  F_new(pulledIdx,:) = 0;
  % g) Verlet velocity update
  a_new = (F_new - c_global*vel_mid)/m;
  vel_n = vel_mid + 0.5*a_new*dt;
  % h) reapply BCs
  pos_n(fixedIdx,:)   = origPos(fixedIdx,:);
  vel_n(fixedIdx,:)   = 0;
  pos_n(pulledIdx,2)  = pos(pulledIdx,2) + vStretch*dt;
  vel_n(pulledIdx,:)  = repmat([0, vStretch], numel(pulledIdx),1);
  % i) commit updates
  pos = pos_n; vel = vel_n; F = F_new;
  % j) update plot & write video frame every 20 steps
  if mod(step,20)==0
    for s = 1:nSprings
      if ~broken(s)
        i1 = springs(s,1); i2 = springs(s,2);
        set(hSpr(s),'XData',pos([i1,i2],1),'YData',pos([i1,i2],2));
      end
    end
    set(hNodes,'XData',pos(:,1),'YData',pos(:,2));
    drawnow;
    writeVideo(vw,getframe(fig));
  end
end

% finalize video
close(vw);
disp('Animation saved as gridTopTwoRowsFracture.mp4');