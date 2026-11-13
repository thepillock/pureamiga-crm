# Pure Amiga repairs CRM

[![CI](https://github.com/thepillock/pureamiga-crm/actions/workflows/ci.yml/badge.svg)](https://github.com/thepillock/pureamiga-crm/actions/workflows/ci.yml)

A small Django app for tracking machines through the repair process:
**Received → Being worked on → Being tested → Returned**.

- **Board**: one column per stage. Cards show how many days a job has sat in its stage (red after 14). One click moves a job on.
- **Customers → Machines → Repair jobs.** Each machine has its own repair history, so a machine that comes back is booked in against the same record.
- **Booking in** records the work requested, condition on arrival, an items-received checklist (board, shields, case, keyboard, floppy, PSU, box, accessories), accessories and the quote.
- **Bench log**: timestamped notes on each job. Every stage change is recorded with who made it and when.
- **Admin** (`/admin/`) gives full editing of everything, plus user management.
- **Importer** for the old Jetpack CRM data in WordPress.

Staff-only: every page needs a login.

---

## Test and live versions

GitHub Actions runs the tests on every push. If they pass, it publishes a Docker image to GHCR:

| You do | Image built | Runs on Unraid as |
|---|---|---|
| Push to `main` | `ghcr.io/thepillock/pureamiga-crm:test` | **pureamiga-crm-test**, with a yellow TEST banner and its own database |
| Tag a release `vX.Y.Z` | `ghcr.io/thepillock/pureamiga-crm:latest` (also `:X.Y.Z`) | **pureamiga-crm**: the live system |

The version is shown in the footer of every page (`test-abc1234` or `v1.2.0`).

**To release:** once something on test is good, go to GitHub → Releases → *Draft a new release* → create the tag `v1.0.0` (then `v1.0.1`, `v1.1.0`, …) → *Publish*. About two minutes later `:latest` is ready, and you update the live container in Unraid. Tags with a hyphen (`v1.1.0-rc1`) get their own image tag but never `:latest`.

**To roll back live:** edit the container and change the repository tag from `:latest` to the previous version, e.g. `:1.0.0`.

---

## Deploying on Unraid (one-time setup)

### 1. Docker network
Both containers sit on the same custom Docker network as NPM+, and publish no ports. Check with `docker network ls`. If NPM+ isn't already on a custom network:

```sh
docker network create proxynet
```

Then edit the NPM+ container and set its **Network Type** to `proxynet`. The templates assume this name; change it in the template if yours differs.

### 2. Add the two containers
Copy the templates from this repo's `unraid/` folder onto the flash drive:

```sh
cd /boot/config/plugins/dockerMan/templates-user/
wget https://raw.githubusercontent.com/thepillock/pureamiga-crm/main/unraid/my-pureamiga-crm-test.xml
wget https://raw.githubusercontent.com/thepillock/pureamiga-crm/main/unraid/my-pureamiga-crm.xml
```

Then go to Docker → **Add Container** → pick the template from the *Template* dropdown → fill in:
- **Secret key**: a different one for each container. Generate with `openssl rand -base64 48`.
- **Hostname** and **Trusted origin**: e.g. `crm-test.yourdomain.net` and `https://crm-test.yourdomain.net`.

Do this once for **pureamiga-crm-test** and once for **pureamiga-crm**. Each container keeps its own data under `/mnt/user/appdata/<name>`. The extra parameters in the template make the container filesystem read-only, drop Linux capabilities and block privilege escalation.

### 3. NPM+ (LAN only)
Create an **Access List** "LAN only": allow `192.168.x.0/24` (add `100.64.0.0/10` if you use Tailscale), deny `all`.

Then add a **Proxy Host** for each container:

| Domain | Forward to | Access list | SSL |
|---|---|---|---|
| `crm-test.yourdomain.net` | `http://pureamiga-crm-test:8000` | LAN only | Let's Encrypt, Force SSL, HSTS |
| `crm.yourdomain.net` | `http://pureamiga-crm:8000` | LAN only | Let's Encrypt, Force SSL, HSTS |

Point both hostnames at the Unraid box in local DNS. If they aren't reachable from the internet, use the DNS challenge for the certificate. For access away from home, use Tailscale/WireGuard rather than port forwarding.

### 4. Create logins
Run this for each container:

```sh
docker exec -it -u 99:100 pureamiga-crm python manage.py createsuperuser
docker exec -it -u 99:100 pureamiga-crm-test python manage.py createsuperuser
```

To add more staff, go to `/admin/` → Users. Give technicians a first name (e.g. "Chris"): it's shown on the board and used by the importer.

### 5. Import the old Jetpack CRM data
Try it on **test** first. Create the technician logins before importing, so jobs marked "Chris - …" get assigned to them.

```sh
cp /path/to/localhost.sql /mnt/user/appdata/pureamiga-crm-test/import.sql
docker exec -u 99:100 pureamiga-crm-test python manage.py import_jetpack /data/import.sql            # dry run
docker exec -u 99:100 pureamiga-crm-test python manage.py import_jetpack /data/import.sql --commit   # for real
rm /mnt/user/appdata/pureamiga-crm-test/import.sql
```

When you're happy with how it looks, do the same with `pureamiga-crm`.

What the importer does:
- Imports the **contacts that have repair jobs**. Contact-form leads with no jobs (mostly spam) are skipped; `--include-leads` brings them in anyway.
- Turns each quote into a repair job: title, value, accepted date, costs, work requested, condition, accessories and the parts-sent checklist.
- Creates a machine per job from make/model + serial. Model names are normalised ("A1200" → Amiga 1200), and a customer's jobs with the same serial share one machine.
- Splits "Chris - In test" into stage + technician. Jobs with no status, or "Completed", go to **Returned**.
- Copies the HTML bench log and quote notes into the bench log, and keeps the old status text on each job.
- Safe to re-run: anything already imported is skipped.

### 6. Updates
- **Test**: after you push to `main`, wait for the green tick on GitHub, then click *Update* on pureamiga-crm-test in the Docker tab. You can also let the *Auto Update Applications* plugin update the test container automatically. Database migrations run on start.
- **Live**: after publishing a release, click *Update* on pureamiga-crm. Take a backup first (below).

### 7. Backups
Each container's data is a single SQLite file in its appdata folder. Take a consistent snapshot while it's running:

```sh
docker exec -u 99:100 pureamiga-crm python manage.py backup_db   # → appdata/pureamiga-crm/backups/, keeps 14
```

Schedule that nightly with the **User Scripts** plugin, and copy `backups/` off the server (Appdata Backup plugin, rclone, …). It's customer personal data, so keep the off-site copy encrypted.

To refresh **test** with a copy of live data:

```sh
docker stop pureamiga-crm-test
cp "$(ls -t /mnt/user/appdata/pureamiga-crm/backups/crm-*.sqlite3 | head -1)" /mnt/user/appdata/pureamiga-crm-test/crm.sqlite3
rm -f /mnt/user/appdata/pureamiga-crm-test/crm.sqlite3-wal /mnt/user/appdata/pureamiga-crm-test/crm.sqlite3-shm
docker start pureamiga-crm-test
```

---

## Development

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DJANGO_DEBUG=1 DJANGO_HTTPS=0
python manage.py migrate && python manage.py createsuperuser
python manage.py runserver
python manage.py test          # what CI runs
```

Model changes need a migration: `python manage.py makemigrations`. CI fails if you forget.

`docker-compose.yml` builds and runs the image from source locally. Copy `.env.example` to `.env` first.

## Day to day

- **New repair:** **+ Book in** → find or create the customer → pick their machine or enter a new one → it lands in **Received**.
- Move jobs with the arrow buttons on the board, or the stage bar on the job page. Moving a job to *Being worked on* assigns it to you if it has no technician yet.
- Search anywhere by name, email, serial or job ref (`PA0042`).
- Returned jobs stay on the board for 14 days. All of them are under **All jobs**.
