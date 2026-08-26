import json
from pathlib import Path
from perseus import _build_server_card

card = _build_server_card({
    "version": "1.0.26",
    "mcp": {"sse_bearer_token": "publication-requires-bearer"},
})
Path(".well-known/mcp/server-card.json").write_text(
    json.dumps(card, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
