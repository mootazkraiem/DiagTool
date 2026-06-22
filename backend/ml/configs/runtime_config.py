from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeConfig:
    # Rolling limits (bounded memory)
    interval_window: int = 100
    payload_window: int = 100
    score_window: int = 100
    transition_window: int = 100

    # Scoring behavior
    temporal_short_window: int = 20
    temporal_medium_window: int = 50
    temporal_long_window: int = 100
    alert_threshold: float = 0.55
    low_threshold: float = 0.30
    medium_threshold: float = 0.55
    high_threshold: float = 0.80
    critical_threshold: float = 1.00
    emit_low_alerts: bool = False
    persistence_threshold: float = 0.30
    temporal_decay: float = 0.90
    cooldown_seconds: float = 1.0
    debug_every_n_frames: int = 20

    # Fusion weights (frozen v1 philosophy)
    timing_weight: float = 0.35
    payload_weight: float = 0.35
    ml_weight: float = 0.20
    temporal_weight: float = 0.10

    # I/O
    base_dir: Path = Path(__file__).resolve().parents[1]

    @property
    def outputs_dir(self) -> Path:
        return self.base_dir / "outputs"

    @property
    def alerts_path(self) -> Path:
        return self.outputs_dir / "alerts" / "alerts.jsonl"

    @property
    def alerts_csv_path(self) -> Path:
        return self.outputs_dir / "alerts" / "alerts.csv"


DEFAULT_CONFIG = RuntimeConfig()
