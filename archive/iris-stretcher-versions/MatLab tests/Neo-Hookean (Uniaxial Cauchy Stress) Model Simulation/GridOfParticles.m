%---------------------------------------------------------------
%  Neo-Hookean square lattice with diagonals + bond breaking
%  Fast animation: draws every 40 steps (≈ 0.008 s in sim-time)
%---------------------------------------------------------------
clear; clc; close all;

%% ---------- user parameters ----------
Nx = 50;  Ny = 50;
dx = 4e-3;  dy = 4e-3;
A0 = 8e-7;              % spring area  [m^2]
G  = 6e4;               % shear modulus [Pa]
m  = 1e-3;              % node mass      [kg]
damp = 0.4;            % velocity damping (0–0.2)

dt   = 2e-4;  Tend = 10.0;          % sim window
pullVx = 5e-2;   pullVy = 2e-1;     % pull speeds (x, y) [m s-1]
lambdaCrit = 15;                  % break threshold (stretch ratio)
plotEvery  = 50;                   % draw every N steps  ← faster
margin     = 0.005;                 % axes margin [m]
%---------------------------------------------------------------

%%  Build grid -------------------------------------------------
[xg,yg] = meshgrid((0:Nx-1)*dx,(0:Ny-1)*dy);      % Ny×Nx
pos = [xg(:) yg(:)];          vel = zeros(size(pos));
N   = numel(xg);
idx = @(i,j) (i-1)*Ny + j;                        % column-major

%  Neighbours: horz, vert, both diagonals
sI = []; sJ = [];
for j = 1:Ny
  for i = 1:Nx
    if i<Nx,  sI=[sI; idx(i,j)]; sJ=[sJ; idx(i+1,j)]; end
    if j<Ny,  sI=[sI; idx(i,j)]; sJ=[sJ; idx(i,  j+1)]; end
    if i<Nx && j<Ny, sI=[sI; idx(i,j)]; sJ=[sJ; idx(i+1,j+1)]; end
    if i<Nx && j>1 , sI=[sI; idx(i,j)]; sJ=[sJ; idx(i+1,j-1)]; end
  end
end
ns   = numel(sI);
r0   = pos(sJ,:) - pos(sI,:);
L0   = hypot(r0(:,1), r0(:,2));
alive = true(ns,1);                        % spring still intact?

pinned = pos(:,1) < 1e-12;                 % fix left edge

%%  Graphics ---------------------------------------------------
fig = figure('Name','Neo-Hookean grid'); axis equal off
massH  = plot(pos(:,1),pos(:,2),'bo', ...
              'MarkerSize',4,'MarkerFaceColor','b');
sprH   = line(NaN,NaN,'Color',[.2 .2 .2],'Tag','SPRINGS');
xlim([-margin, (Nx-1)*dx + pullVx*Tend + margin]);
ylim([-margin, (Ny-1)*dy + pullVy*Tend + margin]);
title('');

%%  Helpers & buffers -----------------------------------------
Fmag = @(L,idxLive) A0*G.*(1 - (L0(idxLive)./L).^3);
acc  = zeros(N,2);
nSteps = round(Tend/dt);

%%  Main loop --------------------------------------------------
for k = 1:nSteps
    % ---- impose boundary motion -----------------------------
    right = pos(:,1) > (Nx-1)*dx - 1e-12;
    vel(right,1) = pullVx;   vel(right,2) = pullVy;

    % ---- velocity–Verlet (1) --------------------------------
    vel = vel + 0.5*dt*acc;
    vel = vel*(1-damp*dt);
    pos = pos + dt*vel;
    pos(pinned,:) = [xg(pinned) yg(pinned)];      % enforce pins

    % ---- spring forces (only intact) ------------------------
    ai  = alive;                       % logical mask
    rij = pos(sJ(ai),:) - pos(sI(ai),:);
    L   = hypot(rij(:,1), rij(:,2));   % current lengths
    F   = Fmag(L,ai);
    rHat = rij ./ [L L];
    Fi   = F .* rHat;

    % scatter-add to node accelerations
    acc(:) = 0;
    acc(:,1) = accumarray([sI(ai); sJ(ai)], [ Fi(:,1); -Fi(:,1) ], [N 1])/m;
    acc(:,2) = accumarray([sI(ai); sJ(ai)], [ Fi(:,2); -Fi(:,2) ], [N 1])/m;
    acc(pinned,:) = 0;

    % ---- velocity–Verlet (2) --------------------------------
    vel = vel + 0.5*dt*acc;

    % ---- break criterion ------------------------------------
    broken = L > lambdaCrit * L0(ai);
    alive(ai) = ~broken;               % mark broken springs

    % ---- draw every plotEvery steps -------------------------
    if mod(k,plotEvery)==0 || k==nSteps
        % update spring polyline (only intact)
        ai = alive;
        X = [pos(sI(ai),1) pos(sJ(ai),1) NaN(sum(ai),1)].';
        Y = [pos(sI(ai),2) pos(sJ(ai),2) NaN(sum(ai),1)].';
        set(sprH,'XData',X(:),'YData',Y(:));
        set(massH,'XData',pos(:,1),'YData',pos(:,2));
        title(sprintf('t = %.2f / %.0f s – springs left: %d', ...
              k*dt, Tend, sum(alive)));
        drawnow;          % draw only every ~40 steps  → much faster
    end
end