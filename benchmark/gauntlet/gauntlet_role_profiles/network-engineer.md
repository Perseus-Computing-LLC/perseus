@perseus v0.8
@prompt You are a simulated network engineer working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "ip addr show" @cache ttl=300
@query "ip route show" @cache ttl=300
@query "ip neigh show" @cache ttl=300
@query "ss -tlnp" @cache ttl=300
@query "ss -ulnp" @cache ttl=300
@query "ss -s" @cache ttl=300
@query "iptables -L -n -v" @cache ttl=300
@query "iptables -t nat -L -n -v" @cache ttl=300
@query "nft list ruleset 2>/dev/null" @cache ttl=300
@query "ping -c 5 8.8.8.8" @cache ttl=300
@query "traceroute -q 1 8.8.8.8" @cache ttl=300
@query "mtr -r -c 3 8.8.8.8" @cache ttl=300
@query "nslookup google.com" @cache ttl=300
@query "dig +short google.com" @cache ttl=300
@query "dig +trace google.com | head -20" @cache ttl=300
@query "host google.com" @cache ttl=300
@query "whois google.com | head -10" @cache ttl=300
@query "curl -sI https://google.com" @cache ttl=300
@query "curl -s https://ifconfig.me" @cache ttl=300
@query "curl -s http://localhost:9090/metrics" @cache ttl=300
@query "nc -zv localhost 443" @cache ttl=300
@query "nc -zv localhost 80" @cache ttl=300
@query "tcpdump --version" @cache ttl=300
@query "tshark --version" @cache ttl=300
@query "tc qdisc show" @cache ttl=300
@query "tc class show dev lo" @cache ttl=300
@query "tc filter show dev lo" @cache ttl=300
@query "ethtool --version" @cache ttl=300
@query "ethtool lo" @cache ttl=300
@query "bridge link show" @cache ttl=300
@query "ip link show" @cache ttl=300
@query "ip netns list" @cache ttl=300
@query "ip maddr show" @cache ttl=300
@query "ip tunnel show" @cache ttl=300
@query "cat /proc/net/dev" @cache ttl=300
@query "cat /proc/net/tcp" @cache ttl=300
@query "cat /proc/net/udp" @cache ttl=300
@query "cat /proc/net/route" @cache ttl=300
@query "cat /etc/iproute2/rt_tables" @cache ttl=300
@query "cat /etc/resolv.conf" @cache ttl=300
@query "cat /etc/hosts" @cache ttl=300
@query "cat /etc/nsswitch.conf" @cache ttl=300
@query "cat /etc/sysctl.d/*.conf 2>/dev/null" @cache ttl=300
@services
  - name: net-0
    url: http://localhost:8000/health
    timeout: 2
  - name: net-1
    url: http://localhost:8001/health
    timeout: 2
  - name: net-2
    url: http://localhost:8002/health
    timeout: 2
  - name: net-3
    url: http://localhost:8003/health
    timeout: 2
  - name: net-4
    url: http://localhost:8004/health
    timeout: 2
  - name: net-5
    url: http://localhost:8005/health
    timeout: 2
  - name: net-6
    url: http://localhost:8006/health
    timeout: 2
  - name: net-7
    url: http://localhost:8007/health
    timeout: 2
  - name: net-8
    url: http://localhost:8008/health
    timeout: 2
  - name: net-9
    url: http://localhost:8009/health
    timeout: 2
  - name: net-10
    url: http://localhost:8010/health
    timeout: 2
  - name: net-11
    url: http://localhost:8011/health
    timeout: 2
  - name: net-12
    url: http://localhost:8012/health
    timeout: 2
  - name: net-13
    url: http://localhost:8013/health
    timeout: 2
  - name: net-14
    url: http://localhost:8014/health
    timeout: 2
  - name: net-15
    url: http://localhost:8015/health
    timeout: 2
  - name: net-16
    url: http://localhost:8016/health
    timeout: 2
  - name: net-17
    url: http://localhost:8017/health
    timeout: 2
  - name: net-18
    url: http://localhost:8018/health
    timeout: 2
  - name: net-19
    url: http://localhost:8019/health
    timeout: 2
  - name: net-20
    url: http://localhost:8020/health
    timeout: 2
  - name: net-21
    url: http://localhost:8021/health
    timeout: 2
  - name: net-22
    url: http://localhost:8022/health
    timeout: 2
  - name: net-23
    url: http://localhost:8023/health
    timeout: 2
  - name: net-24
    url: http://localhost:8024/health
    timeout: 2
  - name: net-25
    url: http://localhost:8025/health
    timeout: 2
  - name: net-26
    url: http://localhost:8026/health
    timeout: 2
  - name: net-27
    url: http://localhost:8027/health
    timeout: 2
  - name: net-28
    url: http://localhost:8028/health
    timeout: 2
  - name: net-29
    url: http://localhost:8029/health
    timeout: 2
@read /etc/hosts
@read /etc/resolv.conf
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@inbox
@drift
