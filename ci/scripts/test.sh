#!/bin/bash
set -e

echo "========================================"
echo "Running Scheduler Policy Unit Tests"
echo "========================================"

cd srsRAN_Project/build

ctest \
    -R "scheduler_policy/" \
    --output-on-failure

echo
echo "Scheduler policy unit tests passed."
