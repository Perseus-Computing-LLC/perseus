@perseus v0.8
@prompt You are a simulated security engineer working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=86400
@query "lynis audit system --quick 2>/dev/null || echo lynis not installed" timeout=5 @cache ttl=86400
@query "trivy --version 2>/dev/null || echo trivy not installed" timeout=5 @cache ttl=86400
@query "nmap --version" timeout=5 @cache ttl=86400
@query "grep --version" timeout=5 @cache ttl=86400
@query "openssl version" timeout=5 @cache ttl=86400
@query "gnutls-cli --version" timeout=5 @cache ttl=86400
@query "ssh -V" timeout=5 @cache ttl=86400
@query "gpg --version" timeout=5 @cache ttl=86400
@query "find / -perm -4000 -type f 2>/dev/null | head -20" timeout=5 @cache ttl=86400
@query "find / -perm -2000 -type f 2>/dev/null | head -20" timeout=5 @cache ttl=86400
@query "cat /etc/passwd | cut -d: -f1,3,7 | head -30" timeout=5 @cache ttl=86400
@query "cat /etc/shadow | cut -d: -f1,2 | head -10" timeout=5 @cache ttl=86400
@query "cat /etc/group | head -20" timeout=5 @cache ttl=86400
@query "cat /etc/sudoers 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat /etc/ssh/sshd_config | grep -v '^#' | grep -v '^$'" timeout=5 @cache ttl=86400
@query "cat /etc/ssh/ssh_config" timeout=5 @cache ttl=86400
@query "ls -la /etc/ssl/" timeout=5 @cache ttl=86400
@query "ls -la /etc/letsencrypt/ 2>/dev/null" timeout=5 @cache ttl=86400
@query "openssl version -a" timeout=5 @cache ttl=86400
@query "openssl ciphers -v 'HIGH:!aNULL:!eNULL' | wc -l" timeout=5 @cache ttl=86400
@query "ss -tlnp | grep LISTEN" timeout=5 @cache ttl=86400
@query "ss -ulnp | grep LISTEN" timeout=5 @cache ttl=86400
@query "netstat -tulpn 2>/dev/null || echo netstat not available" timeout=5 @cache ttl=86400
@query "lsof -i -P -n | head -30" timeout=5 @cache ttl=86400
@query "firewall-cmd --list-all 2>/dev/null" timeout=5 @cache ttl=86400
@query "ufw status verbose 2>/dev/null" timeout=5 @cache ttl=86400
@query "iptables -L -n -v" timeout=5 @cache ttl=86400
@query "auditctl -l 2>/dev/null || echo auditd not running" timeout=5 @cache ttl=86400
@query "ausearch -m USER_LOGIN -ts today 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat /var/log/auth.log 2>/dev/null | tail -20" timeout=5 @cache ttl=86400
@query "cat /var/log/secure 2>/dev/null | tail -20" timeout=5 @cache ttl=86400
@query "journalctl -u sshd --no-pager -n 20" timeout=5 @cache ttl=86400
@query "ls -la /var/log/audit/ 2>/dev/null" timeout=5 @cache ttl=86400
@query "clamscan --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "rkhunter --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "chkrootkit --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "aide --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "tripwire --version 2>/dev/null" timeout=5 @cache ttl=86400
@query "ls -la /etc/cron*" timeout=5 @cache ttl=86400
@query "cat /etc/crontab" timeout=5 @cache ttl=86400
@query "cat /etc/anacrontab 2>/dev/null" timeout=5 @cache ttl=86400
@query "systemctl list-timers --all" timeout=5 @cache ttl=86400
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
@memory focus="decisions"
