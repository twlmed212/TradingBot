# Recorder server (AWS)

Created 25 October 2026 in the AWS project (account ID: see `aws sts get-caller-identity --profile tradingbot`), Region **eu-north-1**, CLI profile `tradingbot`.

| Item | Value |
|---|---|
| Instance | `i-0c468a3d52d2e242f`, t4g.micro (2 vCPU Arm, 1 GiB + 2 GB swap), Ubuntu 24.04, eu-north-1a |
| Public IP | `13.53.89.50` (changes if the instance is stopped and started) |
| Disk | 20 GB gp3, encrypted, deleted with the instance |
| Access | **No inbound ports open** (security group `sg-006d5dbd589e49b44` has zero inbound rules). SSH runs through AWS Session Manager with the owner's SSH key, from any IP. Instance role `tradingbot-recorder-ssm` has only `AmazonSSMManagedInstanceCore` |
| Hardening | IMDSv2 required, CPU credits "standard" (no surplus charges), unattended security upgrades, recorder runs as locked-down user `deskbot` |
| Services | `deskbot-recorder` (quotes), `deskbot-console` (dashboard), `deskbot-announcements.timer` (listings), `deskbot-h9.timer` (H9 forward paper test, hourly; a failed run retries every 4 min), `deskbot-backup.timer` (daily SQLite copies); all restart on failure and at boot. Data in `/opt/deskbot/data/` |
| Cost | ≈ $12/month (instance $6.28, disk $1.67, public IPv4 $3.65, snapshots ≈ $0.25–0.50), paid from the Free-plan credit |
| Backups | Daily EBS snapshot of the disk at 03:30 UTC, 7 kept (Data Lifecycle Manager policy `policy-0d3112a07d8199860`, role `service-role/AWSDataLifecycleManagerDefaultRole`, both created 26 Oct 2026). Daily SQLite copies of `h9_paper` and `announcements` at 03:15 UTC in `/opt/deskbot/backups/`, 30 days kept. AWS instance auto-recovery is on (default) |

## Common tasks

`~/.ssh/config` on the Mac has a `tradingbot` host that tunnels SSH through Session Manager (needs the Session Manager plugin in `~/.local/bin` and a valid `aws login --profile tradingbot`). Your home IP no longer matters.

Connect:

```bash
ssh tradingbot
```

Check the recorder:

```bash
ssh tradingbot 'systemctl is-active deskbot-recorder; sudo sqlite3 /opt/deskbot/data/quotes.sqlite3 "select count(*), sum(recorded), sum(expected), max(started_at) from cycles"'
```

Deploy an updated recorder:

```bash
rsync -az recorder/ tradingbot:deskbot-src/recorder/ && ssh tradingbot 'sudo cp deskbot-src/recorder/* /opt/deskbot/recorder/ && sudo chown -R deskbot:deskbot /opt/deskbot/recorder && sudo systemctl restart deskbot-recorder'
```

Copy the data to the Mac:

```bash
scp tradingbot:/opt/deskbot/data/quotes.sqlite3 data/quotes-server.sqlite3
```

If `ssh tradingbot` fails with an expired-token or credentials error, the AWS login has expired (it lasts 12 hours and renews automatically for up to 90 days). Sign in again:

```bash
aws login --region eu-north-1 --profile tradingbot
```

## Console (watch-only dashboard)

Runs on the server as `deskbot-console` (FastAPI + React), bound to 127.0.0.1:8787, so it is never on the internet. Open it from the Mac:

```bash
ssh tradingbot-console
```

Leave that running, browse to http://localhost:8787, and press Ctrl-C to close the tunnel.

Deploy changes to the console, the listings collector, or the research files:

```bash
bash deploy/deploy_console.sh
```

The listings collector (`deskbot-announcements.timer`) runs every 10 minutes. Upbit's announcement site blocks AWS IPs, so on the server Upbit listings come from Upbit's official market list (new and removed markets, warning flags); its older notice history was copied from the Mac.

## Notes

- Jupiter's keyless API rate-limits bursts from this IP; the recorder pauses 1 s between requests (`--pause`), so a cycle takes about 30 s.
- The Mac recorder was stopped on 25 Oct 2026 at 18:15 UTC; its data stays in `data/quotes.sqlite3` on the Mac as an archive.
- The Free plan credit ($100) expires on 25 April 2027; the project must be upgraded to the paid plan before then to keep the server.

## H9 forward paper test

Hourly oneshot `deskbot-h9.service` (timer at :02) runs `research/h9_paper.py` against public Hyperliquid prices; state in `/opt/deskbot/data/h9_paper.sqlite3`. Check:

```bash
ssh tradingbot 'sudo -u deskbot python3 /opt/deskbot/research/h9_paper.py --status'
```

Or open the console (`ssh tradingbot-console`, then http://localhost:8787/#paper): the **H9 paper test** card shows equity against USDC 5%, the five pass criteria so far, positions and stop distances, P&L by token, weekly results and engine events. Its live prices come from Hyperliquid's public `allMids` (no key); the official figures are the hourly marks.

Verdict (any time for a provisional reading; final after 31 Jan 2027 23:10 UTC). The engine stops changing its state after 31 Jan 23:59 UTC:

```bash
ssh tradingbot 'cd /opt/deskbot && sudo -u deskbot python3 research/h9_verdict.py'
```

## Backups and restore

- **What exists:** a clean daily copy of `h9_paper.sqlite3` and `announcements.sqlite3` in `/opt/deskbot/backups/` (03:15 UTC, `deploy/backup_sqlite.py`), then a snapshot of the whole disk at 03:30 UTC (7 kept). `quotes.sqlite3` is only in the snapshots.
- **Restore a file on the same server** (for example a damaged H9 database): stop the timer, copy the backup over, start the timer, and disclose the restore in the H9 registry (any hours between the copy and the restore are lost runs).

```bash
ssh tradingbot 'sudo systemctl stop deskbot-h9.timer && sudo -u deskbot cp /opt/deskbot/backups/h9_paper-YYYY-MM-DD.sqlite3 /opt/deskbot/data/h9_paper.sqlite3 && sudo systemctl start deskbot-h9.timer'
```

- **If the server or disk is lost:** in the EC2 console, open Snapshots (tag `Project=tradingbot`), create a volume from the newest one in the same Availability Zone, attach it to a replacement instance, mount it, and copy `/opt/deskbot/data/` and `/opt/deskbot/backups/` across.
- **To remove the backups** (stops the snapshot cost): delete the DLM policy and its snapshots in the EC2 console (Lifecycle Manager, then Snapshots).
