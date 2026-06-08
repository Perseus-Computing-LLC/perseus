import os
from typing import Any, List, Dict, Optional, Tuple
from mcp.server.fastmcp import FastMCP
from sibyl_memory_client import MemoryClient

mcp = FastMCP("sibyl")

def _get_client() -> MemoryClient:
    db_path = os.environ.get("SIBYL_DB_PATH", "~/.sibyl-memory/memory.db")
    expanded_path = os.path.expanduser(db_path)
    return MemoryClient.local(expanded_path)

@mcp.tool()
def sibyl_search(query: str, limit: int = 20) -> str:
    """
    Search Sibyl Memory across all tiers using FTS5.
    Returns matching entities, state keys, and reference documents.
    """
    client = _get_client()
    try:
        results = client.search(query, limit=limit)
        if not results:
            return f"No results found for query: '{query}'"
        
        output = []
        for r in results:
            tier = r.get("tier", "?")
            key = r.get("key", "?")
            cat = r.get("category", "")
            label = f"[{tier}] {cat}/{key}" if cat else f"[{tier}] {key}"
            snippet = str(r.get("snippet", "")).strip()
            if not snippet:
                snippet = str(r.get("body", ""))[:200].strip()
            
            output.append(f"- {label}: {snippet}")
        return "\n".join(output)
    except Exception as e:
        return f"Error searching Sibyl Memory: {str(e)}"

@mcp.tool()
def sibyl_recall(category: str, name: str) -> str:
    """
    Fetch an entity from Sibyl Memory by its category and name.
    """
    client = _get_client()
    try:
        entity = client.get_entity(category, name)
        if not entity:
            return f"Entity '{category}/{name}' not found."
        import json
        return json.dumps(entity, indent=2)
    except Exception as e:
        return f"Error fetching entity '{category}/{name}': {str(e)}"

@mcp.tool()
def sibyl_remember(category: str, name: str, body_json: str, status: Optional[str] = None) -> str:
    """
    Create or update an entity in Sibyl Memory.
    'body_json' must be a valid JSON string containing an object or array.
    """
    client = _get_client()
    import json
    try:
        body = json.loads(body_json)
    except json.JSONDecodeError as e:
        return f"Error: body_json must be valid JSON. {str(e)}"

    try:
        result = client.set_entity(category, name, body, status=status)
        return f"Successfully saved '{category}/{name}':\n" + json.dumps(result, indent=2)
    except Exception as e:
        return f"Error saving entity '{category}/{name}': {str(e)}"

def main():
    mcp.run()

if __name__ == "__main__":
    main()
