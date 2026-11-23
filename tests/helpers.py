import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planner.validate import load_json  # noqa: E402

DATA = ROOT / "data"
ORG_FILES = ["org_small", "org_medium", "org_large", "org_sample_15"]


def org(name):
    return load_json(DATA / f"{name}.json")


def plan():
    return load_json(DATA / "plan_example_mini.json")


def clone(d):
    return copy.deepcopy(d)
