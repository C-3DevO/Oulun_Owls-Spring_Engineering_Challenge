#!/bin/bash
set -e

echo "========== Build =========="

cd srsRAN_Project/build

cmake --build . --parallel "$(nproc)"
