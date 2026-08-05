"""
Contract between the signal API and the freqtrade strategy.

The two sides are tested in different environments: the API here, and
user_data/strategies/EnsembleSignalStrategy.py in the freqtrade job against a
fake SignalClient with hand-written payloads. Nothing checked that the fakes
still resemble what the API emits, so renaming a field on either side would
leave both suites green while the bot silently stopped entering trades.

These tests read the strategy's source with `ast` rather than importing it, so
they run in the cheap backend job without freqtrade installed.
"""

import ast
import dataclasses
from pathlib import Path

import pytest

from app.services.signal_service import Signal

STRATEGY_PATH = (
    Path(__file__).resolve().parents[1]
    / "user_data"
    / "strategies"
    / "EnsembleSignalStrategy.py"
)


def _strategy_ast() -> ast.Module:
    return ast.parse(STRATEGY_PATH.read_text())


def _signal_key_accesses() -> list[ast.AST]:
    """Every `signal.get("x")` and `signal["x"]` node in the strategy."""
    nodes = []
    for node in ast.walk(_strategy_ast()):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "signal"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            nodes.append(node)
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "signal"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            nodes.append(node)
    return nodes


def _key_of(node: ast.AST) -> str:
    return node.args[0].value if isinstance(node, ast.Call) else node.slice.value


def test_the_parser_actually_finds_something():
    """A silently-empty parse would make every assertion below vacuous."""
    keys = {_key_of(node) for node in _signal_key_accesses()}
    assert {"stale", "direction", "confidence"} <= keys


def test_strategy_only_reads_fields_the_api_produces():
    """Rename a Signal field and this fails, naming the strategy as consumer."""
    produced = {field.name for field in dataclasses.fields(Signal)}
    consumed = {_key_of(node) for node in _signal_key_accesses()}

    missing = consumed - produced
    assert not missing, (
        f"EnsembleSignalStrategy reads signal fields the API does not emit: "
        f"{sorted(missing)}. API emits: {sorted(produced)}"
    )


def test_stale_defaults_to_true_so_a_missing_field_blocks_entry():
    """The fail-closed default (R9).

    `signal.get("stale", True)` means a payload without the field is treated
    as stale. Flipping that default to False, or dropping it, would let the
    bot enter on data it cannot vouch for - which is exactly the situation
    production is in right now, with klines days old.
    """
    stale_reads = [
        node for node in _signal_key_accesses() if _key_of(node) == "stale"
    ]
    assert stale_reads, "strategy no longer checks the stale flag at all"

    for node in stale_reads:
        assert isinstance(node, ast.Call), (
            "stale is read with signal['stale'], which raises KeyError instead "
            "of failing closed; use signal.get('stale', True)"
        )
        assert len(node.args) == 2, "signal.get('stale') has no explicit default"
        default = node.args[1]
        assert isinstance(default, ast.Constant) and default.value is True, (
            "stale must default to True so an absent field blocks entry"
        )


@pytest.mark.parametrize("direction", ["long", "flat"])
def test_directions_the_strategy_branches_on_are_ones_the_api_can_emit(direction):
    """Spot-only: the API never emits "short", and the strategy never asks."""
    compared = set()
    for node in ast.walk(_strategy_ast()):
        if isinstance(node, ast.Compare) and isinstance(node.left, (ast.Call, ast.Subscript)):
            try:
                if _key_of(node.left) != "direction":
                    continue
            except (AttributeError, IndexError):
                continue
            for comparator in node.comparators:
                if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                    compared.add(comparator.value)

    assert compared, "strategy no longer branches on direction"
    assert compared <= {"long", "flat"}, (
        f"strategy branches on directions the API cannot emit: "
        f"{sorted(compared - {'long', 'flat'})}"
    )
    assert direction in compared
