@perseus v0.8
@prompt You are a simulated performance engineer working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "perf --version 2>/dev/null" @cache ttl=300
@query "perf list | head -20" @cache ttl=300
@query "flamegraph --version 2>/dev/null" @cache ttl=300
@query "sysbench --version 2>/dev/null" @cache ttl=300
@query "sysbench cpu run --threads=4 --time=5" @cache ttl=300
@query "sysbench memory run --threads=4 --time=5" @cache ttl=300
@query "sysbench fileio --file-test-mode=seqwr prepare 2>/dev/null" @cache ttl=300
@query "sysbench fileio --file-test-mode=seqrd run 2>/dev/null" @cache ttl=300
@query "stress-ng --version 2>/dev/null" @cache ttl=300
@query "stress-ng --cpu 2 --timeout 5s --metrics-brief 2>/dev/null" @cache ttl=300
@query "dd if=/dev/zero of=/tmp/test bs=1M count=1024 oflag=direct 2>&1" @cache ttl=300
@query "dd if=/tmp/test of=/dev/null bs=1M iflag=direct 2>&1" @cache ttl=300
@query "hdparm -Tt /dev/sda 2>/dev/null" @cache ttl=300
@query "fio --version 2>/dev/null" @cache ttl=300
@query "ioping -c 5 /tmp 2>/dev/null" @cache ttl=300
@query "ioping -R /tmp 2>/dev/null" @cache ttl=300
@query "df -h" @cache ttl=300
@query "df -i /" @cache ttl=300
@query "free -m" @cache ttl=300
@query "free -h" @cache ttl=300
@query "uptime" @cache ttl=300
@query "uname -a" @cache ttl=300
@query "hostnamectl" @cache ttl=300
@query "lscpu | grep 'CPU(s)'" @cache ttl=300
@query "lscpu | grep 'MHz'" @cache ttl=300
@query "cat /proc/cpuinfo | grep 'model name' | head -1" @cache ttl=300
@query "cat /proc/meminfo" @cache ttl=300
@query "cat /proc/loadavg" @cache ttl=300
@query "cat /proc/uptime" @cache ttl=300
@query "cat /proc/schedstat | head -10" @cache ttl=300
@query "cat /proc/interrupts | head -20" @cache ttl=300
@query "cat /proc/softirqs | head -20" @cache ttl=300
@query "cat /proc/stat | head -10" @cache ttl=300
@query "cat /proc/zoneinfo | head -30" @cache ttl=300
@query "vmstat 1 5" @cache ttl=300
@query "iostat -x 1 5" @cache ttl=300
@query "mpstat -P ALL 1 1" @cache ttl=300
@query "pidstat -l 1 5" @cache ttl=300
@query "sar -u 1 5" @cache ttl=300
@query "sar -r 1 5" @cache ttl=300
@query "sar -n DEV 1 5" @cache ttl=300
@query "ps aux --sort=-%cpu | head -15" @cache ttl=300
@query "ps aux --sort=-%mem | head -15" @cache ttl=300
@query "top -bn1 | head -30" @cache ttl=300
@query "lsof | wc -l" @cache ttl=300
@query "ulimit -a" @cache ttl=300
@query "sysctl -a --pattern 'kernel.(pid_max|hostname|osrelease|sched)'" @cache ttl=300
@query "ls -la /sys/devices/system/cpu/" @cache ttl=300
@query "cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor" @cache ttl=300
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
