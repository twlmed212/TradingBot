#!/usr/bin/env bash
# Deploy (or update) the console, the announcement collector and the latest recorder/research files.
# Run from the repo root on the Mac:  bash deploy/deploy_console.sh
# Builds the web app locally, copies files over the Session Manager SSH tunnel (`ssh tradingbot`), installs
# Python deps into /opt/deskbot/venv, and (re)starts the systemd units. Never copies data or .env.
set -euo pipefail
cd "$(dirname "$0")/.."

(cd console/web && npm run build >/dev/null)
rsync -az --delete --exclude '.venv/' --exclude 'node_modules/' --exclude '__pycache__/' console/ tradingbot:deskbot-src/console/
rsync -az --exclude '__pycache__/' recorder research deploy tradingbot:deskbot-src/

ssh tradingbot 'bash -s' <<'REMOTE'
set -euo pipefail
sudo DEBIAN_FRONTEND=noninteractive apt-get -qq -y install python3-venv >/dev/null
[ -x /opt/deskbot/venv/bin/python ] || sudo python3 -m venv /opt/deskbot/venv
sudo /opt/deskbot/venv/bin/pip install -q --disable-pip-version-check -r deskbot-src/console/requirements.txt
sudo mkdir -p /opt/deskbot/console
sudo rsync -a --delete --exclude 'web/node_modules/' --exclude 'web/src/' deskbot-src/console/ /opt/deskbot/console/
sudo rsync -a deskbot-src/research/ /opt/deskbot/research/
sudo cp deskbot-src/recorder/*.py deskbot-src/recorder/*.json /opt/deskbot/recorder/
sudo mkdir -p /opt/deskbot/ops /opt/deskbot/backups
sudo cp deskbot-src/deploy/backup_sqlite.py /opt/deskbot/ops/
sudo chown -R deskbot:deskbot /opt/deskbot/console /opt/deskbot/research /opt/deskbot/recorder /opt/deskbot/ops /opt/deskbot/backups
sudo cp deskbot-src/deploy/deskbot-console.service deskbot-src/deploy/deskbot-announcements.service deskbot-src/deploy/deskbot-announcements.timer deskbot-src/deploy/deskbot-h9.service deskbot-src/deploy/deskbot-h9.timer deskbot-src/deploy/deskbot-backup.service deskbot-src/deploy/deskbot-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now deskbot-announcements.timer >/dev/null
sudo systemctl enable --now deskbot-h9.timer >/dev/null
sudo systemctl enable --now deskbot-backup.timer >/dev/null
sudo systemctl enable deskbot-console >/dev/null
sudo systemctl restart deskbot-console
for i in $(seq 1 20); do curl -sf http://127.0.0.1:8787/api/overview >/dev/null && break; sleep 1; done
echo "console: $(systemctl is-active deskbot-console)  timer: $(systemctl is-active deskbot-announcements.timer)  recorder: $(systemctl is-active deskbot-recorder)  h9: $(systemctl is-active deskbot-h9.timer)  backup: $(systemctl is-active deskbot-backup.timer)"
REMOTE
