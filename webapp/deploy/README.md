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

Fill in your actual repo path, python3 path, and a stable session secret
(without one, everyone gets logged out of the site every time this
restarts):

```bash
REPO_PATH="$(cd .. && cd .. && pwd)"
PYTHON_PATH="$(which python3)"
SESSION_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
```

Generate the filled-in service file and install it:

```bash
sed -e "s|__REPO_PATH__|$REPO_PATH|g" -e "s|__PYTHON_PATH__|$PYTHON_PATH|g" -e "s|__SESSION_SECRET_KEY__|$SESSION_SECRET_KEY|g" com.ianheslin.fantasyfootball.plist > /tmp/com.ianheslin.fantasyfootball.plist
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

Generate a stable session secret -- without one, everyone gets logged out
of the site every time this service restarts:

```bash
SESSION_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
```

`sudo` only covers `sed` itself, not the `>` redirect (your normal shell
sets that up before `sudo` runs) -- write to a temp file first, then move
it into place with `sudo`:

```bash
sed -e "s|__REPO_PATH__|/opt/fantasy-football-apps/repo|g" -e "s|__VENV_PATH__|/opt/fantasy-football-apps/venv|g" -e "s|__SERVICE_USER__|fantasyapp|g" -e "s|__SESSION_SECRET_KEY__|$SESSION_SECRET_KEY|g" fantasyfootball.service > /tmp/fantasyfootball.service
```
```bash
sudo mv /tmp/fantasyfootball.service /etc/systemd/system/fantasyfootball.service
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

Confirm the app answers, from **on the Pi itself**:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/login   # expect 200
```

Do this before moving to the tunnel step -- easier to debug the app
itself before adding Cloudflare into the mix.

> **The app binds loopback only.** `fantasyfootball.service` starts
> uvicorn on `127.0.0.1:8000`, not `0.0.0.0:8000`, so
> `http://homebridge.local:8000` from a laptop on the same WiFi will
> **not** answer -- that's intended. cloudflared runs on the Pi and
> reaches the app over localhost (see `cloudflared-config.yml`), so
> nothing needs the port exposed to the LAN, and the tunnel hostname is
> the one way in.
>
> If you set this Pi up before this change, re-run the `sed` above and
> `sudo systemctl daemon-reload && sudo systemctl restart
> fantasyfootball.service` to pick up the new unit -- including the
> `--proxy-headers` flags, which are what make real client IPs visible
> instead of every request looking like it came from 127.0.0.1.

### 6. Install cloudflared and run a quick tunnel

```bash
curl -L --output /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
```
```bash
sudo dpkg -i /tmp/cloudflared.deb
```

Install the tunnel as a systemd service (this is the "quick tunnel" mode --
no Cloudflare account needed yet):

Same redirect gotcha as step 5 -- write to `/tmp` first, then `sudo mv`:

```bash
sed -e "s|__REPO_PATH__|/opt/fantasy-football-apps/repo|g" cloudflared-quicktunnel.service > /tmp/cloudflared-quicktunnel.service
```
```bash
sudo mv /tmp/cloudflared-quicktunnel.service /etc/systemd/system/cloudflared-quicktunnel.service
```
```bash
sudo systemctl daemon-reload
```
```bash
sudo systemctl enable --now cloudflared-quicktunnel.service
```

Find your public URL (it takes a few seconds to appear after starting).
If the tunnel has ever restarted before, the log has multiple old (now
dead) URLs in it -- grab the last one, not just any match:

```bash
grep trycloudflare /opt/fantasy-football-apps/repo/webapp/deploy/cloudflared.log | tail -1
```

That `https://<random-words>.trycloudflare.com` URL works from anywhere --
send it to a friend on a different network to confirm. Remember: it
changes if this service restarts (Pi reboot, `cloudflared` crash, etc.) --
re-run the command above to find the new one. This is why it's a testing
step, not the final link.

**If you click the link and get Cloudflare's Error 1033**, that means
`cloudflared` itself isn't currently connected -- check
`sudo systemctl status cloudflared-quicktunnel.service`. If it's stuck in
`activating (auto-restart)`, check
`tail -50 /opt/fantasy-football-apps/repo/webapp/deploy/cloudflared.log`
for a `429 Too Many Requests` error: requesting a quick tunnel hits a
rate-limited, account-less Cloudflare endpoint, so restarting too fast
after a failure just keeps it rate-limited (confirmed this happens, not
just a theoretical risk -- the systemd unit here waits 60s between
restarts and gives up after 3 failures in 10 minutes specifically because
of this). If you're already stuck in that loop, stop it and let the rate
limit clear before trying again:

