#!/usr/bin/env bash
set -euxo pipefail

apt-get update
apt-get install -y git
pip install --only-binary=scrypt --no-cache-dir -e .

# "Fake" a pbr.json to keep our changelog happy
[ -f vcenter_operator.egg-info/pbr.json ] || (
  cat >vcenter_operator.egg-info/pbr.json <<EOT
{"git_version": "$(git rev-parse --short HEAD)", "is_release": false}
EOT
)

apt-get purge --autoremove -y git
rm -r /var/lib/apt/lists /var/cache/apt/archives
mkdir -p /var/cache/apt/archives /var/lib/apt/lists
