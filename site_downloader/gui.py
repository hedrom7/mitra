"""PySide6 application entry point for the site downloader."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)

from .downloader import DownloadOptions
from .worker import DownloadWorker, WorkerConfig


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Mitra")
        self.resize(900, 650)
        self._worker: DownloadWorker | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://example.com")

        self.dest_input = QLineEdit()
        self.dest_input.setPlaceholderText("Kayıt klasörü seçin…")
        self.dest_input.setReadOnly(True)

        self.browse_btn = QPushButton("Gözat…")
        self.browse_btn.clicked.connect(self._choose_dir)

        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(0, 10)
        self.depth_spin.setValue(1)
        self.depth_spin.setToolTip("Maksimum tarama derinliği. 0 = sadece ilk sayfa.")

        self.scroll_spin = QSpinBox()
        self.scroll_spin.setRange(0, 30)
        self.scroll_spin.setValue(6)
        self.scroll_spin.setToolTip("Lazy-load içerik için kaydırma adımı sayısı.")

        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        self.concurrent_spin.setValue(3)
        self.concurrent_spin.setToolTip("Eş zamanlı indirilen sayfa sayısı.")

        self.filesize_spin = QDoubleSpinBox()
        self.filesize_spin.setRange(1.0, 500.0)
        self.filesize_spin.setValue(50.0)
        self.filesize_spin.setSuffix(" MB")
        self.filesize_spin.setToolTip("Bu boyuttan büyük dosyalar atlanır.")

        self.headless_cb = QCheckBox("Headless tarayıcı")
        self.headless_cb.setChecked(True)

        self.resume_cb = QCheckBox("Devam et (mevcut dosyaları atla)")
        self.resume_cb.setChecked(True)

        self.start_btn = QPushButton("Başlat")
        self.start_btn.clicked.connect(self._start)

        self.stop_btn = QPushButton("Durdur")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setValue(0)

        self.stats_label = QLabel("Hazır")

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)

        # Layout
        w = QWidget()
        g = QGridLayout()
        w.setLayout(g)

        row = 0
        g.addWidget(QLabel("Site URL:"), row, 0)
        g.addWidget(self.url_input, row, 1, 1, 3)

        row += 1
        path_row = QHBoxLayout()
        path_row.addWidget(self.dest_input)
        path_row.addWidget(self.browse_btn)
        g.addWidget(QLabel("Kayıt yeri:"), row, 0)
        g.addLayout(path_row, row, 1, 1, 3)

        row += 1
        g.addWidget(QLabel("Derinlik:"), row, 0)
        g.addWidget(self.depth_spin, row, 1)
        g.addWidget(QLabel("Kaydırma:"), row, 2)
        g.addWidget(self.scroll_spin, row, 3)

        row += 1
        g.addWidget(QLabel("Eş zamanlı:"), row, 0)
        g.addWidget(self.concurrent_spin, row, 1)
        g.addWidget(QLabel("Maks dosya:"), row, 2)
        g.addWidget(self.filesize_spin, row, 3)

        row += 1
        g.addWidget(self.headless_cb, row, 0, 1, 2)
        g.addWidget(self.resume_cb, row, 2, 1, 2)

        row += 1
        btns = QHBoxLayout()
        btns.addWidget(self.start_btn)
        btns.addWidget(self.stop_btn)
        g.addLayout(btns, row, 0, 1, 4)

        row += 1
        g.addWidget(self.progress_bar, row, 0, 1, 4)

        row += 1
        g.addWidget(self.stats_label, row, 0, 1, 4)

        row += 1
        g.addWidget(QLabel("Log:"), row, 0)

        row += 1
        g.addWidget(self.log_view, row, 0, 1, 4)

        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        g.setRowStretch(row, 1)

        self.setCentralWidget(w)

    # -- slots ------------------------------------------------------------

    def _choose_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Kayıt klasörü seçin")
        if d:
            self.dest_input.setText(d)

    def _start(self) -> None:
        url = self.url_input.text().strip()
        dest = self.dest_input.text().strip()

        if not url:
            QMessageBox.warning(self, "Eksik URL", "Lütfen bir site URL'si girin.")
            return
        if not dest:
            QMessageBox.warning(
                self, "Eksik klasör", "Lütfen bir kayıt klasörü seçin."
            )
            return

        opts = DownloadOptions(
            max_depth=self.depth_spin.value(),
            scroll_steps=self.scroll_spin.value(),
            headless=self.headless_cb.isChecked(),
            max_concurrent=self.concurrent_spin.value(),
            max_file_size_mb=self.filesize_spin.value(),
            resume=self.resume_cb.isChecked(),
        )

        config = WorkerConfig(url=url, destination=Path(dest), options=opts)
        worker = DownloadWorker(config)
        worker.log_signal.connect(self._log)
        worker.progress_signal.connect(self._on_progress)
        worker.finished_signal.connect(self._on_finished)
        worker.error_signal.connect(self._on_error)

        self._worker = worker
        self._log("İndirme başlatılıyor…")
        self._set_running(True)
        self.progress_bar.setValue(0)
        self.stats_label.setText("Başlatılıyor…")
        worker.start()

    def _stop(self) -> None:
        if self._worker:
            self._log("Durdurma isteği gönderildi…")
            self._worker.stop()
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.url_input.setEnabled(not running)
        self.dest_input.setEnabled(not running)
        self.browse_btn.setEnabled(not running)
        self.depth_spin.setEnabled(not running)
        self.scroll_spin.setEnabled(not running)
        self.concurrent_spin.setEnabled(not running)
        self.filesize_spin.setEnabled(not running)
        self.headless_cb.setEnabled(not running)
        self.resume_cb.setEnabled(not running)

    def _log(self, msg: str) -> None:
        self.log_view.appendPlainText(msg)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_progress(self, pages_done: int, pages_total: int, assets: int) -> None:
        if pages_total > 0:
            pct = int(pages_done / pages_total * 100)
            self.progress_bar.setValue(pct)
        self.stats_label.setText(
            f"{pages_done}/{pages_total} sayfa  |  {assets} asset kaydedildi"
        )

    def _on_finished(self) -> None:
        self._log("İndirme tamamlandı.")
        self.progress_bar.setValue(100)
        self.stats_label.setText("Tamamlandı!")
        self._set_running(False)
        self._worker = None

    def _on_error(self, msg: str) -> None:
        QMessageBox.critical(self, "Hata", msg)
        self._log(f"HATA: {msg}")
        self._set_running(False)
        self._worker = None


def run() -> None:
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()
