#!/usr/bin/env bash
set -euo pipefail

workspace="${GITHUB_WORKSPACE:-$(pwd)}"
run_id="${GITHUB_RUN_ID:-local-$$}"
python_version="${PYTHON_VERSION:-$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')}"
broker_root="/sys/fs/cgroup/perseus-acceptance-${run_id}-${python_version}"
broker_dir="/run/perseus-acceptance-${run_id}-${python_version}"
broker_socket="${broker_dir}/broker.sock"
broker_pid_file="/tmp/perseus-acceptance-broker-${run_id}-${python_version}.pid"
broker_log="/tmp/perseus-acceptance-broker-${run_id}-${python_version}.log"
broker_script="${workspace}/benchmark/disconnected_acceptance/cgroup_broker.py"
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
    if [ -f "${broker_pid_file}" ] && broker_process_matches; then
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
    elif [ -f "${broker_pid_file}" ]; then
        # A stale or mismatched identity is not safe to remove silently.
        cleanup_failed=1
    fi
    if [ -e "${broker_socket}" ]; then
        sudo rm -f "${broker_socket}" || cleanup_failed=1
    fi
    sudo rmdir "${broker_root}" 2>/dev/null || true
    sudo rmdir "${broker_dir}" 2>/dev/null || true
    sudo rm -f "${broker_pid_file}" "${broker_log}" || cleanup_failed=1
    if [ "${cleanup_failed}" -ne 0 ]; then
        echo "privileged cgroup broker cleanup failed" >&2
        sudo cat "${broker_log}" >&2 2>/dev/null || true
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

if [ ! -f "${broker_script}" ]; then
    echo "trusted cgroup broker script is missing: ${broker_script}" >&2
    exit 1
fi
sudo mkdir -p "${broker_root}" "${broker_dir}"
sudo chmod 0755 "${broker_dir}"
sudo rm -f "${broker_pid_file}"
python_bin="$(command -v python)"
sudo bash -c '
    set -euo pipefail
    umask 0022
    pid_file="$1"
    python_bin="$2"
    shift 2
    start_time="$(awk "{print \\$22}" "/proc/$$/stat")"
    printf "%s %s\\n" "$$" "${start_time}" >"${pid_file}"
    exec "${python_bin}" "$@"
' -- "${broker_pid_file}" "${python_bin}" "${broker_script}" \
    --root "${broker_root}" --socket "${broker_socket}" --uid "$(id -u)" \
    >"${broker_log}" 2>&1 &
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
python -m pytest tests/test_disconnected_acceptance.py -q --durations=20
