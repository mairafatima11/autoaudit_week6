from __future__ import annotations

from typing import Any, Callable


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}

    def register(self, name: str, tool: Callable[..., Any]) -> None:
        self._tools[name] = tool

    def get(self, name: str) -> Callable[..., Any]:
        return self._tools[name]

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())