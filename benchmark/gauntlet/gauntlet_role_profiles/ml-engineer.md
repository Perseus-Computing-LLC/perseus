@perseus v0.8
@prompt You are a simulated ml engineer working inside a large enterprise.

@query "git log --oneline -5" @cache ttl=300
@query "nvidia-smi" @cache ttl=300
@query "pip list --format=columns" @cache ttl=300
@query "python3 --version" @cache ttl=300
@query "nvcc --version" @cache ttl=300
@query "torch --version" @cache ttl=300
@query "tensorflow --version" @cache ttl=300
@query "jax --version" @cache ttl=300
@query "transformers --version" @cache ttl=300
@query "accelerate --version" @cache ttl=300
@query "deepspeed --version" @cache ttl=300
@query "flash-attn --version" @cache ttl=300
@query "vllm --version" @cache ttl=300
@query "triton --version" @cache ttl=300
@query "wandb --version" @cache ttl=300
@query "mlflow --version" @cache ttl=300
@query "dvc --version" @cache ttl=300
@query "cat /proc/cpuinfo | grep -c processor" @cache ttl=300
@query "free -h" @cache ttl=300
@query "df -h /workspace" @cache ttl=300
@query "ls -la /workspace/data/" @cache ttl=300
@query "ls /workspace/models/" @cache ttl=300
@query "du -sh /workspace/models/" @cache ttl=300
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