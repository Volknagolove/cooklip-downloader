#!/usr/bin/env python3
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

try:
    from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal
    from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QTextCharFormat, QTextCursor
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QFileDialog,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QMenu,
        QMessageBox,
        QSizePolicy,
        QSplitter,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
    from qfluentwidgets import (
        BodyLabel,
        CaptionLabel,
        ComboBox,
        FluentIcon as FIF,
        LineEdit,
        PrimaryPushButton,
        PushButton,
        StrongBodyLabel,
        SubtitleLabel,
        ToolButton,
    )
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Для Fluent UI нужно установить зависимости:\n"
        "py -m pip install PySide6 PySide6-Fluent-Widgets"
    ) from exc

import cooklip_resources_rc
import cooklip_core as core


STATUS_META = {
    "ready": ("Готов", "#475569", "#E2E8F0"),
    "running": ("Скачивается", "#166534", "#DCFCE7"),
    "stopping": ("Остановка", "#92400E", "#FEF3C7"),
    "error": ("Ошибка", "#B91C1C", "#FEE2E2"),
}
INPUT_HEIGHT = 40
BUTTON_HEIGHT = 40
CARD_RADIUS = 18


def app_icon() -> QIcon:
    return QIcon(":/app/cooklip.ico")


class SignalBus(QObject):
    log = Signal(str)
    info = Signal(str)
    error = Signal(str)
    downloadFinished = Signal(bool)
    downloadAdded = Signal(str, str)
    cookieDone = Signal(str)
    cookieError = Signal(str)


class HistoryItemWidget(QFrame):
    openRequested = Signal(dict)
    linkRequested = Signal(dict)
    deleteRequested = Signal(dict)

    def __init__(self, item: dict[str, str], parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("HistoryItem")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 12, 12)
        layout.setSpacing(10)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(2)

        full_path = item.get("path", "")
        file_name = Path(full_path).name if full_path else ""
        parent_path = str(Path(full_path).parent) if full_path else ""
        metrics = self.fontMetrics()
        self.name_label = StrongBodyLabel(metrics.elidedText(file_name, Qt.ElideRight, 250), self)
        self.name_label.setToolTip(full_path)
        self.path_label = CaptionLabel(metrics.elidedText(parent_path, Qt.ElideRight, 320), self)
        self.path_label.setToolTip(parent_path)
        self.path_label.setWordWrap(False)
        self.path_label.setStyleSheet("color: #667085;")

        text_box.addWidget(self.name_label)
        text_box.addWidget(self.path_label)
        layout.addLayout(text_box, 1)

        self.open_btn = self._make_tool_button(FIF.PLAY, "Открыть файл", "#16A34A", "#DCFCE7")
        self.link_btn = self._make_tool_button(FIF.LINK, "Открыть исходную ссылку", "#2563EB", "#DBEAFE")
        self.delete_btn = self._make_tool_button(FIF.DELETE, "Удалить файл", "#DC2626", "#FEE2E2")

        self.open_btn.clicked.connect(lambda: self.openRequested.emit(self.item))
        self.link_btn.clicked.connect(lambda: self.linkRequested.emit(self.item))
        self.delete_btn.clicked.connect(lambda: self.deleteRequested.emit(self.item))

        layout.addWidget(self.open_btn)
        layout.addWidget(self.link_btn)
        layout.addWidget(self.delete_btn)

    def _make_tool_button(self, icon, tooltip: str, fg: str, bg: str):
        button = ToolButton(icon, self)
        button.setToolTip(tooltip)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedSize(42, 42)
        hover_bg = {
            "#16A34A": "#CFEFD8",
            "#2563EB": "#D7E6FD",
            "#DC2626": "#F9D6D6",
        }.get(fg, bg)
        button.setStyleSheet(
            f"""
            ToolButton {{
                background: {bg};
                color: {fg};
                border: none;
                border-radius: 21px;
            }}
            ToolButton:hover {{
                background: {hover_bg};
                color: {fg};
            }}
            """
        )
        return button


