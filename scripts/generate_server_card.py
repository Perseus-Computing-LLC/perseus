import json
from pathlib import Path
from perseus import _build_server_card

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".well-known" / "mcp" / "server-card.json"
manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))

card = _build_server_card({
    "version": manifest["version"],
    "mcp": {"sse_bearer_token": "publication-requires-bearer"},
})
OUTPUT.write_text(
    json.dumps(card, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
