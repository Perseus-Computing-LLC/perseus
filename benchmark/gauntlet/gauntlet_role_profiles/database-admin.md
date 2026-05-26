@perseus v0.8
@prompt You are a simulated database admin working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "psql --version 2>/dev/null" @cache ttl=300
@query "mongod --version 2>/dev/null" @cache ttl=300
@query "mysql --version 2>/dev/null" @cache ttl=300
@query "redis-server --version 2>/dev/null" @cache ttl=300
@query "pg_isready 2>/dev/null" @cache ttl=300
@query "pg_lsclusters 2>/dev/null" @cache ttl=300
@query "pg_stat_statements --version 2>/dev/null" @cache ttl=300
@query "cat /etc/postgresql/*/main/pg_hba.conf 2>/dev/null | head -20" @cache ttl=300
@query "cat /etc/postgresql/*/main/postgresql.conf 2>/dev/null | grep -v '^#' | head -30" @cache ttl=300
@query "cat /etc/mysql/my.cnf 2>/dev/null" @cache ttl=300
@query "cat /etc/redis/redis.conf 2>/dev/null | head -20" @cache ttl=300
@query "du -sh /var/lib/postgresql/ 2>/dev/null" @cache ttl=300
@query "du -sh /var/lib/mongodb/ 2>/dev/null" @cache ttl=300
@query "df -h /var/lib/postgresql/ 2>/dev/null" @cache ttl=300
@query "free -h" @cache ttl=300
@query "vmstat 1 1" @cache ttl=300
@query "iostat -x 1 1" @cache ttl=300
@query "sysctl -a --pattern 'kernel.shmmax'" @cache ttl=300
@query "sysctl -a --pattern 'kernel.shmall'" @cache ttl=300
@query "ls -la /var/lib/postgresql/*/main/ 2>/dev/null" @cache ttl=300
@query "pg_ctl --version 2>/dev/null" @cache ttl=300
@query "mongosh --version 2>/dev/null" @cache ttl=300
@query "redis-cli --version" @cache ttl=300
@query "redis-cli ping 2>/dev/null" @cache ttl=300
@query "redis-cli INFO server | head -10" @cache ttl=300
@query "nc -zv localhost 5432" @cache ttl=300
@query "nc -zv localhost 27017" @cache ttl=300
@query "nc -zv localhost 6379" @cache ttl=300
@services
  - name: postgres-primary
    url: http://localhost:5432/health
    timeout: 2
  - name: postgres-replica
    url: http://localhost:5433/health
    timeout: 2
  - name: postgres-pgbouncer
    url: http://localhost:6432/health
    timeout: 2
  - name: mongodb-primary
    url: http://localhost:27017/health
    timeout: 2
  - name: mongodb-secondary
    url: http://localhost:27018/health
    timeout: 2
  - name: redis-master
    url: http://localhost:6379/health
    timeout: 2
  - name: redis-sentinel
    url: http://localhost:26379/health
    timeout: 2
  - name: mysql-primary
    url: http://localhost:3306/health
    timeout: 2
  - name: mysql-backup
    url: http://localhost:3307/health
    timeout: 2
  - name: cassandra
    url: http://localhost:9042/health
    timeout: 2
  - name: cockroachdb
    url: http://localhost:26257/health
    timeout: 2
  - name: timescaledb
    url: http://localhost:5434/health
    timeout: 2
  - name: dragonfly
    url: http://localhost:6380/health
    timeout: 2
  - name: valkey
    url: http://localhost:6378/health
    timeout: 2
  - name: scylla
    url: http://localhost:9043/health
    timeout: 2
  - name: vitess
    url: http://localhost:15999/health
    timeout: 2
  - name: patroni
    url: http://localhost:8008/health
    timeout: 2
  - name: debezium
    url: http://localhost:8080/health
    timeout: 2
@read /etc/hosts
@read /etc/resolv.conf
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@inbox
