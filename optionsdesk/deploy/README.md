# Running ATLAS 24/7 on a Hetzner server

Goal: the desk keeps trading the paper account whether your Mac is on, off, or
in your bag — with your existing trade history intact, and the dashboard
reachable only by you.

**Cost:** ~€3.79–4.51/month for the smallest Hetzner Cloud box. Nothing else.

You'll copy the *same* Docker app you already run onto a small always-on Linux
server, carry your ledger over so the account continues (not restarts), and
firewall the dashboard to your own IP.

Three things live OUTSIDE git and must be carried by hand (scripts below do it):
your `.env`, your real option chains in `data/chains/`, and the trade-history
Docker volume. A plain `git clone` on the server would miss all three.

---

## 1. Create the server (Hetzner Cloud console)

1. **Add Server** → Location: pick one near you (US East/West or Germany).
2. **Image:** Ubuntu 24.04. *(Optional shortcut: the "Docker CE" app image comes
   with Docker pre-installed — then you can skip step 3.)*
3. **Type:** Shared vCPU → **CAX11** (Arm, 2 vCPU / 4 GB, ~€3.79/mo). Plenty,
   since research is parked. (CX22/CPX11 x86 also fine, a euro more.)
4. **SSH key:** add your Mac's public key (`cat ~/.ssh/id_ed25519.pub` — if you
   don't have one, run `ssh-keygen -t ed25519` first, then re-check).
5. Create it. Note the server's **public IP** (e.g. `203.0.113.10`).

## 2. Lock it down BEFORE anything else (Hetzner Cloud Firewall)

The desk has **no login**, so the firewall is what keeps it private.

1. Console → **Firewalls** → Create Firewall.
2. Find your own IP: on the Mac run `curl -s ifconfig.me`.
3. Inbound rules — allow **only your IP** (`<YOUR_IP>/32`):
   - TCP **22** (SSH) from `<YOUR_IP>/32`
   - TCP **8080** (dashboard) from `<YOUR_IP>/32`
   - Leave everything else blocked.
4. Apply the firewall to your server.

> Home IP changed and you can't reach it later? Edit these rules to your new
> `curl ifconfig.me` value. (If your IP changes a lot, tell me and I'll set you
> up an SSH tunnel instead — no open port at all.)

## 3. Install Docker on the server (skip if you used the Docker CE image)

```
ssh root@<SERVER_IP>
```
Then copy `deploy/setup-server.sh` up and run it — or just paste its contents.
Easiest: do step 4's rsync first, then `bash ~/optionsdesk/deploy/setup-server.sh`.

## 4. Copy ATLAS + your data + your history to the server

All commands here run **on the Mac**, from the folder above optionsdesk.

**a) Copy the app, your `.env`, and your real chains** (excludes the heavy
build junk; keeps the folder named `optionsdesk` so volume names line up):

```
rsync -av --exclude 'frontend/node_modules' --exclude 'frontend/dist' \
  --exclude '.venv' --exclude 'atlas-state.tgz' \
  ~/peppypeptidezzz/optionsdesk/ root@<SERVER_IP>:/root/optionsdesk/
```

**b) Export your trade history and copy it up:**

```
cd ~/peppypeptidezzz/optionsdesk
bash deploy/backup-state.sh                       # writes atlas-state.tgz
scp atlas-state.tgz root@<SERVER_IP>:/root/optionsdesk/
```

**c) Fix one path in the server's `.env`.** `MERIDIAN_DATA` points at a Mac-only
folder. On the server:

```
ssh root@<SERVER_IP>
cd ~/optionsdesk
sed -i 's#^MERIDIAN_DATA=.*#MERIDIAN_DATA=./data/raw#' .env
grep -E 'AUTO_RESEARCH=|MERIDIAN_DATA=' .env        # AUTO_RESEARCH=0 should be here
```
If `AUTO_RESEARCH=0` isn't listed, add it: `echo "AUTO_RESEARCH=0" >> .env`.

## 5. Restore the history and launch (on the server)

```
cd ~/optionsdesk
bash deploy/restore-state.sh          # loads your ledger into the volume
docker compose up -d --build          # first build takes a few minutes
```

## 6. Check it

```
curl -s localhost:8080/api/auto/research | grep -o '"research_enabled":[a-z]*'   # -> false (parked)
curl -s localhost:8080/api/paper/positions | head -c 400                          # your book
```
Then open **http://<SERVER_IP>:8080** in Safari — you should see your desk with
the same equity, the same closed-trade count, and PARKED research.

## 7. Stop the Mac copy (important)

Two desks running the same strategies on the same API key would double your
Alpha Vantage usage and split your history across two ledgers. Once the server
looks right, retire the Mac one:

```
cd ~/peppypeptidezzz/optionsdesk
docker compose down
```

From now on the server is the single source of truth. The Mac can sleep.

---

## Updating later (when I push a fix)

Two options:
- **Simple:** re-run the step-4a `rsync`, then on the server
  `docker compose up -d --build`.
- **Cleaner (`git pull` on the server):** create a GitHub *fine-grained,
  read-only* token for this repo, then on the server
  `git remote set-url origin https://<TOKEN>@github.com/jywy78kgrf-create/peppypeptidezzz.git`
  and thereafter `git pull && docker compose up -d --build`. Ask me and I'll
  walk you through the token.

## Backups (recommended)

Your history now lives only on the server. Snapshot it now and then:

```
cd ~/optionsdesk && bash deploy/backup-state.sh   # writes atlas-state.tgz
```
Copy that file somewhere safe (or `scp` it back to the Mac). Hetzner also
offers automated server snapshots/backups in the console for a small % of the
server cost — worth enabling.

## If something looks wrong

- Dashboard won't load → firewall rule doesn't match your current IP
  (`curl ifconfig.me`), or the stack is still building (`docker compose ps`).
- Equity shows $100k / no trades → the state restore didn't run before
  `up`; `docker compose down`, re-run `restore-state.sh`, `up` again.
- Anything else → grab `docker compose logs backend | tail -50` and send it to me.
