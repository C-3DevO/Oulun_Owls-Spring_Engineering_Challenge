#!/bin/bash
set -e

# ROOT Directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

PROJECT_DIR="srsRAN_Project"
BUILD_DIR="${PROJECT_DIR}/build"
CONFIG_DIR="${PROJECT_DIR}/configs"


run_scheduler()
{
    NAME=$1
    CONFIG=$2

    echo "========================================"
    echo "Running ${NAME} scheduler..."
    echo "========================================"

    LOG_FILE="${NAME}.log"

    # Remove previous log if it exists
    rm -f "${LOG_FILE}"

    # Allow timeout to return 124 without terminating the script
    set +e

    timeout 20s \
        "${BUILD_DIR}/apps/gnb/gnb" \
        -c "${CONFIG_DIR}/gnb_custom_cell_2.yml" \
        -c "${CONFIG_DIR}/testmode.yml" \
        -c "${CONFIG_DIR}/${CONFIG}" \
        > "${LOG_FILE}" 2>&1

    STATUS=$?

    set -e

    # Exit code 124 means timeout expired (expected)
    if [ "${STATUS}" -eq 124 ]; then
        echo "${NAME} scheduler ran successfully for 20 seconds."
    elif [ "${STATUS}" -ne 0 ]; then
        echo "ERROR: ${NAME} scheduler crashed (exit code ${STATUS})"
        cat "${LOG_FILE}"
        exit 1
    fi

    # Verify that the gNB actually started
    if ! grep -q "Starting DU" "${LOG_FILE}"; then
        echo "ERROR: ${NAME} scheduler did not start correctly."
        cat "${LOG_FILE}"
        exit 1
    fi

    echo "${NAME} scheduler passed."
    echo
}

run_scheduler "RR" "rr_scheduler.yml"
run_scheduler "AI" "ai_scheduler.yml"

echo "========================================"
echo "All scheduler integration tests passed."
echo "========================================"
