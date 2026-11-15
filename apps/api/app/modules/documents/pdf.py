from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.config import settings
from app.integrations.pdf_render import PdfRenderError

_CANDIDATE_BINARIES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "msedge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/chromium",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


def find_browser() -> str | None:
    configured = settings.PDF_BROWSER_PATH
    if configured:
        return configured if Path(configured).exists() else None
    for candidate in _CANDIDATE_BINARIES:
        found = shutil.which(candidate) or (
            candidate if Path(candidate).exists() else None
        )
        if found:
            return found
    return None


class ChromiumPdfRenderer:
    name = "chromium"

    def __init__(self, binary: str | None = None) -> None:
        self._binary = binary or find_browser()

    def is_available(self) -> bool:
        return self._binary is not None

    async def render(self, html: str, *, timeout_seconds: int = 60) -> bytes:
        if self._binary is None:
            raise PdfRenderError(
                "No PDF renderer is available. Install a Chromium-family browser "
                "or set PDF_BROWSER_PATH to one. The HTML document renders "
                "without it."
            )
        return await asyncio.to_thread(self._print, html, timeout_seconds)

    def _print(self, html: str, timeout_seconds: int) -> bytes:
        assert self._binary is not None
        with tempfile.TemporaryDirectory(prefix="acacia-pdf-") as workspace:
            root = Path(workspace)
            source = root / "document.html"
            target = root / "document.pdf"
            source.write_text(html, encoding="utf-8")

            result = subprocess.run(  # noqa: S603 - fixed argv, no shell
                self._command(source, target, root),
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            if not target.exists():
                detail = (result.stderr or result.stdout or b"").decode(
                    "utf-8", "replace"
                )
                raise PdfRenderError(
                    f"{self.name} produced no PDF (exit {result.returncode}): "
                    f"{detail.strip()[:400]}"
                )
            return target.read_bytes()

    def _command(self, source: Path, target: Path, workspace: Path) -> list[str]:
        assert self._binary is not None
        return [
            self._binary,
            "--headless",
            "--disable-gpu",
            f"--user-data-dir={workspace / 'profile'}",
            "--no-pdf-header-footer",
            "--disable-extensions",
            "--disable-dev-shm-usage",
            *(["--no-sandbox"] if settings.PDF_BROWSER_NO_SANDBOX else []),
            f"--virtual-time-budget={settings.PDF_RENDER_SETTLE_MS}",
            f"--print-to-pdf={target}",
            source.as_uri(),
        ]


def default_renderer() -> ChromiumPdfRenderer:
    return ChromiumPdfRenderer()
