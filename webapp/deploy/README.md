# Running the web app persistently

Two setups are documented here:

- **macOS (launchd)** -- keeps the site running on a Mac that's left on,
  reachable on your home WiFi only (a `.local` hostname). This was the
  first version of this and still works, but doesn't reach anyone outside
  your house.
- **Raspberry Pi (systemd + Cloudflare Tunnel)** -- the current setup:
  runs on a Pi that stays on 24/7, and a Cloudflare Tunnel gives friends a
  real `https://` URL that works from anywhere, with no router
  port-forwarding and no open ports on your home network.

## macOS (launchd)

This gets the site running all the time on whichever Mac stays on at home,
reachable by other devices on your network at a friendly `.local` hostname
-- no manual `uvicorn --reload` every time you want to look at it. It's the
same idea as `mailprep.seawayprinting.net` (a service that's just always
running on the network), scaled down to what a home Mac can do without any
router or DNS admin access: Bonjour/mDNS `.local` names instead of a real
domain, `launchd` instead of whatever's running mailprep.

### 1. Give your Mac a friendly local hostname

macOS already advertises itself on the local network via Bonjour at
`<computer-name>.local`. Check/set yours:

See the current one:

```bash
scutil --get LocalHostName
```

Rename it:

```bash
sudo scutil --set LocalHostName fantasyfootball
```

(Same setting as System Settings -> General -> Sharing -> Local hostname.)
After that, anyone on your home WiFi can reach the Mac at
`fantasyfootball.local` -- no router configuration needed, because Bonjour
handles the name resolution automatically. This is the practical ceiling
without admin access to your router's DNS; if you *do* have that access,
you could instead add a static DNS entry there for something shorter, but
`.local` is simpler and works today.

### 2. Install the launchd service

From inside your existing clone of this repo:

```bash
cd webapp/deploy
```

Fill in your actual repo path and python3 path:

```bash
REPO_PATH="$(cd .. && cd .. && pwd)"
PYTHON_PATH="$(which python3)"
```

Generate the filled-in service file and install it:

```bash
sed -e "s|__REPO_PATH__|$REPO_PATH|g" -e "s|__PYTHON_PATH__|$PYTHON_PATH|g" com.ianheslin.fantasyfootball.plist > /tmp/com.ianheslin.fantasyfootball.plist
cp /tmp/com.ianheslin.fantasyfootball.plist ~/Library/LaunchAgents/
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.ianheslin.fantasyfootball.plist
```

That's it -- the site is now running, will keep running if it crashes, and
will start automatically next time you log in. Open it from any device on
your home WiFi at:

```
http://fantasyfootball.local:8000
```

(swap in whatever local hostname you picked in step 1).

### Managing the service

Stop it:

```bash
launchctl unload ~/Library/LaunchAgents/com.ianheslin.fantasyfootball.plist
```

Start it again:

```bash
launchctl load ~/Library/LaunchAgents/com.ianheslin.fantasyfootball.plist
```

Check it's running:

```bash
launchctl list | grep fantasyfootball
```

See logs:

```bash
tail -f webapp/deploy/webapp.log webapp/deploy/webapp.error.log
```

After you `git pull` new changes or re-run `build_db.py`, restart the
service (`unload` then `load`) to pick them up -- it does not auto-reload
like `uvicorn --reload` does.

## Raspberry Pi (systemd + Cloudflare Tunnel)

This is the setup that actually reaches friends from anywhere, not just
your home WiFi. Two services run on the Pi: the web app itself (via
systemd, the Linux equivalent of launchd above), and `cloudflared`, which
opens an outbound-only connection to Cloudflare so it can hand out a real
public `https://` URL -- no router port-forwarding, no open ports on your
home network, your home IP address stays hidden.

Since `analytics.duckdb` is gitignored (regenerated, never committed) and
the git-committed `app.db` likely doesn't have the real Sleeper/ESPN roster
data you've loaded locally, the fastest correct path is copying both
database files from wherever you've been running this (e.g. your Mac)
straight to the Pi, rather than rebuilding everything from nflverse/Sleeper/
ESPN from scratch on the Pi's SD card.

### 1. Install packages and create a dedicated user

SSH into the Pi, then install what's needed (Debian's Python blocks a bare
`pip install` outside a virtual environment, so this includes
`python3-venv`):

```bash
sudo apt update
```
```bash
sudo apt install -y git python3-venv python3-pip
```

Run the app under its own system account rather than the `homebridge` user
-- keeps it isolated from Homebridge's own files/permissions:

```bash
sudo useradd --system --create-home --home-dir /opt/fantasy-football-apps --shell /usr/sbin/nologin fantasyapp
```

### 2. Clone the repo

```bash
sudo -u fantasyapp git clone https://github.com/Ian-Heslin/Fantasy-Football-Apps.git /opt/fantasy-football-apps/repo
```
```bash
sudo -u fantasyapp git -C /opt/fantasy-football-apps/repo checkout claude/hello-world-doc-lq2m27
```

