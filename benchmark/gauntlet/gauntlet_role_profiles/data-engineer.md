@perseus v0.8
@prompt You are a simulated data engineer working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=86400
@query "git status" timeout=5 @cache ttl=86400
@query "spark-submit --version" timeout=5 @cache ttl=86400
@query "airflow version" timeout=5 @cache ttl=86400
@query "python3 --version" timeout=5 @cache ttl=86400
@query "pip list --format=columns" timeout=5 @cache ttl=86400
@query "dbt --version" timeout=5 @cache ttl=86400
@query "sqlfluff --version" timeout=5 @cache ttl=86400
@query "presto --version" timeout=5 @cache ttl=86400
@query "trino --version" timeout=5 @cache ttl=86400
@query "jq --version" timeout=5 @cache ttl=86400
@query "duckdb --version" timeout=5 @cache ttl=86400
@query "df -h /data" timeout=5 @cache ttl=86400
@query "free -h" timeout=5 @cache ttl=86400
@query "ls -la /data/" timeout=5 @cache ttl=86400
@query "wc -l /data/*.parquet 2>/dev/null" timeout=5 @cache ttl=86400
@query "cat /etc/hosts" timeout=5 @cache ttl=86400
@query "getent hosts db-primary" timeout=5 @cache ttl=86400
@query "nc -zv localhost 5432" timeout=5 @cache ttl=86400
@query "nc -zv localhost 3306" timeout=5 @cache ttl=86400
@services
  - name: trino-coordinator
    url: http://localhost:8080/health
    timeout: 2
  - name: airflow-webserver
    url: http://localhost:8081/health
    timeout: 2
  - name: airflow-scheduler
    url: http://localhost:8082/health
    timeout: 2
  - name: spark-history
    url: http://localhost:18080/
    timeout: 2
  - name: metastore
    url: http://localhost:9083/health
    timeout: 2
  - name: dbt-docs
    url: http://localhost:8083/health
    timeout: 2
  - name: minio
    url: http://localhost:9000/minio/health/live
    timeout: 2
  - name: kafka
    url: http://localhost:9092/health
    timeout: 2
  - name: schema-registry
    url: http://localhost:8084/health
    timeout: 2
  - name: datahub
    url: http://localhost:8085/health
    timeout: 2
  - name: great-expectations
    url: http://localhost:8086/health
    timeout: 2
  - name: superset
    url: http://localhost:8088/health
    timeout: 2
  - name: kestra
    url: http://localhost:8087/health
    timeout: 2
  - name: dagster
    url: http://localhost:3000/health
    timeout: 2
  - name: nifi
    url: http://localhost:8443/nifi-api/system-diagnostics
    timeout: 2
  - name: tableau
    url: http://localhost:8090/health
    timeout: 2
  - name: metabase
    url: http://localhost:3001/health
    timeout: 2
  - name: debezium
    url: http://localhost:8089/health
    timeout: 2
  - name: flink
    url: http://localhost:8081/flink
    timeout: 2
  - name: druid
    url: http://localhost:8888/status/health
    timeout: 2
@read /workspace/perseus/requirements.txt
@read /workspace/perseus/pyproject.toml
@waypoint ttl=86400
@skills flag_stale=true
@health
@agora status=open,in_progress
@memory focus="recent"
@inbox
@drift
