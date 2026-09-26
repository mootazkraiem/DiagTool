"""
model_status.py
───────────────
What each selectable model id is, and what the offline and live paths may do
with it. One resolver for /api/models, /analyze and live hardware, so the three
never disagree and nothing falls back to another model without saying so.

Status of an id:

    clean_holdout_evaluated       a clean-2 family in production, scored on a
                                  complete recording it never saw
    clean_unvalidated_no_holdout  a clean-2 model exists but the vehicle has no
                                  independent recording to evaluate it on
    clean_held_back               a clean-2 model exists but was held back
    unavailable_no_clean_model    no clean model could be built for the vehicle
    legacy                        only the pre-clean state-routed bundle exists
    general                       the general model (or an explicit alias of it)
    unknown                       not a model id this installation knows

What each status allows:

    offline (/analyze)   clean_2 only for a clean family in production; the
                         general model for "general" and its explicit aliases;
                         refused otherwise (the Step 9 manifest gate).
    live (hardware)      clean_2 for a clean family in production; the legacy
                         bundle for legacy and not-promoted unvalidated
                         families, labelled as such; refused for held-back,
                         unavailable and unknown ids.

Statuses of families whose clean model is not in production cannot be read
from assets/models, so they are recorded here from the clean-2-002 decisions
(Steps 10H/10I).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from backend.ml.runtime.model_manifest import (
    FAMILY_SCHEMA_VERSION,
    ID_SCHEMA_VERSION,
    ManifestError,
    manifest_schema,
)

GENERAL = "general"

#: clean-2-002 decisions for families not promoted to production.
NOT_PROMOTED: dict[str, tuple[str, str]] = {
    "mg_zs_ev": ("clean_held_back",
                 "clean-2 model held back: about 78% of its holdout traffic is on CAN IDs absent from training"),
    "hyundai_ioniq5": ("clean_unvalidated_no_holdout",
                       "clean-2 model not promoted: only one recording, no independent holdout"),
    "kaggle_normal": ("clean_unvalidated_no_holdout",
                      "clean-2 model not promoted: only one recording, no independent holdout"),
    "tesla": ("clean_unvalidated_no_holdout",
              "clean-2 model not promoted: only one recording, no independent holdout"),
    "skoda_enyaq": ("unavailable_no_clean_model",
                    "no clean model: every Skoda recording is a protected evaluation file"),
    "nissan_leaf": ("unavailable_no_clean_model",
                    "no clean model: family excluded by policy (mixed SavvyCAN/BusMon recordings)"),
}


class ModelUnavailableError(RuntimeError):
    """The selected model id may not be used on this path; the message says why."""

    def __init__(self, status: "ModelStatus", path: str):
        self.status = status
        super().__init__(f"model '{status.id}' cannot be used for {path} analysis: {status.status} - {status.reason}")


@dataclass(frozen=True)
class ModelStatus:
    id: str
    status: str
    reason: str
    offline: str          # "clean_2" | "general" | "refused"
    live: str             # "clean_2" | "legacy" | "general" | "refused"
    model_version: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _default_model_root() -> Path:
    from backend.ml.runtime.model_loader import _default_assets_root
    return _default_assets_root() / "models"


def _aliases() -> set[str]:
    """Vehicle profiles (DBC decode) that score with the general model, by configuration."""
    try:
        from backend.decoding.vehicle_profiles import list_all
        return {p["id"] for p in list_all()}
    except Exception:
        return set()


def resolve(model_id: str, model_root: Path | None = None) -> ModelStatus:
    import json

    from backend.ml.runtime.model_loader import _trained_states

    mid = (model_id or "").strip() or GENERAL
    root = Path(model_root) if model_root is not None else _default_model_root()

    if mid == GENERAL:
        return ModelStatus(GENERAL, "general", "general model", "general", "general")

    schema = manifest_schema(root, mid)
    if schema in (FAMILY_SCHEMA_VERSION, ID_SCHEMA_VERSION):
        manifest = json.loads((root / mid / "manifest.json").read_text(encoding="utf-8"))
        v = (manifest.get("validation") or {})
        vstatus = v.get("status", "holdout_evaluated" if manifest.get("holdout", {}).get("recordings") else
                        "unvalidated_no_holdout")
        version = str(manifest.get("model_version", ""))
        if vstatus == "held_back":
            return ModelStatus(mid, "clean_held_back", v.get("reason", "held back"), "refused", "refused", version)
        return ModelStatus(mid, f"clean_{vstatus}", v.get("reason", ""), "clean_2", "clean_2", version)
    if schema is not None:
        return ModelStatus(mid, "unknown", f"manifest schema {schema!r} is not a runtime model", "refused", "refused")

    if mid in NOT_PROMOTED:
        status, reason = NOT_PROMOTED[mid]
        live = "legacy" if status == "clean_unvalidated_no_holdout" and _trained_states(root / mid) else "refused"
        return ModelStatus(mid, status, reason + ("; live mode uses the legacy bundle" if live == "legacy" else ""),
                           "refused", live)
    if _trained_states(root / mid):
        return ModelStatus(mid, "legacy", "legacy state-routed bundle; no clean model", "refused", "legacy")
    if mid in _aliases():
        return ModelStatus(mid, "general", "vehicle profile scored with the general model", "general", "general")
    return ModelStatus(mid, "unknown", "not a model id known to this installation", "refused", "refused")


def live_engine(vehicle_id: str, cfg=None, model_root: Path | None = None):
    """A RealtimeEngine for live hardware, built for exactly the selected model.

    Raises ModelUnavailableError when the selection may not be used live, and
    ManifestError when a clean production family fails validation - never a
    fallback to another model.
    """
    from backend.ml.runtime.model_manifest import IdModelFamily, FamilyModel
    from backend.ml.runtime.realtime_engine import RealtimeEngine
    from backend.ml.runtime.runtime_config import DEFAULT_CONFIG

    status = resolve(vehicle_id, model_root)
    if status.live == "refused":
        raise ModelUnavailableError(status, "live")
    vid = GENERAL if status.live == "general" else status.id
    engine = RealtimeEngine(cfg or DEFAULT_CONFIG, vehicle_id=vid, model_root=model_root)
    if status.live == "clean_2" and not isinstance(engine._family, (IdModelFamily, FamilyModel)):
        raise ManifestError(status.id, ["clean family resolved but not loaded by the engine"])
    if status.live != "clean_2" and engine._family is not None:
        raise ManifestError(status.id, [f"engine loaded a clean family for a {status.status} selection"])
    engine.model_status = status
    return engine
