import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from perseus import _build_server_card

OUTPUT = ROOT / ".well-known" / "mcp" / "server-card.json"


def build_card(output: Path) -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    card = _build_server_card({
        "version": manifest["version"],
        "mcp": {"sse_bearer_token": "publication-requires-bearer"},
    })
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(card, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Generate the checked-in MCP server card")
    parser.add_argument(
        "--output",
        default=str(OUTPUT),
        help="output path (default: the checked-in server card)",
    )
    args = parser.parse_args(argv)
    build_card(Path(args.output))


if __name__ == "__main__":
    main()
