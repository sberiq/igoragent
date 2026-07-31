from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


class ConfigurationStore:
    """Stores only non-secret dashboard configuration with owner-only permissions."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(os.getenv("IGORAGENT_CONFIG_PATH", ".data/configuration.json"))

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text())

    def save(self, configuration: dict[str, Any]) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as temporary:
            json.dump(configuration, temporary, indent=2, sort_keys=True)
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.chmod(0o600)
        temporary_path.replace(self.path)
