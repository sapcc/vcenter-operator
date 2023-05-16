#!/usr/bin/env bash
set -euxo pipefail

apt-get update
apt-get install -y gcc libssl-dev libssl1.* git
pip install --no-cache-dir -e .

# "Fake" a pbr.json to keep our changelog happy
[ -f vcenter_operator.egg-info/pbr.json ] || (
  cat >vcenter_operator.egg-info/pbr.json <<EOT
{"git_version": "$(git rev-parse --short HEAD)", "is_release": false}
EOT
)

apt-get purge --autoremove -y gcc libssl-dev
rm -r /var/lib/apt/lists /var/cache/apt/archives
mkdir -p /var/cache/apt/archives /var/lib/apt/lists
