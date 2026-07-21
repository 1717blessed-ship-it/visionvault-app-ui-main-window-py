"""Métricas locales y livianas de rendimiento de Doccione Studio."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
METRICS_PATH = ROOT / ".cache" / "performance.json"
_LOCK = threading.Lock()


def record_performance(name: str, elapsed_ms: float, **details) -> None:
    """Guarda el último tiempo y un promedio acumulado sin bloquear la interfaz."""
    try:
        with _LOCK:
            try:
                data = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            previous = data.get(name, {})
            count = int(previous.get("count", 0)) + 1
            old_average = float(previous.get("average_ms", 0.0))
            average = old_average + (float(elapsed_ms) - old_average) / count
            data[name] = {
                "last_ms": round(float(elapsed_ms), 2),
                "average_ms": round(average, 2),
                "maximum_ms": round(max(float(previous.get("maximum_ms", 0.0)), float(elapsed_ms)), 2),
                "count": count,
                "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "details": details,
            }
            METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = METRICS_PATH.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(METRICS_PATH)
    except OSError:
        # Medir nunca puede impedir que el usuario trabaje.
        pass
