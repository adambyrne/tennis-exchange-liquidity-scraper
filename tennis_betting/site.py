from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ui import HTML


def build_static_site(data: dict[str, Any], output_directory: str | Path) -> None:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    (output / "index.html").write_text(
        HTML.replace("const STATIC_MODE = false;", "const STATIC_MODE = true;"),
        encoding="utf-8",
    )
    (output / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
