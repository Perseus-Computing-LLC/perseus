@perseus v0.8
@prompt You are a simulated platform engineer working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=86400
@query "git diff --stat HEAD~1" timeout=5 @cache ttl=86400
@query "git branch -a" timeout=5 @cache ttl=86400
@query "docker ps --format json" timeout=5 @cache ttl=86400
@query "docker images -q" timeout=5 @cache ttl=86400
@query "df -h /" timeout=5 @cache ttl=86400
@query "free -m" timeout=5 @cache ttl=86400
@query "uptime" timeout=5 @cache ttl=86400
@services
  - name: api-gateway
    url: http://localhost:8080/health
    timeout: 2
  - name: auth-service
    url: http://localhost:8081/health
    timeout: 2
  - name: user-service
    url: http://localhost:8082/health
    timeout: 2
  - name: billing
    url: http://localhost:8083/health
    timeout: 2
  - name: notifications
    url: http://localhost:8084/health
    timeout: 2
  - name: search
    url: http://localhost:8085/health
    timeout: 2
  - name: analytics
    url: http://localhost:8086/health
    timeout: 2
  - name: cdn
    url: http://localhost:8087/health
    timeout: 2
  - name: db-proxy
    url: http://localhost:8088/health
    timeout: 2
  - name: cache
    url: http://localhost:8089/health
    timeout: 2
  - name: queue
    url: http://localhost:8090/health
    timeout: 2
  - name: scheduler
    url: http://localhost:8091/health
    timeout: 2
  - name: storage
    url: http://localhost:8092/health
    timeout: 2
  - name: monitor
    url: http://localhost:8093/health
    timeout: 2
  - name: logger
    url: http://localhost:8094/health
    timeout: 2
  - name: config
    url: http://localhost:8095/health
    timeout: 2
@read /etc/os-release
@read /proc/cpuinfo
@read /proc/meminfo
@read /etc/hosts
@read /etc/resolv.conf
@read /proc/loadavg
@read /proc/uptime
@read /proc/net/dev
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@memory focus="recent"
@inbox
@drift
@prefetch
@synthesize
@graph @focus="dependencies"
@query "cat /etc/hostname" timeout=5 @cache ttl=86400
@query "uname -a" timeout=5 @cache ttl=86400
@query "lscpu" timeout=5 @cache ttl=86400
@query "lsblk" timeout=5 @cache ttl=86400
@query "ip addr show" timeout=5 @cache ttl=86400
@query "ss -tlnp" timeout=5 @cache ttl=86400
@query "journalctl -n 10 --no-pager" timeout=5 @cache ttl=86400
@query "systemctl list-units --type=service --state=running" timeout=5 @cache ttl=86400
@query "sysctl -n vm.swappiness" timeout=5 @cache ttl=86400
@query "ls -la /var/log/" timeout=5 @cache ttl=86400
@query "which docker kubectl helm terraform" timeout=5 @cache ttl=86400
@query "docker info --format json" timeout=5 @cache ttl=86400
@query "docker stats --no-stream --format json" timeout=5 @cache ttl=86400
@query "kubectl version --short" timeout=5 @cache ttl=86400
@query "kubectl get nodes -o wide" timeout=5 @cache ttl=86400
@query "kubectl get pods --all-namespaces" timeout=5 @cache ttl=86400
@query "helm list --all-namespaces" timeout=5 @cache ttl=86400
@query "kubectl get services --all-namespaces" timeout=5 @cache ttl=86400
@query "kubectl get configmaps --all-namespaces" timeout=5 @cache ttl=86400
@query "kubectl get secrets --all-namespaces" timeout=5 @cache ttl=86400
@query "curl -s localhost:8080/health" timeout=5 @cache ttl=86400
@query "curl -s localhost:9090/metrics" timeout=5 @cache ttl=86400
@query "df -i /" timeout=5 @cache ttl=86400
@query "mount | grep nfs" timeout=5 @cache ttl=86400
@query "lsmod" timeout=5 @cache ttl=86400
@query "dmesg -T | tail -20" timeout=5 @cache ttl=86400
@query "ps aux --sort=-%mem | head -20" timeout=5 @cache ttl=86400
@query "top -bn1 | head -20" timeout=5 @cache ttl=86400
@query "vmstat 1 1" timeout=5 @cache ttl=86400
@query "iostat -x 1 1" timeout=5 @cache ttl=86400
@query "netstat -i" timeout=5 @cache ttl=86400
@query "ping -c 1 localhost" timeout=5 @cache ttl=86400
@query "traceroute -q 1 localhost" timeout=5 @cache ttl=86400
@query "hostnamectl" timeout=5 @cache ttl=86400
@query "timedatectl" timeout=5 @cache ttl=86400
@query "localectl" timeout=5 @cache ttl=86400
@query "loginctl list-sessions" timeout=5 @cache ttl=86400
@query "cat /proc/1/cmdline" timeout=5 @cache ttl=86400
@query "ls -la /etc/ssl/" timeout=5 @cache ttl=86400

@mneme query="infrastructure deployment"