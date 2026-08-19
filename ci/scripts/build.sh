#!/bin/bash
set -e

echo "========== Build =========="

cd srsRAN_Project/build

CCACHE_DISABLE=1 cmake --build . --parallel "$(nproc)"
