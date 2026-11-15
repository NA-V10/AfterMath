from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import settings

from app.core.config import REPO_ROOT
from app.graph.dataset import DatasetFiles, load_dataset_dir, to_snapshot
from app.graph.model import TwinSnapshot
from app.graph.twin_graph import TwinGraph

settings.register_profile("ci", max_examples=200, deadline=None)
settings.register_profile("nightly", max_examples=2000, deadline=None)
settings.load_profile("ci")

DATASET_DIR = REPO_ROOT / "data" / "synthetic" / "meridian-valley"
SCENARIOS_DIR = REPO_ROOT / "data" / "scenarios"


@pytest.fixture(scope="session")
def dataset_dir() -> Path:
    return DATASET_DIR


@pytest.fixture(scope="session")
def dataset_files() -> DatasetFiles:
    return load_dataset_dir(DATASET_DIR)[0]


@pytest.fixture(scope="session")
def district(dataset_files: DatasetFiles) -> TwinSnapshot:
    return to_snapshot(dataset_files)


@pytest.fixture(scope="session")
def district_graph(district: TwinSnapshot) -> TwinGraph:
    return TwinGraph(district)
