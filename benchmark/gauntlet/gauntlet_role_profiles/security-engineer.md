@perseus v0.8
@prompt You are a simulated security engineer working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "lynis audit system --quick 2>/dev/null || echo lynis not installed" @cache ttl=300
@query "trivy --version 2>/dev/null || echo trivy not installed" @cache ttl=300
@query "nmap --version" @cache ttl=300
@query "grep --version" @cache ttl=300
@query "openssl version" @cache ttl=300
@query "gnutls-cli --version" @cache ttl=300
@query "ssh -V" @cache ttl=300
@query "gpg --version" @cache ttl=300
@query "find / -perm -4000 -type f 2>/dev/null | head -20" @cache ttl=300
@query "find / -perm -2000 -type f 2>/dev/null | head -20" @cache ttl=300
@query "cat /etc/passwd | cut -d: -f1,3,7 | head -30" @cache ttl=300
@query "cat /etc/shadow | cut -d: -f1,2 | head -10" @cache ttl=300
@query "cat /etc/group | head -20" @cache ttl=300
@query "cat /etc/sudoers 2>/dev/null" @cache ttl=300
@query "cat /etc/ssh/sshd_config | grep -v '^#' | grep -v '^$'" @cache ttl=300
@query "cat /etc/ssh/ssh_config" @cache ttl=300
@query "ls -la /etc/ssl/" @cache ttl=300
@query "ls -la /etc/letsencrypt/ 2>/dev/null" @cache ttl=300
@query "openssl version -a" @cache ttl=300
@query "openssl ciphers -v 'HIGH:!aNULL:!eNULL' | wc -l" @cache ttl=300
@query "ss -tlnp | grep LISTEN" @cache ttl=300
@query "ss -ulnp | grep LISTEN" @cache ttl=300
@query "netstat -tulpn 2>/dev/null || echo netstat not available" @cache ttl=300
@query "lsof -i -P -n | head -30" @cache ttl=300
@query "firewall-cmd --list-all 2>/dev/null" @cache ttl=300
@query "ufw status verbose 2>/dev/null" @cache ttl=300
@query "iptables -L -n -v" @cache ttl=300
@query "auditctl -l 2>/dev/null || echo auditd not running" @cache ttl=300
@query "ausearch -m USER_LOGIN -ts today 2>/dev/null" @cache ttl=300
@query "cat /var/log/auth.log 2>/dev/null | tail -20" @cache ttl=300
@query "cat /var/log/secure 2>/dev/null | tail -20" @cache ttl=300
@query "journalctl -u sshd --no-pager -n 20" @cache ttl=300
@query "ls -la /var/log/audit/ 2>/dev/null" @cache ttl=300
@query "clamscan --version 2>/dev/null" @cache ttl=300
@query "rkhunter --version 2>/dev/null" @cache ttl=300
@query "chkrootkit --version 2>/dev/null" @cache ttl=300
@query "aide --version 2>/dev/null" @cache ttl=300
@query "tripwire --version 2>/dev/null" @cache ttl=300
@query "ls -la /etc/cron*" @cache ttl=300
@query "cat /etc/crontab" @cache ttl=300
@query "cat /etc/anacrontab 2>/dev/null" @cache ttl=300
@query "systemctl list-timers --all" @cache ttl=300
@services
  - name: vault
    url: http://localhost:8200/health
    timeout: 2
  - name: wazuh
    url: http://localhost:55000/health
    timeout: 2
  - name: splunk
    url: http://localhost:8089/health
    timeout: 2
  - name: elasticsearch
    url: http://localhost:9200/health
    timeout: 2
  - name: kibana
    url: http://localhost:5601/health
    timeout: 2
  - name: sonarqube
    url: http://localhost:9000/health
    timeout: 2
  - name: defectdojo
    url: http://localhost:8080/health
    timeout: 2
  - name: hashicorp-vault
    url: http://localhost:8200/health
    timeout: 2
  - name: crowdstrike
    url: http://localhost:8088/health
    timeout: 2
  - name: sophos
    url: http://localhost:8090/health
    timeout: 2
  - name: sentry
    url: http://localhost:9001/health
    timeout: 2
@read /etc/os-release
@read /etc/passwd
@read /etc/group
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@inbox
@drift
@memory focus="recent"
