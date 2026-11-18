% File: interpForceQuad.m
% ------------------------------------------
% Local interpolation of Y vs. X using up to 2nd‐order fits.
% Falls back to linear or constant if X’s aren’t distinct,
% and uses centering & scaling for numerical stability.

function Yq = interpForceQuad(X, Y, Xq)
    X  = X(:);      % make X a column
    Y  = Y(:);      % make Y a column
    Xq = Xq(:);     % make Xq a column
    n  = numel(X);  % how many data points we have
    Yq = nan(size(Xq)); %creates the interpolated point vector and fills it with nan

    for i = 1:numel(Xq)
        x0 = Xq(i);
        % find window of up to 3 points around x0
       k = find(X <= x0, 1, 'last');
       if isempty(k)
            idx = 1:3;          % x0 is left of all data -> first 3 points
        elseif k >= n
            idx = n-2:n;        % x0 is at/after the last point -> last 3 points
        elseif k == 1
            idx = 1:3;          % near the very start -> first 3
        else
            idx = k-1:k+1;      % typical case -> one on the left, itself, one on
       end
        xi = X(idx);            % the local X's
        yi = Y(idx);            % the matching Y's

        % drop duplicate xi
        [xu, uidx] = unique(xi, 'stable');
        yu         = yi(uidx);

        % choose degree = min(2, #xu–1)
        deg = min(2, numel(xu)-1);

        switch deg
            case 2
                % quadratic with centering & scaling
                [p,S,mu] = polyfit(xu, yu, 2);
                Yq(i)    = polyval(p, x0, S, mu);
            case 1
                % linear interpolation
                Yq(i)    = interp1(xu, yu, x0, 'linear');
            otherwise
                % constant (all x the same)
                Yq(i)    = yu(1);
        end
    end
end