# -*- coding: utf-8 -*-
import copy
import glob
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
SKILL = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

EXAMPLES = os.path.join(SKILL, "examples")
CASES = os.path.join(SKILL, "cases")
URGENCH = os.path.join(EXAMPLES, "urgench-apartment", "project.json")
STUDIO = os.path.join(EXAMPLES, "studio-minimal", "project.json")


def case_dirs():
    out = []
    for root in (EXAMPLES, CASES):
        for d in sorted(glob.glob(os.path.join(root, "*"))):
            if os.path.isfile(os.path.join(d, "project.json")) and os.path.isfile(os.path.join(d, "expected.json")):
                out.append(d)
    return out


@pytest.fixture(scope="session")
def urgench():
    from sdalbum import model
    return model.load(URGENCH)


@pytest.fixture(scope="session")
def studio_data():
    with open(STUDIO, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def make_project(studio_data, tmp_path):
    """Build a Project from the minimal studio after applying `mutate(data)` - for rule tests."""
    from sdalbum import model

    def _make(mutate=None):
        d = copy.deepcopy(studio_data)
        if mutate:
            mutate(d)
        return model.Project(d, os.path.dirname(STUDIO))
    return _make
