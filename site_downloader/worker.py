"""Worker thread integration between PySide6 UI and the downloader."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from .downloader import DownloadContext, DownloadOptions, SiteDownloader


@dataclass
class WorkerConfig:
    url: str
    destination: Path
    options: DownloadOptions


class DownloadWorker(QThread):
    log_signal = Signal(str)
    progress_signal = Signal(int, int, int)  # pages_done, pages_total, assets
    finished_signal = Signal()
    error_signal = Signal(str)

    def __init__(self, config: WorkerConfig) -> None:
        super().__init__()
        self._config = config
        self._downloader: Optional[SiteDownloader] = None
        self._context: Optional[DownloadContext] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def run(self) -> None:
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._run_async())
        except Exception as exc:
            self.error_signal.emit(str(exc))
        else:
            self.finished_signal.emit()
        finally:
            if self._loop:
                self._loop.close()
                self._loop = None

    async def _run_async(self) -> None:
        context = DownloadContext(
            base_url=self._config.url,
            destination=self._config.destination,
            options=self._config.options,
            log=self._emit_log,
            on_progress=self._emit_progress,
        )
        self._context = context
        downloader = SiteDownloader(context)
        self._downloader = downloader
        await downloader.run()

    def stop(self) -> None:
        if self._context:
            self._context.stop_event.set()
        if self._downloader and self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._downloader.stop(), self._loop)

    def _emit_log(self, message: str) -> None:
        self.log_signal.emit(message)

    def _emit_progress(self, pages_done: int, pages_total: int, assets: int) -> None:
        self.progress_signal.emit(pages_done, pages_total, assets)
