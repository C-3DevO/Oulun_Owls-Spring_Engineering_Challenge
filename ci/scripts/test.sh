#!/bin/bash
set -e

echo "========================================"
echo "Running Scheduler Policy Unit Tests"
echo "========================================"

cd srsRAN_Project/build

set +e
OUTPUT=$(ctest -R "scheduler_policy/" --output-on-failure 2>&1)
STATUS=$?
set -e

echo "$OUTPUT"

TOTAL=$(echo "$OUTPUT" | grep -oP '\d+(?= tests)' | tail -1)
PASSED=$(echo "$OUTPUT" | grep -oP '\d+(?= tests passed)' | tail -1)

FAILED=$((TOTAL - PASSED))

if [ "$TOTAL" -eq 0 ]; then
    echo "ERROR: No tests were found."
    exit 1
fi

FAILURE_PERCENT=$((FAILED * 100 / TOTAL))

echo
echo "========================================"
echo "Test Summary"
echo "========================================"
echo "Total:   $TOTAL"
echo "Passed:  $PASSED"
echo "Failed:  $FAILED"
echo "Failure: ${FAILURE_PERCENT}%"

if [ "$FAILURE_PERCENT" -lt 10 ]; then
    echo "ACCEPTED: Failure rate is below 10%."
    exit 0
else
    echo "REJECTED: Failure rate is 10% or higher."
    exit 1
fi
