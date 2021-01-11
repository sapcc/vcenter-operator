#!/usr/bin/env bash
set -x
set -e

apt-get update
apt-get install -y gcc libssl-dev libssl1.* git
pip install --no-cache-dir -e .
apt-get purge -y gcc libssl-dev
rm -r /var/lib/apt/lists /var/cache/apt/archives
mkdir -p /var/cache/apt/archives
mkdir -p /var/lib/apt/lists
