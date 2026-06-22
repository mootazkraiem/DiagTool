# ui/main_window.py

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *

from .styles import get_stylesheet
from .sidebar import SidebarWidget
from .topbar import TopBarWidget
from .can_table import CanTableWidget
from .right_panel import RightPanelWidget
from .visualization import VisualizationWidget
from .log_playback import LogPlaybackWidget
from .components import MetricCard
from .decoder_manager import DecoderManagerWidget
from .analytics import AnalyticsWidget
from .settings import SettingsWidget
from .alerts import AlertsWidget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CAN MASTER — Diagnostics Suite")
        self.setMinimumSize(1280, 800)
        self.setGeometry(80, 80, 1440, 900)
        self.apply_style()
        self.init_ui()

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ───────────────────────────────────
        self.sidebar = SidebarWidget()

        # ── Center column ─────────────────────────────
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        self.topbar = TopBarWidget()

        # ── Page stack ────────────────────────────────
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_dashboard())          # 0
        self.stack.addWidget(LogPlaybackWidget())              # 1
        self.stack.addWidget(DecoderManagerWidget())          # 2
        self.stack.addWidget(AlertsWidget())                   # 3
        self.stack.addWidget(AnalyticsWidget())                # 4
        self.stack.addWidget(SettingsWidget())                 # 5

        center_layout.addWidget(self.topbar)
        center_layout.addWidget(self.stack)

        root.addWidget(self.sidebar)
        root.addWidget(center)

        # ── Signals ───────────────────────────────────
        self.sidebar.page_changed.connect(self.stack.setCurrentIndex)

    # ─────────────────────────────────────────────────
    def _build_dashboard(self) -> QWidget:
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Main workspace (table + graph)
        workspace = QWidget()
        ws_layout = QVBoxLayout(workspace)
        ws_layout.setContentsMargins(20, 20, 20, 20)
        ws_layout.setSpacing(20)

        # Dashboard Metrics Row
        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(16)
        self.dash_rpm = MetricCard("ENGINE_RPM", "4250", "RPM", "#00E5FF")
        self.dash_temp = MetricCard("CORE_TEMP", "82.4", "°C", "#7C4DFF")
        self.dash_volt = MetricCard("BUS_VOLTAGE", "392.1", "V", "#00E5FF")
        metrics_row.addWidget(self.dash_rpm)
        metrics_row.addWidget(self.dash_temp)
        metrics_row.addWidget(self.dash_volt)
        
        ws_layout.addLayout(metrics_row)
        splitter = QSplitter(Qt.Vertical)
        splitter.setStyleSheet("QSplitter::handle { background: #1C2A40; height: 4px; }")

        self.can_table = CanTableWidget()
        self.can_table.add_mock_data()

        self.viz = VisualizationWidget()

        splitter.addWidget(self.can_table)
        splitter.addWidget(self.viz)
        splitter.setSizes([520, 280])

        ws_layout.addWidget(splitter)

        # Right alert panel
        self.right_panel = RightPanelWidget()

        layout.addWidget(workspace, 1)
        layout.addWidget(self.right_panel)
        return page

    def _build_placeholder(self, name: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(12)

        icon = QLabel("⬡")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size: 56px; color: #1C2A40;")

        title = QLabel(name)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "font-size: 26px; font-weight: 700; color: #DDE6FF; letter-spacing: 1px;"
        )

        sub = QLabel("This section is under construction.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("font-size: 13px; color: #3A5070;")

        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(sub)
        return page

    def apply_style(self):
        self.setStyleSheet(get_stylesheet())