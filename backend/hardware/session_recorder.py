from __future__ import annotations

import csv
import os
import threading
import time
from datetime import datetime
from pathlib import Path


class SessionRecorder:
    """Records live CAN frames from live_signals_buffer to a timestamped CSV."""

    def __init__(self, live_signals_buffer: list, runtime_lock: threading.Lock) -> None:
        self._buffer = live_signals_buffer
        self._lock = runtime_lock
        self._recording = False
        self._thread: threading.Thread | None = None
        self._start_time: float | None = None
        self._output_path: str | None = None
        self._frame_count = 0
        self._last_seen_idx = 0

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def elapsed_seconds(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    @property
    def output_path(self) -> str | None:
        return self._output_path

    def start(self, output_dir: str = "backend/ml/outputs/sessions") -> str:
        if self._recording:
            raise RuntimeError("Already recording")
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._output_path = str(Path(output_dir) / f"session_{ts}.csv")
        self._recording = True
        self._start_time = time.time()
        self._frame_count = 0
        with self._lock:
            self._last_seen_idx = len(self._buffer)
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()
        return self._output_path

    def stop(self) -> str | None:
        self._recording = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        return self._output_path

    def _record_loop(self) -> None:
        path = self._output_path
        if path is None:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "can_id", "b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7"])
            while self._recording:
                with self._lock:
                    new_frames = list(self._buffer[self._last_seen_idx:])
                    self._last_seen_idx = len(self._buffer)
                for frame in new_frames:
                    can_id_str = str(frame.get("can_id", "0x000"))
                    try:
                        can_id_int = int(can_id_str, 16)
                    except ValueError:
                        can_id_int = 0
                    writer.writerow([
                        frame.get("timestamp", 0.0),
                        can_id_int,
                        frame.get("b0", 0), frame.get("b1", 0),
                        frame.get("b2", 0), frame.get("b3", 0),
                        frame.get("b4", 0), frame.get("b5", 0),
                        frame.get("b6", 0), frame.get("b7", 0),
                    ])
                    self._frame_count += 1
                if new_frames:
                    f.flush()
                time.sleep(0.1)
