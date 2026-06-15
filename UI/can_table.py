# ui/can_table.py

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .theme import (
    BUTTON_HEIGHT,
    CAN_COL_DATA,
    CAN_COL_DLC,
    CAN_COL_ID,
    CAN_COL_SIGNAL,
    CAN_COL_TIMESTAMP,
    CAN_TABLE_ROW_HEIGHT,
    FONT_FAMILY_MONO,
    FONT_SIZE_CAPTION,
    FONT_SIZE_SMALL,
)

STATUS_COLORS = {
    "critical": {"fg": "#ffbeb2", "bg": "#34191c", "line": "#ff8b78"},
    "warning": {"fg": "#ffcc85", "bg": None, "line": None},
    "normal": {"fg": "#e7edf6", "bg": None, "line": None},
}


class CanTableWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(10)

        self.id_chip = QLabel("ID: 0x1A2   x")
        self.id_chip.setStyleSheet(
            "background: rgba(34, 216, 238, 0.08); color: #9fefff; border: 1px solid rgba(34, 216, 238, 0.3); border-radius: 8px; padding: 8px 12px; font-family: 'Consolas'; font-size: 12px; font-weight: 700;"
        )

        self.signal_chip = QLabel("Signal: Oil_Pressure_Critical   x")
        self.signal_chip.setStyleSheet(
            "background: rgba(200, 181, 255, 0.08); color: #d6c6ff; border: 1px solid rgba(200, 181, 255, 0.28); border-radius: 8px; padding: 8px 12px; font-family: 'Consolas'; font-size: 12px; font-weight: 700;"
        )

        self.add_filter_label = QLabel("+ ADD_FILTER")
        self.add_filter_label.setStyleSheet(
            "color: #6f7a8d; font-family: 'Consolas'; font-size: 12px; font-weight: 800; letter-spacing: 1px;"
        )

        self.sort_button = QPushButton("SORT: TIME_DESC")
        self.sort_button.setObjectName("GhostButton")
        self.sort_button.setFixedHeight(BUTTON_HEIGHT)

        self.live_capture_btn = QPushButton("LIVE_CAPTURE_ON")
        self.live_capture_btn.setObjectName("BtnLiveCapture")
        self.live_capture_btn.setFixedHeight(BUTTON_HEIGHT)

        controls_row.addWidget(self.id_chip)
        controls_row.addWidget(self.signal_chip)
        controls_row.addWidget(self.add_filter_label)
        controls_row.addStretch()
        controls_row.addWidget(self.sort_button)
        controls_row.addWidget(self.live_capture_btn)
        root.addLayout(controls_row)

        viewer_card = QFrame()
        viewer_card.setObjectName("SurfaceCard")
        viewer_layout = QVBoxLayout(viewer_card)
        viewer_layout.setContentsMargins(0, 0, 0, 0)
        viewer_layout.setSpacing(0)

        header = QFrame()
        header.setStyleSheet(
            "QFrame { background: #1b1b1d; border-top-left-radius: 14px; border-top-right-radius: 14px; border-bottom: 1px solid #272b34; }"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(12)

        title = QLabel("CAN_FRAME_VIEWER")
        title.setStyleSheet(
            f"color: #d9e4f4; font-family: '{FONT_FAMILY_MONO}', 'Consolas', monospace; font-size: {FONT_SIZE_SMALL}px; font-weight: 800; letter-spacing: 1px;"
        )

        stats = QLabel("PACKETS_S: 1,402  |  ERR_RATE: 0.002%")
        stats.setStyleSheet(
            f"color: #7a8597; font-family: '{FONT_FAMILY_MONO}', 'Consolas', monospace; font-size: {FONT_SIZE_CAPTION}px; font-weight: 700;"
        )

        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(stats)

        self.table = QTableWidget()
        self.table.setMinimumHeight(360)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["TIMESTAMP", "ID", "DLC", "DATA PAYLOAD (HEX)", "DECODED SIGNAL", "VALUE"]
        )
        self.table.setAlternatingRowColors(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setStyleSheet(
            f"""
            QTableWidget {{
                background: #151618;
                border: none;
                color: #C5CCD7;
                font-size: {FONT_SIZE_SMALL}px;
                selection-background-color: rgba(0, 229, 255, 0.10);
                selection-color: #F8FAFC;
            }}
            QHeaderView::section {{
                background: #2a2b2e;
                color: #7b8390;
                border: none;
                border-bottom: 1px solid #232831;
                padding: 10px 12px;
                font-size: {FONT_SIZE_CAPTION}px;
                font-weight: 800;
                letter-spacing: 1px;
                font-family: '{FONT_FAMILY_MONO}', 'Consolas', monospace;
            }}
            QTableWidget::item {{
                border: none;
                border-bottom: 1px solid rgba(255, 255, 255, 0.025);
                padding: 8px 10px;
            }}
            """
        )

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(18)
        shadow.setColor(QColor(0, 0, 0, 70))
        shadow.setOffset(0, 4)
        viewer_card.setGraphicsEffect(shadow)

        self.table.setColumnWidth(0, CAN_COL_TIMESTAMP)
        self.table.setColumnWidth(1, CAN_COL_ID)
        self.table.setColumnWidth(2, CAN_COL_DLC)
        self.table.setColumnWidth(3, CAN_COL_DATA + 70)
        self.table.setColumnWidth(4, CAN_COL_SIGNAL + 40)

        viewer_layout.addWidget(header)
        viewer_layout.addWidget(self.table)
        root.addWidget(viewer_card, 1)

    def _make_item(self, text: str, color: str, align=Qt.AlignVCenter | Qt.AlignLeft, mono=False):
        item = QTableWidgetItem(text)
        item.setTextAlignment(align)
        item.setForeground(QColor(color))
        item.setFont(QFont(FONT_FAMILY_MONO if mono else "Bahnschrift", 11 if mono else 12))
        return item

    def add_mock_data(self):
        frames = [
            ("14:20:01.0342", "0x0CF004FE", "8", "FF 3D 22 00 00 00 00 00", "Engine_Speed", "1,450 RPM", "normal"),
            ("14:20:01.0381", "0x18FEE000", "8", "AA FF 00 00 00 00 00 00", "Oil_Pressure_Critical", "8 PSI", "critical"),
            ("14:20:01.0425", "0x0CF00300", "8", "00 22 14 AA 33 00 00 00", "Throttle_Pos", "22.4 %", "normal"),
            ("14:20:01.0501", "0x18FEF111", "8", "12 44 55 66 77 88 99 00", "Cruis_Ctrl_Set", "---", "warning"),
            ("14:20:01.0622", "0x0CF004FE", "8", "FF 42 22 00 00 00 00 00", "Engine_Speed", "1,482 RPM", "normal"),
            ("14:20:01.0710", "0x1A2", "4", "0C 33 00 00", "Battery_Voltage", "14.2 V", "normal"),
        ]

        self.table.setRowCount(len(frames))

        for row, (ts, cid, dlc, data, sig, val, status) in enumerate(frames):
            cfg = STATUS_COLORS.get(status, STATUS_COLORS["normal"])
            items = [
                self._make_item(ts, cfg["fg"], mono=True),
                self._make_item(cid, "#7fe7ff" if status == "normal" else cfg["fg"], mono=True),
                self._make_item(dlc, cfg["fg"], align=Qt.AlignCenter, mono=True),
                self._make_item(data, cfg["fg"], mono=True),
                self._make_item(sig, cfg["fg"], mono=False),
                self._make_item(val, "#14e3ff" if status == "normal" else cfg["fg"], mono=True),
            ]

            for col, item in enumerate(items):
                if cfg["bg"]:
                    item.setBackground(QColor(cfg["bg"]))
                self.table.setItem(row, col, item)

            if cfg["line"]:
                line_item = self.table.item(row, 0)
                line_item.setBackground(QColor(cfg["bg"]))
                line_item.setData(Qt.UserRole, cfg["line"])

            self.table.setRowHeight(row, CAN_TABLE_ROW_HEIGHT + 6)

        self.table.selectRow(1)
