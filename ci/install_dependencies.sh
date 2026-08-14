#!/bin/bash
set -e

echo "========================================="
echo "Installing srsRAN CI build dependencies"
echo "========================================="

apt-get update

apt-get install -y \
    build-essential \
    cmake \
    git \
    pkg-config \
    ccache \
    libmbedtls-dev \
    libyaml-cpp-dev \
    libsctp-dev \
    libfftw3-dev \
    libgtest-dev \
    libzmq3-dev

rm -rf /var/lib/apt/lists/*

echo
echo "========================================="
echo "Installation complete!"
echo "========================================="
