import pytest

from exm_explorer import scenario, sim
from exm_explorer.grid import load_grid


@pytest.fixture(scope="session")
def grid():
    return load_grid()


@pytest.fixture(scope="session")
def legacy_sim(grid):
    """Exact render of the exm_sim batch run (kinematic, three patches, seed 7)."""
    return sim.simulate(scenario.legacy_scenario(), grid)
