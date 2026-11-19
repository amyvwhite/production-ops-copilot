from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from app.ai import Cache, ModelTurn, ToolCall
from app.loader import load_production

SAMPLE = Path(__file__).resolve().parents[1] / "sample_data"
TODAY = date(2026, 11, 24)


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A private copy of the sample production (tests may edit it)."""
    dest = tmp_path / "data"
    shutil.copytree(SAMPLE, dest)
    return dest


@pytest.fixture
def prod(data_dir: Path):
    return load_production(data_dir)


@pytest.fixture
def cache(tmp_path: Path) -> Cache:
    return Cache(tmp_path / "cache")


class ScriptedModel:
    """A fake ChatModel: plays back a script of turns and records what it was sent.

    Lets the tool loop, citation checks and caching be tested without calling Gemini.
    """

    def __init__(self, turns: list[ModelTurn], extracted: dict | None = None) -> None:
        self.turns = list(turns)
        self.calls: list[list[dict]] = []
        self.extracted = extracted
        self.extract_calls = 0

    def respond(self, system, history, tools):
        self.calls.append([dict(h) for h in history])
        return self.turns.pop(0)

    def extract(self, system, pdf, schema):
        self.extract_calls += 1
        return dict(self.extracted or {})


def tool(name: str, **args) -> ModelTurn:
    return ModelTurn(tool_calls=[ToolCall(name=name, args=args)])


def say(text: str) -> ModelTurn:
    return ModelTurn(text=text)
