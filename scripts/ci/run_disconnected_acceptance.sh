#!/usr/bin/env bash
set -euo pipefail

workspace="${GITHUB_WORKSPACE:-$(pwd)}"
workspace="$(realpath -e "${workspace}")"
run_id="${GITHUB_RUN_ID:-local-$$}"
if [[ ! "${run_id}" =~ ^[A-Za-z0-9_.-]+$ ]]; then
    echo "invalid run identity" >&2
    exit 1
fi

python_candidate="/usr/bin/python3"
if [ ! -x "${python_candidate}" ]; then
    echo "trusted system Python is unavailable: ${python_candidate}" >&2
    exit 1
fi
python_bin="$(realpath -e "${python_candidate}")"
python_owner="$(stat -c '%u' "${python_bin}")"
python_mode="$(stat -c '%a' "${python_bin}")"
if [ "${python_owner}" != "0" ] || (( (8#${python_mode}) & 18 )); then
    echo "trusted system Python has unsafe ownership or mode" >&2
    exit 1
fi
python_version="$("${python_bin}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

broker_root="/sys/fs/cgroup/perseus-acceptance-${run_id}-${python_version}"
broker_dir="$(sudo mktemp -d -p /run "perseus-acceptance-${run_id}-${python_version}.XXXXXX")"
broker_socket="${broker_dir}/broker.sock"
broker_pid_file="${broker_dir}/broker.pid"
broker_log="${broker_dir}/broker.log"
script_repo_path="benchmark/disconnected_acceptance/cgroup_broker.py"
broker_script="${broker_dir}/cgroup_broker.py"
cleanup_failed=0

broker_process_matches() {
    local pid start_time current_start command
    read -r pid start_time <"${broker_pid_file}" || return 1
    [[ "${pid}" =~ ^[0-9]+$ && "${start_time}" =~ ^[0-9]+$ ]] || return 1
    sudo kill -0 "${pid}" 2>/dev/null || return 1
    current_start="$(sudo awk '{print $22}' "/proc/${pid}/stat" 2>/dev/null)" || return 1
    [[ "${current_start}" == "${start_time}" ]] || return 1
    command="$(sudo sh -c 'tr "\\0" " " <"$1"' sh "/proc/${pid}/cmdline" 2>/dev/null)" || return 1
    [[ "${command}" == *"cgroup_broker.py"* ]]
}

cleanup() {
    set +e
    if [ ! -f "${broker_pid_file}" ]; then
        cleanup_failed=1
    elif broker_process_matches; then
        read -r broker_pid _ <"${broker_pid_file}"
        sudo kill "${broker_pid}" 2>/dev/null || {
            sudo kill -0 "${broker_pid}" 2>/dev/null && cleanup_failed=1
        }
        stopped=0
        for _ in $(seq 1 20); do
            if ! sudo kill -0 "${broker_pid}" 2>/dev/null; then
                stopped=1
                break
            fi
            sleep 0.1
        done
        if [ "${stopped}" -ne 1 ]; then
            if broker_process_matches; then
                sudo kill -KILL "${broker_pid}" 2>/dev/null || cleanup_failed=1
            else
                cleanup_failed=1
            fi
            sudo kill -0 "${broker_pid}" 2>/dev/null && cleanup_failed=1
        fi
    else
        # A stale or mismatched identity is not safe to remove silently.
        cleanup_failed=1
    fi
    if [ -e "${broker_socket}" ]; then
        sudo rm -f "${broker_socket}" || cleanup_failed=1
    fi
    if [ "${cleanup_failed}" -ne 0 ]; then
        echo "privileged cgroup broker cleanup failed" >&2
        sudo cat "${broker_log}" >&2 2>/dev/null || true
    fi
    sudo rm -f "${broker_pid_file}" "${broker_log}" "${broker_script}" || cleanup_failed=1
    sudo rmdir "${broker_root}" 2>/dev/null || cleanup_failed=1
    sudo rmdir "${broker_dir}" 2>/dev/null || cleanup_failed=1
    if [ "${cleanup_failed}" -ne 0 ]; then
        echo "privileged cgroup broker cleanup failed" >&2
        return 1
    fi
    return 0
}

finish() {
    status=$?
    cleanup || status=1
    exit "${status}"
}
trap finish EXIT

commit_sha="$(git -C "${workspace}" rev-parse --verify HEAD^{commit})"
git -C "${workspace}" cat-file -e "${commit_sha}:${script_repo_path}"
expected_script_sha="$(git -C "${workspace}" cat-file blob "${commit_sha}:${script_repo_path}" | sha256sum | cut -d' ' -f1)"
git -C "${workspace}" cat-file blob "${commit_sha}:${script_repo_path}" | sudo tee "${broker_script}" >/dev/null
sudo chmod 0555 "${broker_script}"
actual_script_sha="$(sudo sha256sum "${broker_script}" | cut -d' ' -f1)"
if [ "${actual_script_sha}" != "${expected_script_sha}" ]; then
    echo "trusted broker materialization digest mismatch" >&2
    exit 1
fi

sudo mkdir -p "${broker_root}"
sudo chmod 0755 "${broker_dir}"
sudo bash -c '
    set -euo pipefail
    umask 0022
    pid_file="$1"
    log_file="$2"
    python_bin="$3"
    shift 3
    start_time="$(cut -d " " -f22 "/proc/$$/stat")"
    printf "%s %s\n" "$$" "${start_time}" >"${pid_file}"
    exec "${python_bin}" "$@" >"${log_file}" 2>&1
' -- "${broker_pid_file}" "${broker_log}" "${python_bin}" "${broker_script}" \
    --root "${broker_root}" --socket "${broker_socket}" --uid "$(id -u)" \
    &
for _ in $(seq 1 50); do
    if [ -S "${broker_socket}" ] && broker_process_matches; then
        break
    fi
    if [ -f "${broker_pid_file}" ] && read -r broker_pid broker_start_time <"${broker_pid_file}" \
        && ! sudo kill -0 "${broker_pid}" 2>/dev/null; then
        sudo cat "${broker_log}" >&2 || true
        exit 1
    fi
    sleep 0.1
done
if ! [ -S "${broker_socket}" ] || ! broker_process_matches; then
    sudo cat "${broker_log}" >&2 || true
    exit 1
fi

export PERSEUS_ALLOW_DANGEROUS=1
export PERSEUS_ACCEPTANCE_CGROUP_BROKER="${broker_socket}"
python -m pytest tests/test_disconnected_acceptance.py -q --durations=20 -m "privileged_acceptance or not privileged_acceptance"
