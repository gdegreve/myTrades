"""Type definitions for strategy parameters and definitions."""

from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


ParamType = Literal["int", "float", "bool", "choice"]
ParamGroup = Literal["main", "filters", "stops"]


@dataclass
class ParamSpec:
    """Parameter specification for a strategy."""
    id: str
    label: str
    group: ParamGroup
    ptype: ParamType
    default: int | float | bool | str
    min_val: int | float | None = None
    max_val: int | float | None = None
    step: int | float | None = None
    choices: list[tuple[str, str]] | None = None  # [(label, value), ...]


@dataclass
class StrategyDef:
    """Complete strategy definition."""
    key: str
    name: str
    description: str
    param_specs: list[ParamSpec]
    default_params: dict[str, int | float | bool | str]
