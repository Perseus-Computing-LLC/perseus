@perseus v0.8
@prompt You are a simulated docs writer working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "git diff --stat" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "pandoc --version" @cache ttl=300
@query "doctoc --version" @cache ttl=300
@query "vale --version" @cache ttl=300
@query "alex --version" @cache ttl=300
@query "write-good --version" @cache ttl=300
@query "npx markdownlint --version" @cache ttl=300
@query "npx prettier --version" @cache ttl=300
@query "ls -la docs/" @cache ttl=300
@query "wc -l docs/**/*.md 2>/dev/null" @cache ttl=300
@query "find docs/ -name '*.md' | wc -l" @cache ttl=300
@query "cat docs/README.md" @cache ttl=300
@query "cat docs/CONTRIBUTING.md" @cache ttl=300
@query "cat docs/CHANGELOG.md" @cache ttl=300
@query "ls docs/guides/" @cache ttl=300
@query "ls docs/api/" @cache ttl=300
@query "ls docs/tutorials/" @cache ttl=300
@query "cat .markdownlint.json 2>/dev/null" @cache ttl=300
@query "cat .vale.ini 2>/dev/null" @cache ttl=300
@query "cat .spellcheck.yml 2>/dev/null" @cache ttl=300
@query "cat mkdocs.yml 2>/dev/null || cat docusaurus.config.js 2>/dev/null" @cache ttl=300
@query "cat docs/_sidebar.md 2>/dev/null" @cache ttl=300
@query "cat docs/_navbar.md 2>/dev/null" @cache ttl=300
@query "ls docs/assets/" @cache ttl=300
@query "ls docs/examples/" @cache ttl=300
@query "cat README.md | head -30" @cache ttl=300
@read README.md
@read docs/CHANGELOG.md
@waypoint ttl=86400
@skills flag_stale=true
@agora status=open,in_progress
@memory focus="recent"
@memory
@drift
@synthesize
