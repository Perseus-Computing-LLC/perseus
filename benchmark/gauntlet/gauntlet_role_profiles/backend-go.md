@perseus v0.8
@prompt You are a simulated backend go working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "go version" @cache ttl=300
@query "go env GOPATH" @cache ttl=300
@query "go env GOROOT" @cache ttl=300
@query "go env GOPROXY" @cache ttl=300
@query "go env GOMOD" @cache ttl=300
@query "go list -m all | head -30" @cache ttl=300
@query "go list -u -m all 2>/dev/null | head -20" @cache ttl=300
@query "go test -list ./..." @cache ttl=300
@query "go vet ./..." @cache ttl=300
@query "go build ./..." @cache ttl=300
@query "go mod tidy --diff" @cache ttl=300
@query "go mod why -m" @cache ttl=300
@query "golangci-lint --version" @cache ttl=300
@query "gofmt -l ." @cache ttl=300
@query "staticcheck --version" @cache ttl=300
@query "revive --version" @cache ttl=300
@query "goimports --version" @cache ttl=300
@query "ls -la cmd/" @cache ttl=300
@query "ls -la internal/" @cache ttl=300
@query "ls -la pkg/" @cache ttl=300
@query "wc -l **/*.go 2>/dev/null" @cache ttl=300
@query "cat go.mod" @cache ttl=300
@query "cat go.sum | wc -l" @cache ttl=300
@query "cat Dockerfile 2>/dev/null" @cache ttl=300
@query "cat .golangci.yml 2>/dev/null || cat .golangci.yaml 2>/dev/null" @cache ttl=300
@query "cat Taskfile.yml 2>/dev/null || cat Makefile" @cache ttl=300
@query "go doc net/http | head -20" @cache ttl=300
@query "go tool pprof --help 2>/dev/null | head -5" @cache ttl=300
@query "go tool trace --version 2>/dev/null" @cache ttl=300
@query "go tool cover --version" @cache ttl=300
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
