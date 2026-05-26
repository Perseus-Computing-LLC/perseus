@perseus v0.8
@prompt You are a simulated backend rust working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "rustc --version" @cache ttl=300
@query "cargo --version" @cache ttl=300
@query "cargo build --release 2>&1 | tail -5" @cache ttl=300
@query "cargo check" @cache ttl=300
@query "cargo test --no-run --quiet" @cache ttl=300
@query "cargo clippy --version" @cache ttl=300
@query "cargo fmt -- --check" @cache ttl=300
@query "cargo audit --version" @cache ttl=300
@query "cargo deny --version" @cache ttl=300
@query "cargo outdated --version" @cache ttl=300
@query "cargo udeps --version" @cache ttl=300
@query "cargo nextest --version" @cache ttl=300
@query "cargo tarpaulin --version" @cache ttl=300
@query "rustup show" @cache ttl=300
@query "rustup toolchain list" @cache ttl=300
@query "ls -la src/" @cache ttl=300
@query "ls -la bin/" @cache ttl=300
@query "wc -l src/**/*.rs 2>/dev/null" @cache ttl=300
@query "cat Cargo.toml" @cache ttl=300
@query "cat Cargo.lock | head -30" @cache ttl=300
@query "cat .rustfmt.toml 2>/dev/null" @cache ttl=300
@query "cat .clippy.toml 2>/dev/null" @cache ttl=300
@query "cat cross.toml 2>/dev/null" @cache ttl=300
@query "cat build.rs 2>/dev/null" @cache ttl=300
@query "cat rust-toolchain.toml 2>/dev/null" @cache ttl=300
@services
  - name: actix-api
    url: http://localhost:8080/health
    timeout: 2
  - name: tokio-console
    url: http://localhost:6669/health
    timeout: 2
  - name: cargo-docs
    url: http://localhost:8081/health
    timeout: 2
@read Cargo.toml
@read Cargo.lock
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@memory focus="recent"
@drift
@inbox
