@perseus v0.8
@prompt You are a simulated devtools working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "bazel --version 2>/dev/null" @cache ttl=300
@query "make --version" @cache ttl=300
@query "cmake --version" @cache ttl=300
@query "ninja --version" @cache ttl=300
@query "mvn --version" @cache ttl=300
@query "gradle --version" @cache ttl=300
@query "sbt --version" @cache ttl=300
@query "cargo --version" @cache ttl=300
@query "go version" @cache ttl=300
@query "rustc --version" @cache ttl=300
@query "clang --version" @cache ttl=300
@query "gcc --version" @cache ttl=300
@query "g++ --version" @cache ttl=300
@query "ccache --version" @cache ttl=300
@query "sccache --version" @cache ttl=300
@query "distcc --version" @cache ttl=300
@query "buck2 --version 2>/dev/null" @cache ttl=300
@query "pants --version 2>/dev/null" @cache ttl=300
@query "please --version 2>/dev/null" @cache ttl=300
@query "pre-commit --version" @cache ttl=300
@query "act --version" @cache ttl=300
@query "earthly --version" @cache ttl=300
@query "dagger --version" @cache ttl=300
@query "ls -la .bazelversion 2>/dev/null" @cache ttl=300
@query "cat Makefile | head -30" @cache ttl=300
@query "cat CMakeLists.txt | head -30" @cache ttl=300
@query "ls -la build/ 2>/dev/null" @cache ttl=300
@query "ls -la dist/ 2>/dev/null" @cache ttl=300
@query "ls -la target/ 2>/dev/null" @cache ttl=300
@query "ls -la bazel-bin/ 2>/dev/null" @cache ttl=300
@query "du -sh build/ 2>/dev/null" @cache ttl=300
@query "du -sh target/ 2>/dev/null" @cache ttl=300
@query "cat .bazelrc 2>/dev/null" @cache ttl=300
@query "cat .bazelversion 2>/dev/null" @cache ttl=300
@query "cat BUILD 2>/dev/null | head -30" @cache ttl=300
@query "cat WORKSPACE 2>/dev/null | head -30" @cache ttl=300
@query "cat pom.xml | head -30" @cache ttl=300
@query "cat build.gradle | head -30" @cache ttl=300
@query "cat Cargo.toml | head -30" @cache ttl=300
@query "cat go.mod | head -30" @cache ttl=300
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
