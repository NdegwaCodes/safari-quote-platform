from __future__ import annotations

from typing import Protocol, runtime_checkable


class PdfRenderError(RuntimeError):
    pass


@runtime_checkable
class PdfRenderProvider(Protocol):

    name: str

    def is_available(self) -> bool:
        ...

    async def render(self, html: str, *, timeout_seconds: int = 60) -> bytes:
        ...
