@perseus v0.8
@prompt You are a simulated performance engineer working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=86400
@query "perf --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "perf list | head -20" timeout=5 @cache ttl=86400
@query "flamegraph --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "sysbench --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "sysbench cpu run --threads=4 --time=5" timeout=5 @cache ttl=86400
@query "sysbench memory run --threads=4 --time=5" timeout=5 @cache ttl=86400
@query "sysbench fileio --file-test-mode=seqwr prepare 2>/dev/null" timeout=5 @cache ttl=86400
@query "sysbench fileio --file-test-mode=seqrd run 2>/dev/null" timeout=5 @cache ttl=86400
@query "stress-ng --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "stress-ng --cpu 2 --timeout 5s --metrics-brief 2>/dev/null" timeout=5 @cache ttl=86400
@query "dd if=/dev/zero of=/tmp/test bs=1M count=1024 oflag=direct 2>&1" timeout=5 @cache ttl=86400
@query "dd if=/tmp/test of=/dev/null bs=1M iflag=direct 2>&1" timeout=5 @cache ttl=86400
@query "hdparm -Tt /dev/sda 2>/dev/null" timeout=5 @cache ttl=86400
@query "fio --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "ioping -c 5 /tmp 2>/dev/null" timeout=5 @cache ttl=86400
@query "ioping -R /tmp 2>/dev/null" timeout=5 @cache ttl=86400
@query "df -h" timeout=5 @cache ttl=86400
@query "df -i /" timeout=5 @cache ttl=86400
@query "free -m" timeout=5 @cache ttl=86400
@query "free -h" timeout=5 @cache ttl=86400
@query "uptime" timeout=5 @cache ttl=86400
@query "uname -a" timeout=5 @cache ttl=86400
@query "hostnamectl" timeout=5 @cache ttl=86400
@query "lscpu | grep 'CPU(s)'" timeout=5 @cache ttl=86400
@query "lscpu | grep 'MHz'" timeout=5 @cache ttl=86400
@query "cat /proc/cpuinfo | grep 'model name' | head -1" timeout=5 @cache ttl=86400
@query "cat /proc/meminfo" timeout=5 @cache ttl=86400
@query "cat /proc/loadavg" timeout=5 @cache ttl=86400
@query "cat /proc/uptime" timeout=5 @cache ttl=86400
@query "cat /proc/schedstat | head -10" timeout=5 @cache ttl=86400
@query "cat /proc/interrupts | head -20" timeout=5 @cache ttl=86400
@query "cat /proc/softirqs | head -20" timeout=5 @cache ttl=86400
@query "cat /proc/stat | head -10" timeout=5 @cache ttl=86400
@query "cat /proc/zoneinfo | head -30" timeout=5 @cache ttl=86400
@query "vmstat 1 5" timeout=5 @cache ttl=86400
@query "iostat -x 1 5" timeout=5 @cache ttl=86400
@query "mpstat -P ALL 1 1" timeout=5 @cache ttl=86400
@query "pidstat -l 1 5" timeout=5 @cache ttl=86400
@query "sar -u 1 5" timeout=5 @cache ttl=86400
@query "sar -r 1 5" timeout=5 @cache ttl=86400
@query "sar -n DEV 1 5" timeout=5 @cache ttl=86400
@query "ps aux --sort=-%cpu | head -15" timeout=5 @cache ttl=86400
@query "ps aux --sort=-%mem | head -15" timeout=5 @cache ttl=86400
@query "top -bn1 | head -30" timeout=5 @cache ttl=86400
@query "lsof | wc -l" timeout=5 @cache ttl=86400
@query "ulimit -a" timeout=5 @cache ttl=86400
@query "sysctl -a --pattern 'kernel.(pid_max|hostname|osrelease|sched)'" timeout=5 @cache ttl=86400
@query "ls -la /sys/devices/system/cpu/" timeout=5 @cache ttl=86400
@query "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor" timeout=5 @cache ttl=86400
@services
  - name: grafana-dash
    url: http://localhost:3000/health
    timeout: 2
  - name: prometheus-perf
    url: http://localhost:9090/health
    timeout: 2
  - name: jaeger-perf
    url: http://localhost:16686/health
    timeout: 2
  - name: pyroscope
    url: http://localhost:4040/health
    timeout: 2
  - name: parca
    url: http://localhost:7070/health
    timeout: 2
  - name: netdata
    url: http://localhost:19999/health
    timeout: 2
  - name: glances
    url: http://localhost:61208/health
    timeout: 2
@read /proc/cpuinfo
@read /proc/meminfo
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@inbox
@drift
