#!/usr/bin/env bash
set -x
set -e

export PBR_VERSION=`grep '^version *= *.*$' setup.cfg | cut -d'=' -f2 | tr -d '[:space:]'`
apt-get update
apt-get install -y gcc libssl-dev libssl1.*
pip install --no-cache-dir -e .
apt-get purge -y gcc libssl-dev
rm -r /var/lib/apt/lists /var/cache/apt/archives
mkdir -p /var/cache/apt/archives
mkdir -p /var/lib/apt/lists
