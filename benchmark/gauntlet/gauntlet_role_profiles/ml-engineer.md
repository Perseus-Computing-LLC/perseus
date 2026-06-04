@perseus v0.8
@prompt You are a simulated ml engineer working inside a large enterprise.

@query "git log --oneline -5" timeout=5 @cache ttl=86400
@query "nvidia-smi" timeout=5 @cache ttl=86400
@query "pip list --format=columns" timeout=5 @cache ttl=86400
@query "python3 --version" timeout=5 @cache ttl=86400
@query "nvcc --version" timeout=5 @cache ttl=86400
@query "torch --version" timeout=5 @cache ttl=86400
@query "tensorflow --version" timeout=5 @cache ttl=86400
@query "jax --version" timeout=5 @cache ttl=86400
@query "transformers --version" timeout=5 @cache ttl=86400
@query "accelerate --version" timeout=5 @cache ttl=86400
@query "deepspeed --version" timeout=5 @cache ttl=86400
@query "flash-attn --version" timeout=5 @cache ttl=86400
@query "vllm --version" timeout=5 @cache ttl=86400
@query "triton --version" timeout=5 @cache ttl=86400
@query "wandb --version" timeout=5 @cache ttl=86400
@query "mlflow --version" timeout=5 @cache ttl=86400
@query "dvc --version" timeout=5 @cache ttl=86400
@query "cat /proc/cpuinfo | grep -c processor" timeout=5 @cache ttl=86400
@query "free -h" timeout=5 @cache ttl=86400
@query "df -h /workspace" timeout=5 @cache ttl=86400
@query "ls -la /workspace/data/" timeout=5 @cache ttl=86400
@query "ls /workspace/models/" timeout=5 @cache ttl=86400
@query "du -sh /workspace/models/" timeout=5 @cache ttl=86400
@services
  - name: mlflow
    url: http://localhost:5000/health
    timeout: 2
  - name: wandb
    url: http://localhost:8080/health
    timeout: 2
  - name: tensorboard
    url: http://localhost:6006/
    timeout: 2
  - name: jupyter
    url: http://localhost:8888/api
    timeout: 2
  - name: triton-server
    url: http://localhost:8000/v2/health/live
    timeout: 2
  - name: ray-dashboard
    url: http://localhost:8265/
    timeout: 2
  - name: label-studio
    url: http://localhost:8081/health
    timeout: 2
  - name: clearsml
    url: http://localhost:8082/health
    timeout: 2
  - name: optuna-db
    url: http://localhost:5432/health
    timeout: 2
  - name: dvc-remote
    url: http://localhost:9000/minio/health/live
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
@prefetch
@synthesize

@mneme query="model training benchmark"