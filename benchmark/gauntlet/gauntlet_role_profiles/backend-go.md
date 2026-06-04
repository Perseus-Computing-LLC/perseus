@perseus v0.8
@prompt You are a simulated backend go working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=86400
@query "go version" timeout=5 @cache ttl=86400
@query "go env GOPATH" timeout=5 @cache ttl=86400
@query "go env GOROOT" timeout=5 @cache ttl=86400
@query "go env GOPROXY" timeout=5 @cache ttl=86400
@query "go env GOMOD" timeout=5 @cache ttl=86400
@query "go list -m all | head -30" timeout=5 @cache ttl=86400
@query "go list -u -m all 2>/dev/null | head -20" timeout=5 @cache ttl=86400
@query "go test -list ./..." timeout=5 @cache ttl=86400
@query "go vet ./..." timeout=5 @cache ttl=86400
@query "go build ./..." timeout=5 @cache ttl=86400
@query "go mod tidy --diff" timeout=5 @cache ttl=86400
@query "go mod why -m" timeout=5 @cache ttl=86400
@query "golangci-lint --version" timeout=5 @cache ttl=86400
@query "gofmt -l ." timeout=5 @cache ttl=86400
@query "staticcheck --version" timeout=5 @cache ttl=86400
@query "revive --version" timeout=5 @cache ttl=86400
@query "goimports --version" timeout=5 @cache ttl=86400
@query "ls -la cmd/" timeout=5 @cache ttl=86400
@query "ls -la internal/" timeout=5 @cache ttl=86400
@query "ls -la pkg/" timeout=5 @cache ttl=86400
@query "wc -l **/*.go 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat go.mod" timeout=5 @cache ttl=86400
@query "cat go.sum | wc -l" timeout=5 @cache ttl=86400
@query "cat Dockerfile 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat .golangci.yml 2>/dev/null || cat .golangci.yaml 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat Taskfile.yml 2>/dev/null || cat Makefile" timeout=5 @cache ttl=86400
@query "go doc net/http | head -20" timeout=5 @cache ttl=86400
@query "go tool pprof --help 2>/dev/null | head -5" timeout=5 @cache ttl=86400
@query "go tool trace --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "go tool cover --version" timeout=5 @cache ttl=86400
@services
  - name: go-api
    url: http://localhost:8080/health
    timeout: 2
  - name: grpc-server
    url: http://localhost:50051/health
    timeout: 2
  - name: prometheus-metrics
    url: http://localhost:9090/health
    timeout: 2
  - name: jaeger
    url: http://localhost:16686/health
    timeout: 2
  - name: pprof
    url: http://localhost:6060/health
    timeout: 2
@read go.mod
@read go.sum
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@memory focus="recent"
@drift
@inbox
