@perseus v0.8
@prompt You are a simulated sre working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "kubectl version --short" @cache ttl=300
@query "kubectl get nodes -o wide" @cache ttl=300
@query "kubectl top nodes" @cache ttl=300
@query "kubectl top pods -A" @cache ttl=300
@query "kubectl describe nodes" @cache ttl=300
@query "kubectl get events -A --sort-by=.lastTimestamp" @cache ttl=300
@query "kubectl get hpa -A" @cache ttl=300
@query "kubectl get pdb -A" @cache ttl=300
@query "kubectl get networkpolicies -A" @cache ttl=300
@query "kubectl get crd" @cache ttl=300
@query "terraform version" @cache ttl=300
@query "terraform plan -detailed-exitcode" @cache ttl=300
@query "promtool check rules /etc/prometheus/rules/*.yml" @cache ttl=300
@query "promtool test rules /etc/prometheus/rules/test/*.yml" @cache ttl=300
@query "amtool --version" @cache ttl=300
@query "amtool silence list" @cache ttl=300
@query "curl -s http://localhost:9090/api/v1/status/runtimeinfo" @cache ttl=300
@query "curl -s http://localhost:9090/api/v1/status/buildinfo" @cache ttl=300
@query "curl -s http://localhost:9090/api/v1/alerts | head -100" @cache ttl=300
@query "curl -s http://localhost:9090/api/v1/targets | head -100" @cache ttl=300
@query "curl -s http://localhost:9093/api/v2/alerts | head -100" @cache ttl=300
@query "curl -s http://localhost:3000/api/health" @cache ttl=300
@query "curl -s http://localhost:3100/ready" @cache ttl=300
@query "curl -s http://localhost:9090/api/v1/query?query=up" @cache ttl=300
@query "curl -s http://localhost:9090/api/v1/query?query=node_load1" @cache ttl=300
@query "curl -s http://localhost:9090/api/v1/query?query=node_memory_MemAvailable_bytes" @cache ttl=300
@query "curl -s http://localhost:9090/api/v1/query?query=node_filesystem_free_bytes" @cache ttl=300
@query "df -h" @cache ttl=300
@query "df -i /" @cache ttl=300
@query "free -m" @cache ttl=300
@query "uptime" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "hostnamectl" @cache ttl=300
@query "timedatectl" @cache ttl=300
@query "ip addr show" @cache ttl=300
@query "ss -tlnp" @cache ttl=300
@query "ss -ulnp" @cache ttl=300
@query "ping -c 3 localhost" @cache ttl=300
@query "journalctl -n 20 --no-pager -u kubelet" @cache ttl=300
@query "journalctl -n 20 --no-pager -u docker" @cache ttl=300
@query "systemctl list-units --type=service --state=running" @cache ttl=300
@query "systemctl status prometheus" @cache ttl=300
@query "systemctl status alertmanager" @cache ttl=300
@query "systemctl status grafana-server" @cache ttl=300
@query "ps aux --sort=-%cpu | head -20" @cache ttl=300
@query "ps aux --sort=-%mem | head -20" @cache ttl=300
@query "top -bn1 | head -30" @cache ttl=300
@query "vmstat 1 1" @cache ttl=300
@query "iostat -x 1 1" @cache ttl=300
@query "sar -u 1 1" @cache ttl=300
@query "sar -r 1 1" @cache ttl=300
@query "cat /proc/cpuinfo | grep 'model name' | head -1" @cache ttl=300
@query "cat /proc/meminfo | head -10" @cache ttl=300
@query "cat /proc/loadavg" @cache ttl=300
@query "cat /proc/uptime" @cache ttl=300
@services
  - name: prom-0
    url: http://localhost:9090/health
    timeout: 2
  - name: prom-1
    url: http://localhost:9091/health
    timeout: 2
  - name: prom-2
    url: http://localhost:9092/health
    timeout: 2
  - name: prom-3
    url: http://localhost:9093/health
    timeout: 2
  - name: prom-4
    url: http://localhost:9094/health
    timeout: 2
  - name: prom-5
    url: http://localhost:9095/health
    timeout: 2
  - name: prom-6
    url: http://localhost:9096/health
    timeout: 2
  - name: prom-7
    url: http://localhost:9097/health
    timeout: 2
  - name: prom-8
    url: http://localhost:9098/health
    timeout: 2
  - name: prom-9
    url: http://localhost:9099/health
    timeout: 2
  - name: prom-10
    url: http://localhost:9100/health
    timeout: 2
  - name: prom-11
    url: http://localhost:9101/health
    timeout: 2
  - name: prom-12
    url: http://localhost:9102/health
    timeout: 2
  - name: prom-13
    url: http://localhost:9103/health
    timeout: 2
  - name: prom-14
    url: http://localhost:9104/health
    timeout: 2
  - name: graf-0
    url: http://localhost:3000/health
    timeout: 2
  - name: graf-1
    url: http://localhost:3001/health
    timeout: 2
  - name: graf-2
    url: http://localhost:3002/health
    timeout: 2
  - name: graf-3
    url: http://localhost:3003/health
    timeout: 2
  - name: graf-4
    url: http://localhost:3004/health
    timeout: 2
  - name: loki-0
    url: http://localhost:3100/health
    timeout: 2
  - name: loki-1
    url: http://localhost:3101/health
    timeout: 2
  - name: loki-2
    url: http://localhost:3102/health
    timeout: 2
  - name: loki-3
    url: http://localhost:3103/health
    timeout: 2
  - name: loki-4
    url: http://localhost:3104/health
    timeout: 2
  - name: alert-0
    url: http://localhost:9093/health
    timeout: 2
  - name: alert-1
    url: http://localhost:9094/health
    timeout: 2
  - name: alert-2
    url: http://localhost:9095/health
    timeout: 2
  - name: alert-3
    url: http://localhost:9096/health
    timeout: 2
  - name: alert-4
    url: http://localhost:9097/health
    timeout: 2
@read /etc/os-release
@read /proc/cpuinfo
@read /proc/meminfo
@read /etc/hosts
@read /etc/resolv.conf
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@inbox
@drift
