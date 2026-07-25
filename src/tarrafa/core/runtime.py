# -*- coding: utf-8 -*-
"""Process-wide runtime context (global CLI flags + active run)."""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tarrafa.core.config import TarrafaConfig
    from tarrafa.core.run import RunSession

_RUNTIME: ContextVar["Runtime | None"] = ContextVar("tarrafa_runtime", default=None)


@dataclass
class Runtime:
    verbose: int = 0
    quiet: bool = False
    force: bool = False
    no_clobber: bool = False
    timeout: float | None = None
    out_dir: Path | None = None
    json_logs: bool = False
    config: TarrafaConfig | None = None
    run: RunSession | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def workspace(self) -> Path | None:
        if self.config and self.config.workspace:
            return self.config.workspace
        return None


def get_runtime() -> Runtime:
    return _RUNTIME.get() or Runtime()


def set_runtime(rt: Runtime) -> None:
    _RUNTIME.set(rt)


def reset_runtime() -> None:
    _RUNTIME.set(None)
