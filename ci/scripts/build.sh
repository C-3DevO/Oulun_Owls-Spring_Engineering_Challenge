#!/bin/bash
set -e

echo "========== Build =========="

cd srsRAN_Project/build

make -j"$(nproc)"
