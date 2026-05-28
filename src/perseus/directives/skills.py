# stdlib imports available from build artifact header
# ──────────────────────────────── @skills ─────────────────────────────────────

def resolve_skills(args_str: str, cfg: dict) -> str:
    """Scan the configured skills directory and emit a markdown summary."""
    skill_dir = Path(cfg.get("pythia", {}).get("skill_dir", str(PERSEUS_HOME / "skills")))
    stale_days = int(cfg.get("pythia", {}).get("stale_skill_days", 30))
    flag_stale = "flag_stale=true" in args_str

    # Parse category= / include= filter (comma-separated, case-insensitive).
    # include= is an alias for category=.
    _cat_m = re.search(r'(?:category|include)=([^\s]+)', args_str)
    categories: list = []
    if _cat_m:
        raw = _cat_m.group(1).strip("\"'")
        categories = [c.strip().lower() for c in raw.split(",") if c.strip()]

    stale_threshold = time.time() - stale_days * 86400
    skills = []

    if not skill_dir.exists():
        return f"> ⚠ Skills directory not found: `{skill_dir}`"

    for skill_md in sorted(skill_dir.rglob("SKILL.md")):
        rel = skill_md.relative_to(skill_dir)
        parts = list(rel.parts)
        # category = first dir component; name = second (or same if flat)
        if len(parts) >= 2:
            category = parts[0]
            name = parts[1]
        else:
            category = ""
            name = parts[0]

        if categories and category.lower() not in categories:
            continue

        mtime = skill_md.stat().st_mtime
        age_days = int((time.time() - mtime) / 86400)
        stale = flag_stale and mtime < stale_threshold

        # Parse description from frontmatter
        description = ""
        try:
            text = skill_md.read_text(errors="replace")
            fm, _body = _parse_frontmatter(text)
            description = str((fm or {}).get("description", ""))
            name = str((fm or {}).get("name", name))
        except Exception:
            pass

        stale_marker = " ⚠ stale" if stale else ""
        skills.append(f"| `{category}/{name}` | {description[:60]} | {age_days}d ago{stale_marker} |")

    if not skills:
        return "> No skills found."

    header = "| Skill | Description | Last updated |\n|---|---|---|"
    return header + "\n" + "\n".join(skills)


