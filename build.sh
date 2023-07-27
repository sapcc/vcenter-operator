#!/usr/bin/env bash
set -euxo pipefail

rm -f /etc/apt/apt.conf.d/docker-clean
echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

apt-get update
apt-get upgrade
apt-get install -y git

pip install --only-binary=scrypt --disable-pip-version-check -e .

# "Fake" a pbr.json to keep our changelog happy
[ -f vcenter_operator.egg-info/pbr.json ] || (
  cat >vcenter_operator.egg-info/pbr.json <<EOT
{"git_version": "$(git rev-parse --short HEAD)", "is_release": false}
EOT
)

apt-get purge --autoremove -y git
