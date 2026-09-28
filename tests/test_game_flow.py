"""Drive the real game through every state headlessly."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))


def test_full_walkthrough(tmp_path):
    from smoke_test import Walkthrough
    shots = Walkthrough(str(tmp_path)).play()
    assert len(shots) >= 20
    for path in shots:
        assert os.path.getsize(path) > 1000
