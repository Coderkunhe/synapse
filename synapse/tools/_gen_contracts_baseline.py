"""Generate or update the OpenAPI contract baseline snapshot.

Usage: python tools/_gen_contracts_baseline.py [output_path]
Default output: docs/contracts/openapi-baseline.json
"""

import json
import os
import sys

from src.main import app

OUTPUT = sys.argv[1] if len(sys.argv) > 1 else "docs/contracts/openapi-baseline.json"


def strip_descriptions(obj):
    """Remove non-structural keys from OpenAPI schema for diff comparison."""
    if isinstance(obj, dict):
        return {
            k: strip_descriptions(v)
            for k, v in obj.items()
            if k not in ("description", "title", "summary", "operationId")
        }
    elif isinstance(obj, list):
        return [strip_descriptions(v) for v in obj]
    return obj


def main():
    schema = app.openapi()
    normalized = strip_descriptions(schema)

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w") as f:
        json.dump(normalized, f, indent=2, sort_keys=True)
        f.write("\n")

    print(f"✅ 契约基线已更新: {OUTPUT}")


if __name__ == "__main__":
    main()
