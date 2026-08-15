from __future__ import annotations
from pathlib import Path
import json, os

class IntegrationSettings:
    """Small local secret/config store for integration credentials.

    The file is created with owner-only permissions. It is deliberately separate
    from AXON memory so credentials never enter the memory subsystem.
    """
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or Path.home()/".config"/"axon"/"integrations.json").expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self):
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    def save(self, section: str, values: dict):
        self.data[section] = dict(values)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        try: os.chmod(tmp, 0o600)
        except OSError: pass
        tmp.replace(self.path)
        try: os.chmod(self.path, 0o600)
        except OSError: pass

    def section(self, section: str) -> dict:
        value = self.data.get(section, {})
        return dict(value) if isinstance(value, dict) else {}
