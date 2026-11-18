% ------------------------------------------------------------
% 2-D Neo-Hookean mass–spring lattice demo
% ------------------------------------------------------------
clear; clc; close all;

%% 1.  Parameters
Nx = 10; Ny = 8;                % lattice size
dx = 5e-3; dy = 5e-3;           % rest spacing [m]
A0 = 1e-6;                      % spring cross-section [m^2]
G  = 6e3;                       % shear modulus [Pa]  (≈4-6 kPa ExM gel)
m  = 1e-3;                      % node mass [kg]
damp = 0.07;                    % velocity damping (0 = none)

dt  = 5e-4;                     % time step [s]
T   = 1.5;                      % total time  [s]
nSteps = round(T/dt);

pullSpeed = 10e-3;              % pull right edge (m/s) in +x

%% 2.  Build node list
[xGrid, yGrid] = meshgrid((0:Nx-1)*dx, (0:Ny-1)*dy);
pos  = [xGrid(:), yGrid(:)];    % (Nx*Ny) × 2
vel  = zeros(size(pos));        % initial v = 0

nNodes = size(pos,1);

% index helpers
idx = @(i,j) (j-1)*Nx + i;      % 1-based linear index

% connectivity: horizontal & vertical springs
sprI = []; sprJ = [];
for j = 1:Ny
    for i = 1:Nx
        if i < Nx      % right neighbour
            sprI(end+1) = idx(i,j);
            sprJ(end+1) = idx(i+1,j);
        end
        if j < Ny      % upper neighbour
            sprI(end+1) = idx(i,j);
            sprJ(end+1) = idx(i,j+1);
        end
    end
end
sprI = sprI(:); sprJ = sprJ(:);      % column vectors
nSpr = numel(sprI);

% rest lengths
r0   = pos(sprJ,:) - pos(sprI,:);
L0   = sqrt(sum(r0.^2,2));            % nSpr × 1

%% 3.  Pinned nodes (left edge)
pinned = pos(:,1) < 1e-9;             % boolean mask

%% 4.  Pre-allocate force array
force = zeros(nNodes,2);

%% 5.  Figure for animation
figure('Name','Neo-Hookean sheet'); axis equal off
hLines = plot(0,0,'k-'); hold on; hMass = plot(0,0,'bo','MarkerSize',4,'MarkerFaceColor','b');
drawnow;

%% 6.  Time integration (velocity-Verlet)
for step = 1:nSteps
    t = step*dt;
    
    % ==== Pull right edge in +x ====
    % identify right-edge nodes (largest x initially)
    rightEdge = pos(:,1) > ( (Nx-1)*dx - 1e-9 );
    vel(rightEdge,1) = pullSpeed;     % impose velocity
    
    % ===== First half-step velocity update =====
    accel = force / m;                % from previous loop (zeros at start)
    vel   = vel + 0.5*dt*accel;
    vel   = vel * (1-damp*dt);        % simple damping
    
    % ===== Position update =====
    pos   = pos + dt*vel;
    pos(pinned,:) = [xGrid(pinned), yGrid(pinned)];   % keep pinned fixed
    
    % ===== Zero forces and accumulate spring forces =====
    force(:) = 0;
    % vector from i → j
    rij = pos(sprJ,:) - pos(sprI,:);
    L   = sqrt(sum(rij.^2,2));                % nSpr × 1 current lengths
    lambda = L./L0;                           % stretch ratios
    % scalar magnitude (nSpr × 1)
    Fmag = A0 .* G .* (1 - (L0./L).^3);
    % unit vectors
    rHat = rij ./ L;                          % nSpr × 2
    Fvec = Fmag .* rHat;                      % broadcast
    
    % accumulate equal & opposite forces
    for s = 1:nSpr
        i = sprI(s);  j = sprJ(s);
        force(i,:) = force(i,:) + Fvec(s,:);
        force(j,:) = force(j,:) - Fvec(s,:);
    end
    
    % ===== Second half-step velocity update =====
    accel = force / m;
    vel   = vel + 0.5*dt*accel;
    vel(pinned,:) = 0;                        % pinned → v = 0
    
    % ===== Plot (every few steps) =====
    if mod(step,10)==1 || step==nSteps
        set(hLines,'XData',[pos(sprI,1) pos(sprJ,1)]',...
                    'YData',[pos(sprI,2) pos(sprJ,2)]');
        set(hMass,'XData',pos(:,1),'YData',pos(:,2));
        title(sprintf('t = %.3f s',t));
        drawnow;
    end
end