### 3. Create the virtual environment and install dependencies

```bash
sudo -u fantasyapp python3 -m venv /opt/fantasy-football-apps/venv
```
```bash
sudo -u fantasyapp /opt/fantasy-football-apps/venv/bin/pip install -r /opt/fantasy-football-apps/repo/fantasy-football-db/scripts/requirements.txt
```
```bash
sudo -u fantasyapp /opt/fantasy-football-apps/venv/bin/pip install -r /opt/fantasy-football-apps/repo/webapp/requirements.txt
```

### 4. Copy your real databases over from your Mac

From your **Mac** (not the Pi), with the Pi's hostname or IP address:

```bash
scp fantasy-football-db/data/app.db homebridge@homebridge.local:/tmp/app.db
```
```bash
scp fantasy-football-db/data/analytics.duckdb homebridge@homebridge.local:/tmp/analytics.duckdb
```

Back on the **Pi**, move them into place and hand them to the `fantasyapp`
user:

```bash
sudo mv /tmp/app.db /tmp/analytics.duckdb /opt/fantasy-football-apps/repo/fantasy-football-db/data/
```
```bash
sudo chown fantasyapp:fantasyapp /opt/fantasy-football-apps/repo/fantasy-football-db/data/app.db /opt/fantasy-football-apps/repo/fantasy-football-db/data/analytics.duckdb
```

### 5. Install the app's systemd service

```bash
cd /opt/fantasy-football-apps/repo/webapp/deploy
```
```bash
sudo sed -e "s|__REPO_PATH__|/opt/fantasy-football-apps/repo|g" -e "s|__VENV_PATH__|/opt/fantasy-football-apps/venv|g" -e "s|__SERVICE_USER__|fantasyapp|g" fantasyfootball.service > /etc/systemd/system/fantasyfootball.service
```
```bash
sudo systemctl daemon-reload
```
```bash
sudo systemctl enable --now fantasyfootball.service
```

Check it's running:

```bash
sudo systemctl status fantasyfootball.service
```

From any device on your home WiFi: `http://homebridge.local:8000` should
now show the site. Confirm that works before moving to the tunnel step --
easier to debug the app itself before adding Cloudflare into the mix.

### 6. Install cloudflared and run a quick tunnel

```bash
curl -L --output /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
```
```bash
sudo dpkg -i /tmp/cloudflared.deb
```

Install the tunnel as a systemd service (this is the "quick tunnel" mode --
no Cloudflare account needed yet):

```bash
sudo sed -e "s|__REPO_PATH__|/opt/fantasy-football-apps/repo|g" cloudflared-quicktunnel.service > /etc/systemd/system/cloudflared-quicktunnel.service
```
```bash
sudo systemctl daemon-reload
```
```bash
sudo systemctl enable --now cloudflared-quicktunnel.service
```

Find your public URL (it takes a few seconds to appear after starting):

```bash
grep trycloudflare /opt/fantasy-football-apps/repo/webapp/deploy/cloudflared.log
```

That `https://<random-words>.trycloudflare.com` URL works from anywhere --
send it to a friend on a different network to confirm. Remember: it
changes if this service restarts (Pi reboot, `cloudflared` crash, etc.) --
re-run the `grep` above to find the new one. This is why it's a testing
step, not the final link.

### Managing the Pi services

Restart the app (after a `git pull` or new database files):

```bash
sudo systemctl restart fantasyfootball.service
```

Restart the tunnel (gets you a fresh quick-tunnel URL):

```bash
sudo systemctl restart cloudflared-quicktunnel.service
```

Live app logs:

```bash
sudo journalctl -u fantasyfootball.service -f
```

Live tunnel logs:

```bash
sudo journalctl -u cloudflared-quicktunnel.service -f
```

### Moving to a permanent domain later

Once you own a domain, switch from a quick tunnel to a **named tunnel**:
`cloudflared tunnel login`, `cloudflared tunnel create fantasyfootball`,
then `cloudflared tunnel route dns fantasyfootball fantasy.yourdomain.com`
-- that hostname stays fixed across restarts, unlike the quick tunnel's
random one. Ask when you're ready to add your domain to Cloudflare (free)
and I'll walk through the named-tunnel config swap.

## Multi-user login (still not built)

Right now every page just reads the databases with no concept of "whose
data is this" -- fine for you alone, not fine once friends have their own
logins. Before that, you'd want at minimum a `users` table and
session-based login (e.g. FastAPI's `SessionMiddleware` + signed cookies,
or an OAuth provider like Google sign-in) gating which Sleeper/ESPN
leagues and rosters a given login can see -- worth its own design pass
whenever you're ready to get there, since it touches every route that
currently assumes "there's just one of me."
