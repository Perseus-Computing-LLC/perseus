# Skills catalog policy

Status: adopted implementation policy
Date: 2026-08-01

## Counting rule

The public count includes only standalone, supported, user-invocable skills with:

- a maintained trigger description;
- a complete packaged body;
- current verification evidence;
- resolved related-skill links and supporting-file references;
- an explicit public/product capability boundary.

The count excludes:

- references, templates, scripts, and assets;
- private or environment-specific runbooks;
- project-local skills;
- plugin-scoped skills;
- aliases and compatibility names;
- deprecated skills;
- investigation/quarantine packages;
- duplicate copies in worktrees, backups, or caches.

A merged skill counts once. The catalog is published with its version and audit date.

## Current target

The curated active Hermes catalog is intentionally described qualitatively rather than by a fixed public count. Internal runbooks, reference bundles, deprecated packages, and investigation packages remain preserved outside the public discovery tree.

This catalog is separate from Perseus Vault's MCP surface. Vault capabilities are maintained in `claims.json` and are not a skill count.

## Visibility classes

- **Public:** active standalone skills in `/opt/data/skills/`.
- **Internal:** preserved under `/opt/data/skills-private/internal/`; explicitly loadable by path when authorized, not publicly advertised.
- **Reference:** preserved under `/opt/data/skills-private/references/` or a retained skill's `references/` directory; not standalone-discoverable.
- **Deprecated:** preserved under `/opt/data/skills-private/deprecated/` pending removal or an explicit migration decision.
- **Investigate:** preserved under `/opt/data/skills-private/investigate/` pending runtime/usage evidence.
- **Plugin:** provided by a plugin namespace and counted separately from the core skill catalog.

## Maintenance gates

Every public catalog change should validate:

1. frontmatter and body size;
2. unique names and platform gates;
3. related-skill resolution;
4. relative support-file existence;
5. public/private/reference boundary;
6. generated documentation and count synchronization;
7. representative skill loading and usage regression.

The public count must not be changed by hand without regenerating or validating the catalog inventory.
