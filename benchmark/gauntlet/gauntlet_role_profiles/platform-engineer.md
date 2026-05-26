@perseus v0.8
@prompt You are a simulated platform engineer working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "git diff --stat HEAD~1" @cache ttl=300
@query "git branch -a" @cache ttl=300
@query "docker ps --format json" @cache ttl=300
@query "docker images -q" @cache ttl=300
@query "df -h /" @cache ttl=300
@query "free -m" @cache ttl=300
@query "uptime" @cache ttl=300
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
@query "cat /etc/hostname" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "lscpu" @cache ttl=300
@query "lsblk" @cache ttl=300
@query "ip addr show" @cache ttl=300
@query "ss -tlnp" @cache ttl=300
@query "journalctl -n 10 --no-pager" @cache ttl=300
@query "systemctl list-units --type=service --state=running" @cache ttl=300
@query "sysctl -n vm.swappiness" @cache ttl=300
@query "ls -la /var/log/" @cache ttl=300
@query "which docker kubectl helm terraform" @cache ttl=300
@query "docker info --format json" @cache ttl=300
@query "docker stats --no-stream --format json" @cache ttl=300
@query "kubectl version --short" @cache ttl=300
@query "kubectl get nodes -o wide" @cache ttl=300
@query "kubectl get pods --all-namespaces" @cache ttl=300
@query "helm list --all-namespaces" @cache ttl=300
@query "kubectl get services --all-namespaces" @cache ttl=300
@query "kubectl get configmaps --all-namespaces" @cache ttl=300
@query "kubectl get secrets --all-namespaces" @cache ttl=300
@query "curl -s localhost:8080/health" @cache ttl=300
@query "curl -s localhost:9090/metrics" @cache ttl=300
@query "df -i /" @cache ttl=300
@query "mount | grep nfs" @cache ttl=300
@query "lsmod" @cache ttl=300
@query "dmesg -T | tail -20" @cache ttl=300
@query "ps aux --sort=-%mem | head -20" @cache ttl=300
@query "top -bn1 | head -20" @cache ttl=300
@query "vmstat 1 1" @cache ttl=300
@query "iostat -x 1 1" @cache ttl=300
@query "netstat -i" @cache ttl=300
@query "ping -c 1 localhost" @cache ttl=300
@query "traceroute -q 1 localhost" @cache ttl=300
@query "hostnamectl" @cache ttl=300
@query "timedatectl" @cache ttl=300
@query "localectl" @cache ttl=300
@query "loginctl list-sessions" @cache ttl=300
@query "cat /proc/1/cmdline" @cache ttl=300
@query "ls -la /etc/ssl/" @cache ttl=300
