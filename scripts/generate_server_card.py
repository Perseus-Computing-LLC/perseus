import json
from pathlib import Path
from perseus import _build_server_card

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".well-known" / "mcp" / "server-card.json"

card = _build_server_card({
    "version": "1.0.26",
    "mcp": {"sse_bearer_token": "publication-requires-bearer"},
})
OUTPUT.write_text(
    json.dumps(card, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
