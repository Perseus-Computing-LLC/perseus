@perseus v0.8
@prompt You are a simulated devtools working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=86400
@query "bazel --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "make --version" timeout=5 @cache ttl=86400
@query "cmake --version" timeout=5 @cache ttl=86400
@query "ninja --version" timeout=5 @cache ttl=86400
@query "mvn --version" timeout=5 @cache ttl=86400
@query "gradle --version" timeout=5 @cache ttl=86400
@query "sbt --version" timeout=5 @cache ttl=86400
@query "cargo --version" timeout=5 @cache ttl=86400
@query "go version" timeout=5 @cache ttl=86400
@query "rustc --version" timeout=5 @cache ttl=86400
@query "clang --version" timeout=5 @cache ttl=86400
@query "gcc --version" timeout=5 @cache ttl=86400
@query "g++ --version" timeout=5 @cache ttl=86400
@query "ccache --version" timeout=5 @cache ttl=86400
@query "sccache --version" timeout=5 @cache ttl=86400
@query "distcc --version" timeout=5 @cache ttl=86400
@query "buck2 --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "pants --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "please --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "pre-commit --version" timeout=5 @cache ttl=86400
@query "act --version" timeout=5 @cache ttl=86400
@query "earthly --version" timeout=5 @cache ttl=86400
@query "dagger --version" timeout=5 @cache ttl=86400
@query "ls -la .bazelversion 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat Makefile | head -30" timeout=5 @cache ttl=86400
@query "cat CMakeLists.txt | head -30" timeout=5 @cache ttl=86400
@query "ls -la build/ 2>/dev/null" timeout=5 @cache ttl=86400
@query "ls -la dist/ 2>/dev/null" timeout=5 @cache ttl=86400
@query "ls -la target/ 2>/dev/null" timeout=5 @cache ttl=86400
@query "ls -la bazel-bin/ 2>/dev/null" timeout=5 @cache ttl=86400
@query "du -sh build/ 2>/dev/null" timeout=5 @cache ttl=86400
@query "du -sh target/ 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat .bazelrc 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat .bazelversion 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat BUILD 2>/dev/null | head -30" timeout=5 @cache ttl=86400
@query "cat WORKSPACE 2>/dev/null | head -30" timeout=5 @cache ttl=86400
@query "cat pom.xml | head -30" timeout=5 @cache ttl=86400
@query "cat build.gradle | head -30" timeout=5 @cache ttl=86400
@query "cat Cargo.toml | head -30" timeout=5 @cache ttl=86400
@query "cat go.mod | head -30" timeout=5 @cache ttl=86400
@services
  - name: build-artifactory
    url: http://localhost:8081/health
    timeout: 2
  - name: nexus
    url: http://localhost:8082/health
    timeout: 2
  - name: jenkins
    url: http://localhost:8083/health
    timeout: 2
  - name: teamcity
    url: http://localhost:8084/health
    timeout: 2
  - name: buildkite
    url: http://localhost:8085/health
    timeout: 2
  - name: circleci
    url: http://localhost:8086/health
    timeout: 2
  - name: github-actions
    url: http://localhost:8087/health
    timeout: 2
  - name: gitlab-ci
    url: http://localhost:8088/health
    timeout: 2
  - name: artifactory
    url: http://localhost:8089/health
    timeout: 2
  - name: sonar
    url: http://localhost:9000/health
    timeout: 2
  - name: codespell-dict
    url: http://localhost:8080/health
    timeout: 2
@waypoint ttl=86400
@skills flag_stale=true
@agora status=open,in_progress
@inbox
@health
@drift
@prefetch
@memory focus="recent"
