#!/bin/bash
set -e

echo "========== Configure =========="

cd srsRAN_Project

rm -rf build
mkdir -p build
cd build

cmake .. -DENABLE_UHD=OFF