```bash
sudo systemctl stop cloudflared-quicktunnel.service
```

Wait a few minutes, then start it again:

```bash
sudo systemctl start cloudflared-quicktunnel.service
```

### Managing the Pi services

Restart the app (after a `git pull` or new database files):

```bash
sudo systemctl restart fantasyfootball.service
```

Then check the tunnel is still up -- `curl -sS -o /dev/null -w '%{http_code}\n'
https://solarisfantasyfootball.com/login` should give 200, not a Cloudflare
error page:

```bash
systemctl is-active cloudflared-tunnel.service    # expect: active
```

Both cloudflared units used to declare `Requires=fantasyfootball.service`,
which propagates *stops*: restarting the app stopped the tunnel with it and
did not bring it back, so the site served Cloudflare **error 1033** until
someone restarted the tunnel by hand. They now use `Wants=` instead, so an
app restart leaves the tunnel alone. If you're on a Pi set up before that
change, reinstall the tunnel unit (below) or the old behaviour persists in
`/etc/systemd/system/`. Either way, if the site is down after a restart:

```bash
sudo systemctl restart cloudflared-tunnel.service
```

Restart the tunnel (gets you a fresh quick-tunnel URL):

```bash
sudo systemctl restart cloudflared-quicktunnel.service
```

Live app logs:

```bash
sudo journalctl -u fantasyfootball.service -f
```

Live tunnel logs -- `journalctl` only shows systemd's own start/restart
bookkeeping for this one, not cloudflared's actual output (it's redirected
to a file instead, per the service definition), so tail that file directly:

```bash
tail -f /opt/fantasy-football-apps/repo/webapp/deploy/cloudflared.log
```

### Moving to a permanent domain

A **named tunnel** authenticates as your own Cloudflare account instead of
hitting the quick tunnel's account-less, rate-limited endpoint -- fixes
the instability quick tunnels have by design, and gives you a hostname
that stays fixed across every restart instead of a new random one each
time.

#### 1. Add your domain to Cloudflare

In the Cloudflare dashboard: **Add a Site** -> enter your domain -> Free
plan. Cloudflare shows two nameservers -- set those at your domain
registrar (wherever you bought the domain), replacing whatever's there
now. This can take minutes to hours to go **Active**; Cloudflare emails
you when it's done.

#### 2. Authenticate cloudflared to your account

On the Pi (as root, so the systemd service below can read the resulting
files -- it runs as root, no `User=` set):

```bash
sudo cloudflared tunnel login
```

This prints a URL -- open it on **any device** with a browser (your phone,
your Mac), log into Cloudflare, and select your domain. The Pi's `cloudflared`
polls in the background and downloads a certificate once you've authorized it.

#### 3. Create the tunnel and route your domain to it

```bash
sudo cloudflared tunnel create fantasyfootball
```

Note the **Tunnel ID** (a UUID) it prints, and that it wrote a credentials
file to `/root/.cloudflared/<TUNNEL_ID>.json`.

```bash
sudo cloudflared tunnel route dns fantasyfootball solarisfantasyfootball.com
```

