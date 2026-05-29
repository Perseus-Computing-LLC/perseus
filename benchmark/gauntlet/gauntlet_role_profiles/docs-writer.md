@perseus v0.8
@prompt You are a simulated docs writer working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=300
@query "git diff --stat" timeout=5 @cache ttl=300
@query "python3 --version" timeout=5 @cache ttl=300
@query "pandoc --version" timeout=5 @cache ttl=300
@query "doctoc --version" timeout=5 @cache ttl=300
@query "vale --version" timeout=5 @cache ttl=300
@query "alex --version" timeout=5 @cache ttl=300
@query "write-good --version" timeout=5 @cache ttl=300
@query "npx markdownlint --version" timeout=5 @cache ttl=300
@query "npx prettier --version" timeout=5 @cache ttl=300
@query "ls -la docs/" timeout=5 @cache ttl=300
@query "wc -l docs/**/*.md 2>/dev/null" timeout=5 @cache ttl=300
@query "find docs/ -name '*.md' | wc -l" timeout=5 @cache ttl=300
@query "cat docs/README.md" timeout=5 @cache ttl=300
@query "cat docs/CONTRIBUTING.md" timeout=5 @cache ttl=300
@query "cat docs/CHANGELOG.md" timeout=5 @cache ttl=300
@query "ls docs/guides/" timeout=5 @cache ttl=300
@query "ls docs/api/" timeout=5 @cache ttl=300
@query "ls docs/tutorials/" timeout=5 @cache ttl=300
@query "cat .markdownlint.json 2>/dev/null" timeout=5 @cache ttl=300
@query "cat .vale.ini 2>/dev/null" timeout=5 @cache ttl=300
@query "cat .spellcheck.yml 2>/dev/null" timeout=5 @cache ttl=300
@query "cat mkdocs.yml 2>/dev/null || cat docusaurus.config.js 2>/dev/null" timeout=5 @cache ttl=300
@query "cat docs/_sidebar.md 2>/dev/null" timeout=5 @cache ttl=300
@query "cat docs/_navbar.md 2>/dev/null" timeout=5 @cache ttl=300
@query "ls docs/assets/" timeout=5 @cache ttl=300
@query "ls docs/examples/" timeout=5 @cache ttl=300
@query "cat README.md | head -30" timeout=5 @cache ttl=300
@read README.md
@read docs/CHANGELOG.md
@waypoint ttl=86400
@skills flag_stale=true
@agora status=open,in_progress
@memory focus="recent"
@memory
@drift
@synthesize
