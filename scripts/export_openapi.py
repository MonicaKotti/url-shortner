#!/usr/bin/env python3
"""Export the deterministic service's OpenAPI contract."""

from __future__ import annotations

import json
from pathlib import Path

from app.main import create_app


def main() -> None:
    destination = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