That creates the DNS record on Cloudflare automatically -- no manual DNS
dashboard step needed. (Swap in a subdomain like `app.solarisfantasyfootball.com`
here instead, if you'd rather keep the bare domain free for something else later.)

#### 4. Configure and install the named-tunnel service

```bash
cd /opt/fantasy-football-apps/repo/webapp/deploy
```

Fill in the config (replace `TUNNEL_ID_HERE` with the UUID from step 3):

```bash
sudo mkdir -p /etc/cloudflared
```
```bash
sed -e "s|__TUNNEL_ID__|TUNNEL_ID_HERE|g" -e "s|__CREDENTIALS_PATH__|/root/.cloudflared/TUNNEL_ID_HERE.json|g" -e "s|__HOSTNAME__|solarisfantasyfootball.com|g" cloudflared-config.yml > /tmp/config.yml
```
```bash
sudo mv /tmp/config.yml /etc/cloudflared/config.yml
```

Install the new service:

```bash
sed -e "s|__REPO_PATH__|/opt/fantasy-football-apps/repo|g" cloudflared-tunnel.service > /tmp/cloudflared-tunnel.service
```
```bash
sudo mv /tmp/cloudflared-tunnel.service /etc/systemd/system/cloudflared-tunnel.service
```

Retire the quick tunnel and switch to the named one:

```bash
sudo systemctl disable --now cloudflared-quicktunnel.service
```
```bash
sudo systemctl daemon-reload
```
```bash
sudo systemctl enable --now cloudflared-tunnel.service
```

Check it's up:

```bash
sudo systemctl status cloudflared-tunnel.service
```
```bash
tail -20 cloudflared.log
```

Then just visit `https://solarisfantasyfootball.com` (or whatever
hostname you routed) -- that link now works forever, no more grepping
logs for a random URL after every restart.

## Backups

`app.db` holds live, continuously-written data with no other source of
truth -- accounts, Pick'em picks/settings, roster links -- so it needs its
own backup story independent of git and independent of restarting or
updating the app. **Restarting the service, or `git pull`-ing a code
update, never touches `app.db` at all** -- it's just a file on disk that
the running app happens to read/write; neither of those operations goes
anywhere near it. The real risk was `app.db` having been a *git-tracked*
file: if a future commit ever changed its tracked content, the next
`git pull` on a machine with real accumulated data would have either
hard-failed (blocking every future pull) or, worse, silently overwritten
the live file -- confirmed both failure modes in a throwaway test before
fixing this, not just a theoretical worry.

### One-time migration (only needed once, if `app.db` still shows as tracked)

Check first -- if this prints nothing, you're already on the fixed setup
and can skip to "Install the backup timer" below:

```bash
git -C /opt/fantasy-football-apps/repo ls-files fantasy-football-db/data/app.db
```

If it printed a path, untrack it locally *before* pulling (pulling first
would fail -- git won't silently discard a locally-modified tracked file):

```bash
cd /opt/fantasy-football-apps/repo
```
```bash
sudo -u fantasyapp git rm --cached fantasy-football-db/data/app.db
```
```bash
sudo -u fantasyapp git commit -m "stop tracking app.db locally"
```
```bash
sudo -u fantasyapp git pull --no-rebase
```

That's safe -- `git rm --cached` only removes it from git's index, never
touches the actual file, and the `--no-rebase` merge just reconciles your
local "stop tracking it" commit with the same change already made
upstream. `app.db` keeps every row it already has.

### Install the backup timer

Makes an hourly copy of `app.db` into `fantasy-football-db/data/backups/`
(via SQLite's online backup API, not a plain file copy -- safe to run
against a live, in-use database) and prunes anything older than 30 days.

```bash
cd /opt/fantasy-football-apps/repo/webapp/deploy
```
```bash
sed -e "s|__REPO_PATH__|/opt/fantasy-football-apps/repo|g" -e "s|__VENV_PATH__|/opt/fantasy-football-apps/venv|g" -e "s|__SERVICE_USER__|fantasyapp|g" app-db-backup.service > /tmp/app-db-backup.service
```
```bash
sudo mv /tmp/app-db-backup.service /etc/systemd/system/app-db-backup.service
```
```bash
sudo cp app-db-backup.timer /etc/systemd/system/app-db-backup.timer
```
```bash
sudo systemctl daemon-reload
```
```bash
sudo systemctl enable --now app-db-backup.timer
```

Check it's scheduled, and trigger one manually to confirm it works right
away rather than waiting an hour:

```bash
systemctl list-timers app-db-backup.timer
```
```bash
sudo systemctl start app-db-backup.service
```
```bash
ls -la /opt/fantasy-football-apps/repo/fantasy-football-db/data/backups/
```

**This still only protects you against a bad deploy, a mistaken delete,
or the app corrupting its own data** -- all real risks, but not against
the SD card itself failing, which is a well-known way Raspberry Pis lose
data. These backups live on the same card. If you want protection against
that too, the backups should periodically go somewhere else (rsync'd to
your Mac, a cloud storage bucket, etc.) -- say so and I'll set that up as
a follow-up; it needs its own piece of infrastructure (a way for the Pi
to authenticate to wherever the backups end up).

## Multi-user login (still not built)

Right now every page just reads the databases with no concept of "whose
data is this" -- fine for you alone, not fine once friends have their own
logins. Before that, you'd want at minimum a `users` table and
session-based login (e.g. FastAPI's `SessionMiddleware` + signed cookies,
or an OAuth provider like Google sign-in) gating which Sleeper/ESPN
leagues and rosters a given login can see -- worth its own design pass
whenever you're ready to get there, since it touches every route that
currently assumes "there's just one of me."
