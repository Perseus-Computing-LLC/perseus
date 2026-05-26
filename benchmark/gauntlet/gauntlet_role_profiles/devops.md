@perseus v0.8
@prompt You are a simulated devops working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "git status" @cache ttl=300
@query "git diff --stat" @cache ttl=300
@query "kubectl version --short" @cache ttl=300
@query "kubectl get nodes -o wide" @cache ttl=300
@query "kubectl get pods --all-namespaces" @cache ttl=300
@query "kubectl get svc --all-namespaces" @cache ttl=300
@query "kubectl get deployments --all-namespaces" @cache ttl=300
@query "kubectl get configmaps" @cache ttl=300
@query "kubectl get secrets" @cache ttl=300
@query "kubectl get ingress --all-namespaces" @cache ttl=300
@query "kubectl get pv" @cache ttl=300
@query "kubectl get pvc --all-namespaces" @cache ttl=300
@query "kubectl top nodes" @cache ttl=300
@query "kubectl top pods --all-namespaces" @cache ttl=300
@query "terraform version" @cache ttl=300
@query "terraform workspace list" @cache ttl=300
@query "terraform state list" @cache ttl=300
@query "terraform output" @cache ttl=300
@query "helm list --all-namespaces" @cache ttl=300
@query "helm repo list" @cache ttl=300
@query "docker ps --format json" @cache ttl=300
@query "docker images -q" @cache ttl=300
@query "docker system df" @cache ttl=300
@query "docker info --format json" @cache ttl=300
@query "docker compose ps" @cache ttl=300
@query "docker network ls" @cache ttl=300
@query "docker volume ls" @cache ttl=300
@query "ansible --version" @cache ttl=300
@query "ansible-inventory --list" @cache ttl=300
@query "ansible all --list-hosts" @cache ttl=300
@query "ssh -G example.com" @cache ttl=300
@query "curl -sI https://example.com" @cache ttl=300
@query "curl -s localhost:8080/health" @cache ttl=300
@query "curl -s localhost:9090/metrics" @cache ttl=300
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
@query "iptables -L -n --line-numbers" @cache ttl=300
@query "nft list ruleset" @cache ttl=300
@query "ping -c 3 8.8.8.8" @cache ttl=300
@query "traceroute -q 1 8.8.8.8" @cache ttl=300
@query "nslookup google.com" @cache ttl=300
@query "dig +short google.com" @cache ttl=300
@query "nc -zv localhost 443" @cache ttl=300
@query "lsblk" @cache ttl=300
@query "mount | grep nfs" @cache ttl=300
@query "journalctl -n 20 --no-pager" @cache ttl=300
@query "systemctl list-units --type=service" @cache ttl=300
@query "systemctl list-timers" @cache ttl=300
@query "systemctl status docker" @cache ttl=300
@query "ps aux --sort=-%cpu | head -20" @cache ttl=300
@query "ps aux --sort=-%mem | head -20" @cache ttl=300
@query "top -bn1 | head -30" @cache ttl=300
@query "htop --version" @cache ttl=300
@query "vmstat 1 1" @cache ttl=300
@query "iostat -x 1 1" @cache ttl=300
@query "sar -u 1 1" @cache ttl=300
@query "lsof -iTCP -sTCP:LISTEN -P -n" @cache ttl=300
@query "lsof | wc -l" @cache ttl=300
@query "ulimit -a" @cache ttl=300
@query "sysctl -a --pattern 'kernel.(pid_max|hostname|osrelease)'" @cache ttl=300
@query "cat /proc/cpuinfo | grep 'model name' | head -1" @cache ttl=300
@query "cat /proc/meminfo | head -10" @cache ttl=300
@query "cat /proc/loadavg" @cache ttl=300
@query "cat /proc/uptime" @cache ttl=300
@query "cat /etc/os-release" @cache ttl=300
@query "cat /etc/hosts" @cache ttl=300
@query "cat /etc/resolv.conf" @cache ttl=300
@query "cat /etc/hostname" @cache ttl=300
@query "which docker kubectl helm terraform ansible ssh curl" @cache ttl=300
@query "ls -la /var/log/" @cache ttl=300
@query "tail -20 /var/log/syslog 2>/dev/null || tail -20 /var/log/messages" @cache ttl=300
@query "dmesg -T | tail -20" @cache ttl=300
@query "last -10" @cache ttl=300
@query "w" @cache ttl=300
@query "who" @cache ttl=300
@query "id" @cache ttl=300
@query "lscpu" @cache ttl=300
@query "lsmod" @cache ttl=300
@query "modprobe --version" @cache ttl=300
@query "depmod --version" @cache ttl=300
@query "ip link show" @cache ttl=300
@query "bridge link show" @cache ttl=300
@query "netstat -s" @cache ttl=300
@query "ss -s" @cache ttl=300
@query "tc qdisc show" @cache ttl=300
@query "ethtool --version" @cache ttl=300
@query "mtr --version" @cache ttl=300
@query "tcpdump --version" @cache ttl=300
@query "wireshark --version" @cache ttl=300
@query "nmap --version" @cache ttl=300
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