class FluentDownloader(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(core.APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1020, 600)
        self.setMinimumSize(1020, 600)
        self.setFont(QFont("Segoe UI", 10))

        self.settings = core.load_settings()
        self.downloads_history = list(self.settings.get("downloads_history", []))
        self.download_thread = None
        self.cookies_thread = None
        self.download_process: subprocess.Popen | None = None
        self.stop_requested = False
        self.bus = SignalBus()
        self.history_widgets: list[tuple[QListWidgetItem, HistoryItemWidget]] = []

        self._build_ui()
        self._connect_signals()
        self._load_settings()
        self.set_status("ready")

    def _build_ui(self):
        self.setStyleSheet(
            """
            QWidget {
                background: #F7F8FA;
                color: #111827;
                font-family: "Segoe UI";
                font-size: 13px;
            }
            BodyLabel, CaptionLabel, StrongBodyLabel, SubtitleLabel {
                background: transparent;
            }
            QFrame#Card {
                background: white;
                border: 1px solid #E5E7EB;
                border-radius: 18px;
            }
            QFrame#HistoryItem {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                border-radius: 16px;
            }
            QTextEdit {
                background: white;
                border: 1px solid #E5E7EB;
                border-radius: 16px;
                padding: 10px;
                selection-background-color: #BFDBFE;
            }
            QListWidget {
                background: transparent;
                border: none;
            }
            QSplitter::handle {
                background: #D8DEE8;
                width: 8px;
                border-radius: 4px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title_box = QVBoxLayout()
        title_box.setSpacing(4)
        self.subtitle_label = CaptionLabel(
            "Некоторые видео требуют авторизации. Для этого нужны куки.\n"
            "1) запустите Edge для куков  2) авторизуйтесь  3) нажмите «Обновить куки из Edge»  4) проверьте путь к cookies.txt",
            self,
        )
        self.subtitle_label.setStyleSheet("color: #667085;")
        self.subtitle_label.setWordWrap(True)
        title_box.addWidget(self.subtitle_label)
        header.addLayout(title_box, 1)

        self.status_chip = QLabel(self)
        self.status_chip.setAlignment(Qt.AlignCenter)
        self.status_chip.setMinimumHeight(36)
        self.status_chip.setMinimumWidth(132)
        header.addWidget(self.status_chip, 0, Qt.AlignRight)
        root.addLayout(header)

        self.form_card = self._make_card()
        form_layout = QGridLayout(self.form_card)
        form_layout.setContentsMargins(16, 12, 16, 14)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(4)
        for col in range(5):
            form_layout.setColumnStretch(col, 1 if col in (1, 2) else 0)
        form_layout.setColumnMinimumWidth(0, 104)
        form_layout.setColumnMinimumWidth(3, 110)
        form_layout.setColumnMinimumWidth(4, 110)

        self.url_edit = LineEdit(self)
        self.download_dir_edit = LineEdit(self)
        self.cookies_path_edit = LineEdit(self)
        self.format_combo = ComboBox(self)
        self.quality_combo = ComboBox(self)

        for widget in (
            self.url_edit,
            self.download_dir_edit,
            self.cookies_path_edit,
            self.format_combo,
            self.quality_combo,
        ):
            widget.setFixedHeight(36)

        self.download_button = PrimaryPushButton("Скачать", self, FIF.DOWN)
        self.stop_button = PushButton("Стоп", self, FIF.CLOSE)
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet(
            """
            PushButton {
                background: #FCE7F3;
                color: #9F2957;
                border: none;
                border-radius: 10px;
                padding: 6px 12px;
                font-weight: 600;
                outline: none;
            }
            PushButton:hover {
                background: #F9D9EA;
            }
            PushButton:focus {
                border: none;
                outline: none;
            }
            """
        )
        self.download_button.setStyleSheet(
            """
            PrimaryPushButton {
                background: #DCEDE0;
                color: #28543A;
                border: none;
                border-radius: 12px;
                padding: 6px 12px;
                font-weight: 600;
                outline: none;
            }
            PrimaryPushButton:hover {
                background: #D4E8D9;
            }
            PrimaryPushButton:focus {
                border: none;
                outline: none;
            }
            """
        )
        self.download_button.setIcon(QIcon())
        self.stop_button.setIcon(QIcon())
        self.download_button.setFixedHeight(36)
        self.stop_button.setFixedHeight(36)
        self.download_button.setMinimumWidth(118)
        self.stop_button.setMinimumWidth(118)

        self.pick_dir_button = PushButton("Выбрать", self)
        self.open_dir_button = PushButton("Открыть", self)
        self.pick_cookies_button = PushButton("Выбрать", self)
        self.refresh_cookies_button = PushButton("Обновить куки из Edge", self)
        self.launch_edge_button = PushButton("Запустить Edge для куков", self)
        self.check_deps_button = PushButton("Проверить зависимости", self)
        self.save_settings_button = PushButton("Сохранить настройки", self)
        for button in (
            self.download_button,
            self.stop_button,
            self.pick_dir_button,
            self.open_dir_button,
            self.pick_cookies_button,
            self.refresh_cookies_button,
            self.launch_edge_button,
            self.check_deps_button,
            self.save_settings_button,
        ):
            button.setFixedHeight(36)
            button.setMinimumWidth(104)
            existing_style = button.styleSheet()
            button.setStyleSheet(
                existing_style
                + """
                PushButton:focus {
                    outline: none;
                }
                """
            )

        form_layout.addWidget(BodyLabel("Ссылка", self), 0, 0, alignment=Qt.AlignVCenter | Qt.AlignLeft)
        form_layout.addWidget(self.url_edit, 0, 1, 1, 2)
        form_layout.addWidget(self.download_button, 0, 3)
        form_layout.addWidget(self.stop_button, 0, 4)

        form_layout.addWidget(BodyLabel("Папка загрузки", self), 1, 0, alignment=Qt.AlignVCenter | Qt.AlignLeft)
        form_layout.addWidget(self.download_dir_edit, 1, 1, 1, 2)
        form_layout.addWidget(self.pick_dir_button, 1, 3)
        form_layout.addWidget(self.open_dir_button, 1, 4)

        form_layout.addWidget(BodyLabel("Файл куков", self), 2, 0, alignment=Qt.AlignVCenter | Qt.AlignLeft)
        form_layout.addWidget(self.cookies_path_edit, 2, 1, 1, 3)
        form_layout.addWidget(self.pick_cookies_button, 2, 4)

        cookies_row = QHBoxLayout()
        cookies_row.setSpacing(10)
        cookies_row.addWidget(self.refresh_cookies_button)
        cookies_row.addWidget(self.launch_edge_button)
        cookies_row.addStretch(1)
        form_layout.addLayout(cookies_row, 3, 1, 1, 4)

        format_row = QHBoxLayout()
        format_row.setSpacing(8)
        format_row.addWidget(BodyLabel("Формат", self))
        self.format_combo.setMaximumWidth(164)
        format_row.addWidget(self.format_combo)
        format_row.addSpacing(8)
        format_row.addWidget(BodyLabel("Качество", self))
        self.quality_combo.setMaximumWidth(164)
        format_row.addWidget(self.quality_combo)
        format_row.addStretch(1)
        form_layout.addLayout(format_row, 4, 0, 1, 5)

        self.deps_label = CaptionLabel("", self)
        self.deps_label.setStyleSheet("color: #667085;")
        deps_row = QHBoxLayout()
        deps_row.setSpacing(10)
        deps_row.addWidget(self.deps_label)
        deps_row.addWidget(self.check_deps_button)
        deps_row.addStretch(1)
        form_layout.addLayout(deps_row, 5, 0, 1, 3)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        action_row.addStretch(1)
        action_row.addWidget(self.save_settings_button)
        form_layout.addLayout(action_row, 5, 3, 1, 2)

        root.addWidget(self.form_card)

        self.splitter = QSplitter(Qt.Horizontal, self)
        self.history_card = self._make_card()
        self.log_card = self._make_card()
        self._build_history_panel()
        self._build_log_panel()
        self.splitter.addWidget(self.history_card)
        self.splitter.addWidget(self.log_card)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        root.addWidget(self.splitter, 1)
        QTimer.singleShot(0, self._init_splitter)

    def _make_card(self):
        card = QFrame(self)
        card.setObjectName("Card")
        return card

    def _build_history_panel(self):
        layout = QVBoxLayout(self.history_card)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        title = StrongBodyLabel("Скачанные файлы", self)
        layout.addWidget(title)
        self.history_list = QListWidget(self)
        self.history_list.setSpacing(8)
        self.history_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.history_list.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.history_list.verticalScrollBar().setSingleStep(12)
        self.history_list.horizontalScrollBar().setSingleStep(12)
        layout.addWidget(self.history_list, 1)

    def _build_log_panel(self):
        layout = QVBoxLayout(self.log_card)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addStretch(1)
        self.clear_log_button = PushButton("Очистить лог", self)
        self.copy_log_button = PushButton("Копировать лог", self)
        self.clear_log_button.setFixedHeight(36)
        self.copy_log_button.setFixedHeight(36)
        self.clear_log_button.setMinimumWidth(104)
        self.copy_log_button.setMinimumWidth(104)
        top.addWidget(self.clear_log_button)
        top.addWidget(self.copy_log_button)
        layout.addLayout(top)
        self.log_edit = QTextEdit(self)
        self.log_edit.setReadOnly(True)
        layout.addWidget(self.log_edit, 1)

    def _connect_signals(self):
        self.pick_dir_button.clicked.connect(self.pick_download_dir)
        self.open_dir_button.clicked.connect(self.open_download_folder)
        self.pick_cookies_button.clicked.connect(self.pick_cookies_file)
        self.refresh_cookies_button.clicked.connect(self.refresh_cookies)
        self.launch_edge_button.clicked.connect(self.launch_edge)
        self.check_deps_button.clicked.connect(self.check_dependencies)
        self.save_settings_button.clicked.connect(self.persist_settings)
        self.download_button.clicked.connect(self.start_download)
        self.stop_button.clicked.connect(self.stop_download)
        self.clear_log_button.clicked.connect(self.clear_log)
        self.copy_log_button.clicked.connect(self.copy_log)
        self.format_combo.currentTextChanged.connect(self._on_format_changed)

        self.bus.log.connect(self.write_log)
        self.bus.info.connect(self.on_info)
        self.bus.error.connect(self.on_error)
        self.bus.downloadFinished.connect(self.on_download_finished)
        self.bus.downloadAdded.connect(self.add_download_history_item)

    def _load_settings(self):
        self.url_edit.setText(self.settings.get("url", ""))
        self.download_dir_edit.setText(self.settings.get("download_dir", str(core.default_download_dir())))
        self.cookies_path_edit.setText(self.settings.get("cookies_path", str(core.APP_STATE_DIR / core.DEFAULT_COOKIES_FILE)))
        self.format_combo.addItems(core.VIDEO_FORMATS + core.AUDIO_FORMATS)
        self.format_combo.setCurrentText(self.settings.get("format_type", "mp4"))
        self.update_quality_state()
        quality = self.settings.get("quality", "best")
        if quality in [self.quality_combo.itemText(i) for i in range(self.quality_combo.count())]:
            self.quality_combo.setCurrentText(quality)
        self.refresh_dependency_status()
        self.refresh_history_view()

    def _init_splitter(self):
        total = self.splitter.size().width()
        if total > 100:
            self.splitter.setSizes([int(total * 0.55), int(total * 0.45)])

    def collect_settings(self):
        return {
            "url": self.url_edit.text().strip(),
            "download_dir": self.download_dir_edit.text().strip(),
            "cookies_path": self.cookies_path_edit.text().strip(),
            "format_type": self.format_combo.currentText().strip(),
            "quality": self.quality_combo.currentText().strip(),
            "downloads_history": self.downloads_history,
        }

    def persist_settings(self, silent: bool = False):
        self.settings = self.collect_settings()
        core.save_settings(self.settings)
        if not silent:
            self.write_log("Настройки сохранены.")

    def set_status(self, key: str):
        text, fg, bg = STATUS_META[key]
        self.status_chip.setText(text)
        self.status_chip.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:18px; padding:8px 14px; font-weight:600;"
        )

    def set_log_color(self, text: str, color: str):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor = self.log_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text + "\n", fmt)
        self.log_edit.setTextCursor(cursor)
        self.log_edit.ensureCursorVisible()

    def write_log(self, text: str):
        self.set_log_color(text, "#0F172A")

    def clear_log(self):
        self.log_edit.clear()

    def copy_log(self):
        QApplication.clipboard().setText(self.log_edit.toPlainText())
        self.write_log("Лог скопирован в буфер обмена.")

    def on_info(self, text: str):
        self.set_status("ready")
        self.set_log_color(text, "#166534")
        QMessageBox.information(self, core.APP_NAME, text)

    def on_error(self, text: str):
        self.set_status("error")
        self.set_log_color("ОШИБКА: " + text, "#B91C1C")
        QMessageBox.critical(self, core.APP_NAME, text)

    def refresh_history_view(self):
        self.history_list.clear()
        self.history_widgets.clear()
        for item in self.downloads_history:
            list_item = QListWidgetItem(self.history_list)
            widget = HistoryItemWidget(item, self.history_list)
            widget.openRequested.connect(self.open_history_file)
            widget.linkRequested.connect(self.open_history_link)
            widget.deleteRequested.connect(self.delete_history_file)
            list_item.setSizeHint(widget.sizeHint())
            self.history_list.addItem(list_item)
            self.history_list.setItemWidget(list_item, widget)
            self.history_widgets.append((list_item, widget))

    def add_download_history_item(self, file_path: str, source_url: str):
        normalized = str(Path(file_path))
        self.downloads_history = [item for item in self.downloads_history if item.get("path") != normalized]
        self.downloads_history.insert(0, {"path": normalized, "url": source_url})
        self.downloads_history = self.downloads_history[:100]
        self.refresh_history_view()
        self.persist_settings(silent=True)

    def pick_download_dir(self):
        path = QFileDialog.getExistingDirectory(self, core.APP_NAME, self.download_dir_edit.text() or str(core.APP_DIR))
        if path:
            self.download_dir_edit.setText(path)

    def pick_cookies_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            core.APP_NAME,
            str(Path(self.cookies_path_edit.text()).parent if self.cookies_path_edit.text() else core.APP_DIR),
            "Cookie files (*.txt);;All files (*.*)",
        )
        if path:
            self.cookies_path_edit.setText(path)

    def resolve_history_file_path(self, raw_path: str) -> Path | None:
        cleaned = (raw_path or "").strip().strip('"').strip()
        if not cleaned:
            return None

        candidate = Path(cleaned)
        if candidate.exists():
            return candidate

        try:
            resolved = candidate.expanduser().resolve(strict=False)
            if resolved.exists():
                return resolved
        except Exception:
            pass

        download_dir = Path(self.download_dir_edit.text().strip() or str(core.APP_DIR))
        fallback = download_dir / candidate.name
        if fallback.exists():
            return fallback

        try:
            matches = list(download_dir.glob(candidate.name))
            if matches:
                return matches[0]
        except Exception:
            pass

        return None

    def open_download_folder(self):
        path = Path(self.download_dir_edit.text().strip() or str(core.APP_DIR))
        if not path.exists():
            QMessageBox.critical(self, core.APP_NAME, f"Папка не найдена: {path}")
            return
        os.startfile(str(path))

    def open_history_file(self, item: dict[str, str]):
        path = self.resolve_history_file_path(item["path"])
        if not path:
            QMessageBox.critical(
                self,
                core.APP_NAME,
                "Не удалось найти файл на диске.\n\n"
                f"Сохранённый путь: {item['path']}",
            )
            return
        os.startfile(str(path))

    def open_history_link(self, item: dict[str, str]):
        url = item.get("url", "").strip()
        if not url:
            QMessageBox.warning(self, core.APP_NAME, "Для этого файла не сохранена ссылка.")
            return
        webbrowser.open(url)

    def delete_history_file(self, item: dict[str, str]):
        path = Path(item["path"])
        if path.exists():
            prompt = f"Удалить файл?\n{path.name}"
        else:
            prompt = (
                "Файл уже отсутствует на диске.\n"
                f"Убрать запись из списка?\n{path}"
            )

        answer = QMessageBox.question(self, core.APP_NAME, prompt)
        if answer != QMessageBox.Yes:
            return

        if path.exists():
            try:
                path.unlink()
                self.write_log(f"Удалён файл: {path}")
            except Exception as exc:
                QMessageBox.critical(self, core.APP_NAME, f"Не удалось удалить файл: {exc}")
                return
        self.downloads_history = [entry for entry in self.downloads_history if entry.get("path") != item["path"]]
        self.refresh_history_view()
        self.persist_settings(silent=True)

    def update_quality_state(self):
        self.quality_combo.blockSignals(True)
        self.quality_combo.clear()
        self.quality_combo.addItems(core.get_quality_values(self.format_combo.currentText() or "mp4"))
        self.quality_combo.blockSignals(False)

    def _on_format_changed(self):
        previous = self.quality_combo.currentText()
        self.update_quality_state()
        if previous:
            idx = self.quality_combo.findText(previous)
            if idx >= 0:
                self.quality_combo.setCurrentIndex(idx)
        self.refresh_dependency_status()

    def refresh_dependency_status(self):
        ytdlp_found = bool(core.find_ytdlp_executable())
        ffmpeg_found = bool(core.resolve_ffmpeg_executable())
        self.deps_label.setText(
            f"yt-dlp: {'найден' if ytdlp_found else 'не найден'} | "
            f"ffmpeg: {'найден' if ffmpeg_found else 'не найден'}"
        )

    def check_dependencies(self):
        self.refresh_dependency_status()
        missing = core.describe_missing_dependencies(self.format_combo.currentText().strip() or "mp4")
        if missing:
            missing_text = ", ".join(missing)
            QMessageBox.warning(
                self,
                core.APP_NAME,
                "Не найдены обязательные компоненты: "
                + missing_text
                + ".\n\nУстановите их в систему или положите рядом с приложением.",
            )
            self.write_log("Проверка зависимостей: не найдены " + missing_text)
            return
        QMessageBox.information(
            self,
            core.APP_NAME,
            "Все обязательные компоненты найдены.\nМожно запускать загрузку.",
        )
        self.write_log("Проверка зависимостей: yt-dlp и ffmpeg найдены.")

    def launch_edge(self):
        edge_path = core.find_edge_path()
        if not edge_path:
            QMessageBox.critical(self, core.APP_NAME, "Не найден msedge.exe.")
            return
        profile_dir = str(Path.home() / "AppData/Local/Temp/edge-yt-cookies")
        cmd = [
            edge_path,
            "--remote-debugging-port=9222",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&autoplay=1",
        ]
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **core.hidden_subprocess_kwargs(),
        )
        self.write_log("Edge запущен для получения куков.")

    def refresh_cookies(self):
        if self.cookies_thread and self.cookies_thread.is_alive():
            QMessageBox.information(self, core.APP_NAME, "Обновление куков уже выполняется.")
            return
        self.persist_settings(silent=True)
        output_path = Path(self.cookies_path_edit.text().strip())

        def runner():
            try:
                self.bus.log.emit(f"Обновление куков в {output_path}")
                result = core.export_cookies_from_edge(output_path)
                count = result["written"]
                if result["authorized"]:
                    self.bus.info.emit(f"Куки обновлены. Авторизация обнаружена. Записано строк: {count}")
                else:
                    self.bus.info.emit(
                        f"Куки сохранены, но авторизация не обнаружена. "
                        f"Проверьте, что в Edge выполнен вход в аккаунт. Записано строк: {count}"
                    )
            except Exception as exc:
                self.bus.error.emit(core.explain_cookie_refresh_error(exc))

        self.cookies_thread = threading.Thread(target=runner, daemon=True)
        self.cookies_thread.start()

    def validate_inputs(self):
        if not self.url_edit.text().strip():
            QMessageBox.warning(self, core.APP_NAME, "Введите ссылку на видео или плейлист.")
            return False
        if not self.cookies_path_edit.text().strip():
            QMessageBox.warning(self, core.APP_NAME, "Укажите путь к файлу cookies.txt.")
            return False
        if not self.download_dir_edit.text().strip():
            QMessageBox.warning(self, core.APP_NAME, "Укажите папку, куда сохранять скачанные файлы.")
            return False
        missing = core.describe_missing_dependencies(self.format_combo.currentText().strip() or "mp4")
        if missing:
            QMessageBox.critical(
                self,
                core.APP_NAME,
                "Не найдены обязательные компоненты: "
                + ", ".join(missing)
                + ".\n\nСначала установите их или положите рядом с приложением.",
            )
            self.set_status("error")
            return False
        return True

    def choose_playlist_mode(self, url: str) -> str | None:
        mode = core.detect_playlist_mode(url)
        if mode != "mixed":
            return mode

        box = QMessageBox(self)
        box.setWindowTitle(core.APP_NAME)
        box.setIcon(QMessageBox.Question)
        box.setText("Обнаружена ссылка на видео из плейлиста.")
        box.setInformativeText("Что скачать: только текущее видео или весь плейлист?")
        single_button = box.addButton("Только это видео", QMessageBox.AcceptRole)
        playlist_button = box.addButton("Весь плейлист", QMessageBox.YesRole)
        cancel_button = box.addButton("Отмена", QMessageBox.RejectRole)
        box.setDefaultButton(single_button)
        box.exec()

        clicked = box.clickedButton()
        if clicked == single_button:
            return "single"
        if clicked == playlist_button:
            return "playlist"
        if clicked == cancel_button:
            return None
        return None

    def start_download(self):
        if self.download_thread and self.download_thread.is_alive():
            QMessageBox.information(self, core.APP_NAME, "Загрузка уже выполняется.")
            return
        if not self.validate_inputs():
            return

        source_url = self.url_edit.text().strip()
        playlist_mode = self.choose_playlist_mode(source_url)
        if playlist_mode is None:
            self.write_log("Загрузка отменена пользователем.")
            return

        self.persist_settings(silent=True)
        self.stop_requested = False
        self.download_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.set_status("running")

        def runner():
            output_lines: list[str] = []
            final_files: list[str] = []
            final_marker = core.create_final_path_marker()
            try:
                ps_cmd = core.build_powershell_command(
                    url=source_url,
                    cookies_path=self.cookies_path_edit.text().strip(),
                    download_dir=self.download_dir_edit.text().strip(),
                    format_type=self.format_combo.currentText().strip(),
                    quality=self.quality_combo.currentText().strip(),
                    final_path_file=str(final_marker),
                    playlist_mode=playlist_mode,
                )
                deno_exe = core.resolve_deno_executable()
                ffmpeg_exe = core.resolve_ffmpeg_executable()
                self.bus.log.emit("Запуск через PowerShell: " + ps_cmd)

                env = os.environ.copy()
                prepend_dirs = []
                if deno_exe:
                    prepend_dirs.append(str(Path(deno_exe).parent))
                if ffmpeg_exe:
                    prepend_dirs.append(str(Path(ffmpeg_exe).parent))
                if prepend_dirs:
                    env["PATH"] = os.pathsep.join(prepend_dirs) + os.pathsep + env.get("PATH", "")

                self.download_process = subprocess.Popen(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    shell=False,
                    env=env,
                    **core.hidden_subprocess_kwargs(),
                )
                if self.stop_requested:
                    self._terminate_download_process()

                assert self.download_process.stdout is not None
                for line in self.download_process.stdout:
                    cleaned = line.rstrip()
                    output_lines.append(cleaned)
                    self.bus.log.emit(cleaned)

                rc = self.download_process.wait()
                final_files = core.read_final_path_markers(final_marker)
                if rc == 0:
                    for final_file in final_files:
                        self.bus.downloadAdded.emit(final_file, source_url)
                    self.bus.info.emit("Загрузка завершена.")
                elif playlist_mode == "playlist" and core.is_partial_playlist_success(rc, output_lines):
                    for final_file in final_files:
                        self.bus.downloadAdded.emit(final_file, source_url)
                    self.bus.info.emit(core.explain_partial_playlist_success(output_lines))
                else:
                    self.bus.error.emit(core.explain_download_failure(rc, output_lines, self.format_combo.currentText().strip()))
            except Exception as exc:
                self.bus.error.emit(
                    "Не удалось запустить процесс загрузки. "
                    f"Проверьте путь к yt-dlp, ffmpeg и PowerShell.\n\nТехнические детали: {exc}"
                )
            finally:
                self.download_process = None
                self.stop_requested = False
                self.bus.downloadFinished.emit(True)

        self.download_thread = threading.Thread(target=runner, daemon=True)
        self.download_thread.start()

    def _terminate_download_process(self):
        process = self.download_process
        if not process or process.poll() is not None:
            return
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            check=False,
            **core.hidden_subprocess_kwargs(),
        )
        if process.poll() is None:
            try:
                process.kill()
            except Exception:
                pass

    def stop_download(self):
        self.stop_requested = True
        if not self.download_thread or not self.download_thread.is_alive():
            self.write_log("Активной загрузки нет.")
            self.stop_button.setEnabled(False)
            return
        self.set_status("stopping")
        self.stop_button.setEnabled(False)
        if not self.download_process or self.download_process.poll() is not None:
            self.write_log("Остановка запрошена. Ждём запуск процесса...")
            return
        self.write_log("Остановка загрузки...")
        self._terminate_download_process()
        self.write_log("Команда остановки отправлена.")

    def on_download_finished(self, _ok: bool):
        self.download_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if self.status_chip.text() != STATUS_META["error"][0]:
            self.set_status("ready")
        self.refresh_dependency_status()


def main():
    core.set_windows_app_id()
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    window = FluentDownloader()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
