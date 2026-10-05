"""Unit tests for the end-to-end pipeline runner (subprocess calls are mocked)."""
from __future__ import annotations

import subprocess
import sys

import pytest

from src import pipeline

pytestmark = pytest.mark.unit


@pytest.fixture
def calls(monkeypatch):
    recorded: list[list[str]] = []

    def fake_run(cmd, check):
        assert check is True
        recorded.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    return recorded


def modules(recorded: list[list[str]]) -> list[str]:
    return [cmd[-1] for cmd in recorded]


def test_full_run_executes_every_stage_in_order(calls):
    assert pipeline.main([]) == 0
    assert modules(calls) == [module for _, module, _ in pipeline.STAGES]
    assert all(cmd[:2] == [sys.executable, "-m"] for cmd in calls)


def test_skip_db_omits_database_stages(calls, capsys):
    assert pipeline.main(["--skip-db"]) == 0
    assert modules(calls) == ["src.generate_data", "src.data_cleaning", "src.analysis_metrics"]
    assert "skipped (--skip-db)" in capsys.readouterr().out


def test_stage_order_cleans_before_loading():
    order = [module for _, module, _ in pipeline.STAGES]
    assert order.index("src.generate_data") < order.index("src.data_cleaning") < order.index("src.load_to_db")


def test_failure_stops_pipeline_and_returns_exit_code(monkeypatch, capsys):
    recorded: list[str] = []

    def failing_run(cmd, check):
        recorded.append(cmd[-1])
        if cmd[-1] == "src.data_cleaning":
            raise subprocess.CalledProcessError(3, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(pipeline.subprocess, "run", failing_run)
    assert pipeline.main([]) == 3
    assert recorded == ["src.generate_data", "src.data_cleaning"]
    assert "src.data_cleaning exited with code 3" in capsys.readouterr().err
