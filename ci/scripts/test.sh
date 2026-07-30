#!/bin/bash
set -e

echo "========== Test =========="

cd srsRAN_Project/build

ctest --output-on-failure
