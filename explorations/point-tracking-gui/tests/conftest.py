import os, sys
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

SIM = os.path.normpath(os.path.join(ROOT, "..", "expansion-camera-sim"))


@pytest.fixture
def sim_frame_path():
    p = os.path.join(SIM, "tiffs", "expansion_l1p00x.tif")
    if not os.path.exists(p):
        pytest.skip("expansion-camera-sim frames not generated")
    return p


# The optics params the simulator applied (SimConfig defaults) -> the exact
# correction that should flatten and straighten the frame.
@pytest.fixture
def sim_optics():
    return dict(vig_strength=0.88, vig_power=1.8, k1=-0.05, k2=-0.01)
