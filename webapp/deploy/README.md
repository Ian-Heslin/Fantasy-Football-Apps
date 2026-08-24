# Running the web app persistently on your home network

This gets the site running all the time on whichever Mac stays on at home,
reachable by other devices on your network at a friendly `.local` hostname
-- no manual `uvicorn --reload` every time you want to look at it. It's the
same idea as `mailprep.seawayprinting.net` (a service that's just always
running on the network), scaled down to what a home Mac can do without any
router or DNS admin access: Bonjour/mDNS `.local` names instead of a real
domain, `launchd` instead of whatever's running mailprep.

## 1. Give your Mac a friendly local hostname

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

## 2. Install the launchd service

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

## Managing the service

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

## Moving to real public hosting later

The app is already stateless enough (reads two local database files, no
in-memory session state) that "move to the web" is mostly a hosting
decision, not a rewrite:

- **`webapp/Dockerfile`** (added alongside this doc) packages the app the
  same way it'd run on a home Mac or a cloud VM -- so testing "does this
  run the same way elsewhere" is just `docker build` + `docker run` now,
  before there's any pressure to actually move.
- A small VPS (Fly.io, Railway, a $5-6/mo DigitalOcean droplet) can run
  that same container and give you a real domain instead of a `.local`
  one.
- **Multi-user login for friends is a separate, not-yet-built piece** --
  right now every page just reads the databases with no concept of "whose
  data is this." Before opening this up to friends you'd want at minimum a
  `users` table and session-based login (e.g. FastAPI's
  `SessionMiddleware` + signed cookies, or an OAuth provider like Google
  sign-in) gating which Sleeper leagues/rosters a given login can see --
  worth its own design pass whenever you're ready to get there, since it
  touches every route that currently assumes "there's just one of me."
