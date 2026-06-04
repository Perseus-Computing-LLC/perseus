@perseus v0.8
@prompt You are a simulated devops working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=86400
@query "git status" timeout=5 @cache ttl=86400
@query "git diff --stat" timeout=5 @cache ttl=86400
@query "kubectl version --short" timeout=5 @cache ttl=86400
@query "kubectl get nodes -o wide" timeout=5 @cache ttl=86400
@query "kubectl get pods --all-namespaces" timeout=5 @cache ttl=86400
@query "kubectl get svc --all-namespaces" timeout=5 @cache ttl=86400
@query "kubectl get deployments --all-namespaces" timeout=5 @cache ttl=86400
@query "kubectl get configmaps" timeout=5 @cache ttl=86400
@query "kubectl get secrets" timeout=5 @cache ttl=86400
@query "kubectl get ingress --all-namespaces" timeout=5 @cache ttl=86400
@query "kubectl get pv" timeout=5 @cache ttl=86400
@query "kubectl get pvc --all-namespaces" timeout=5 @cache ttl=86400
@query "kubectl top nodes" timeout=5 @cache ttl=86400
@query "kubectl top pods --all-namespaces" timeout=5 @cache ttl=86400
@query "terraform version" timeout=5 @cache ttl=86400
@query "terraform workspace list" timeout=5 @cache ttl=86400
@query "terraform state list" timeout=5 @cache ttl=86400
@query "terraform output" timeout=5 @cache ttl=86400
@query "helm list --all-namespaces" timeout=5 @cache ttl=86400
@query "helm repo list" timeout=5 @cache ttl=86400
@query "docker ps --format json" timeout=5 @cache ttl=86400
@query "docker images -q" timeout=5 @cache ttl=86400
@query "docker system df" timeout=5 @cache ttl=86400
@query "docker info --format json" timeout=5 @cache ttl=86400
@query "docker compose ps" timeout=5 @cache ttl=86400
@query "docker network ls" timeout=5 @cache ttl=86400
@query "docker volume ls" timeout=5 @cache ttl=86400
@query "ansible --version" timeout=5 @cache ttl=86400
@query "ansible-inventory --list" timeout=5 @cache ttl=86400
@query "ansible all --list-hosts" timeout=5 @cache ttl=86400
@query "ssh -G example.com" timeout=5 @cache ttl=86400
@query "curl -sI https://example.com" timeout=5 @cache ttl=86400
@query "curl -s localhost:8080/health" timeout=5 @cache ttl=86400
@query "curl -s localhost:9090/metrics" timeout=5 @cache ttl=86400
@query "df -h" timeout=5 @cache ttl=86400
@query "df -i /" timeout=5 @cache ttl=86400
@query "free -m" timeout=5 @cache ttl=86400
@query "uptime" timeout=5 @cache ttl=86400
@query "uname -a" timeout=5 @cache ttl=86400
@query "hostnamectl" timeout=5 @cache ttl=86400
@query "timedatectl" timeout=5 @cache ttl=86400
@query "ip addr show" timeout=5 @cache ttl=86400
@query "ss -tlnp" timeout=5 @cache ttl=86400
@query "ss -ulnp" timeout=5 @cache ttl=86400
@query "iptables -L -n --line-numbers" timeout=5 @cache ttl=86400
@query "nft list ruleset" timeout=5 @cache ttl=86400
@query "ping -c 3 8.8.8.8" timeout=5 @cache ttl=86400
@query "traceroute -q 1 8.8.8.8" timeout=5 @cache ttl=86400
@query "nslookup google.com" timeout=5 @cache ttl=86400
@query "dig +short google.com" timeout=5 @cache ttl=86400
@query "nc -zv localhost 443" timeout=5 @cache ttl=86400
@query "lsblk" timeout=5 @cache ttl=86400
@query "mount | grep nfs" timeout=5 @cache ttl=86400
@query "journalctl -n 20 --no-pager" timeout=5 @cache ttl=86400
@query "systemctl list-units --type=service" timeout=5 @cache ttl=86400
@query "systemctl list-timers" timeout=5 @cache ttl=86400
@query "systemctl status docker" timeout=5 @cache ttl=86400
@query "ps aux --sort=-%cpu | head -20" timeout=5 @cache ttl=86400
@query "ps aux --sort=-%mem | head -20" timeout=5 @cache ttl=86400
@query "top -bn1 | head -30" timeout=5 @cache ttl=86400
@query "htop --version" timeout=5 @cache ttl=86400
@query "vmstat 1 1" timeout=5 @cache ttl=86400
@query "iostat -x 1 1" timeout=5 @cache ttl=86400
@query "sar -u 1 1" timeout=5 @cache ttl=86400
@query "lsof -iTCP -sTCP:LISTEN -P -n" timeout=5 @cache ttl=86400
@query "lsof | wc -l" timeout=5 @cache ttl=86400
@query "ulimit -a" timeout=5 @cache ttl=86400
@query "sysctl -a --pattern 'kernel.(pid_max|hostname|osrelease)'" timeout=5 @cache ttl=86400
@query "cat /proc/cpuinfo | grep 'model name' | head -1" timeout=5 @cache ttl=86400
@query "cat /proc/meminfo | head -10" timeout=5 @cache ttl=86400
@query "cat /proc/loadavg" timeout=5 @cache ttl=86400
@query "cat /proc/uptime" timeout=5 @cache ttl=86400
@query "cat /etc/os-release" timeout=5 @cache ttl=86400
@query "cat /etc/hosts" timeout=5 @cache ttl=86400
@query "cat /etc/resolv.conf" timeout=5 @cache ttl=86400
@query "cat /etc/hostname" timeout=5 @cache ttl=86400
@query "which docker kubectl helm terraform ansible ssh curl" timeout=5 @cache ttl=86400
@query "ls -la /var/log/" timeout=5 @cache ttl=86400
@query "tail -20 /var/log/syslog 2>/dev/null || tail -20 /var/log/messages" timeout=5 @cache ttl=86400
@query "dmesg -T | tail -20" timeout=5 @cache ttl=86400
@query "last -10" timeout=5 @cache ttl=86400
@query "w" timeout=5 @cache ttl=86400
@query "who" timeout=5 @cache ttl=86400
@query "id" timeout=5 @cache ttl=86400
@query "lscpu" timeout=5 @cache ttl=86400
@query "lsmod" timeout=5 @cache ttl=86400
@query "modprobe --version" timeout=5 @cache ttl=86400
@query "depmod --version" timeout=5 @cache ttl=86400
@query "ip link show" timeout=5 @cache ttl=86400
@query "bridge link show" timeout=5 @cache ttl=86400
@query "netstat -s" timeout=5 @cache ttl=86400
@query "ss -s" timeout=5 @cache ttl=86400
@query "tc qdisc show" timeout=5 @cache ttl=86400
@query "ethtool --version" timeout=5 @cache ttl=86400
@query "mtr --version" timeout=5 @cache ttl=86400
@query "tcpdump --version" timeout=5 @cache ttl=86400
@query "wireshark --version" timeout=5 @cache ttl=86400
@query "nmap --version" timeout=5 @cache ttl=86400
@services
  - name: svc-000
    url: http://localhost:9000/health
    timeout: 2
  - name: svc-001
    url: http://localhost:9001/health
    timeout: 2
  - name: svc-002
    url: http://localhost:9002/health
    timeout: 2
  - name: svc-003
    url: http://localhost:9003/health
    timeout: 2
  - name: svc-004
    url: http://localhost:9004/health
    timeout: 2
  - name: svc-005
    url: http://localhost:9005/health
    timeout: 2
  - name: svc-006
    url: http://localhost:9006/health
    timeout: 2
  - name: svc-007
    url: http://localhost:9007/health
    timeout: 2
  - name: svc-008
    url: http://localhost:9008/health
    timeout: 2
  - name: svc-009
    url: http://localhost:9009/health
    timeout: 2
  - name: svc-010
    url: http://localhost:9010/health
    timeout: 2
  - name: svc-011
    url: http://localhost:9011/health
    timeout: 2
  - name: svc-012
    url: http://localhost:9012/health
    timeout: 2
  - name: svc-013
    url: http://localhost:9013/health
    timeout: 2
  - name: svc-014
    url: http://localhost:9014/health
    timeout: 2
  - name: svc-015
    url: http://localhost:9015/health
    timeout: 2
  - name: svc-016
    url: http://localhost:9016/health
    timeout: 2
  - name: svc-017
    url: http://localhost:9017/health
    timeout: 2
  - name: svc-018
    url: http://localhost:9018/health
    timeout: 2
  - name: svc-019
    url: http://localhost:9019/health
    timeout: 2
  - name: svc-020
    url: http://localhost:9020/health
    timeout: 2
  - name: svc-021
    url: http://localhost:9021/health
    timeout: 2
  - name: svc-022
    url: http://localhost:9022/health
    timeout: 2
  - name: svc-023
    url: http://localhost:9023/health
    timeout: 2
  - name: svc-024
    url: http://localhost:9024/health
    timeout: 2
  - name: svc-025
    url: http://localhost:9025/health
    timeout: 2
  - name: svc-026
    url: http://localhost:9026/health
    timeout: 2
  - name: svc-027
    url: http://localhost:9027/health
    timeout: 2
  - name: svc-028
    url: http://localhost:9028/health
    timeout: 2
  - name: svc-029
    url: http://localhost:9029/health
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

@mneme query="docker container deploy"