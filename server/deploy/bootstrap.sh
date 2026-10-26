#!/usr/bin/env bash
# One-time server setup for an Ubuntu 24.04 VM. Run as the admin user from a copy of server/: sudo bash deploy/bootstrap.sh
# Installs updates, a 2 GB swap file (the free VM has 1 GiB RAM), a firewall that only allows SSH,
# a dedicated non-login "deskbot" user, and the recorder as an auto-restarting systemd service.
set -euo pipefail

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y upgrade
DEBIAN_FRONTEND=noninteractive apt-get -y install python3 sqlite3 rsync unattended-upgrades ufw
dpkg-reconfigure -f noninteractive unattended-upgrades

if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

ufw allow OpenSSH
ufw --force enable

id deskbot >/dev/null 2>&1 || useradd --system --home /opt/deskbot --shell /usr/sbin/nologin deskbot
mkdir -p /opt/deskbot/data
cp -r "$(dirname "$0")/.."/{recorder,research} /opt/deskbot/
chown -R deskbot:deskbot /opt/deskbot

cp "$(dirname "$0")/deskbot-recorder.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now deskbot-recorder
sleep 70
systemctl --no-pager status deskbot-recorder | head -5
sqlite3 /opt/deskbot/data/quotes.sqlite3 "select count(*), sum(recorded), sum(expected) from cycles"
