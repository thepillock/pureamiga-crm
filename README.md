# Pure Amiga repairs CRM

[![CI](https://github.com/thepillock/pureamiga-crm/actions/workflows/ci.yml/badge.svg)](https://github.com/thepillock/pureamiga-crm/actions/workflows/ci.yml)

A small Django app for tracking machines through the repair process:
**Received → Being worked on → Being tested → Returned**.

- **Board**: one column per stage. Cards show how many days a job has sat in its stage (red after 14). One click moves a job on.
- **Customers → Machines → Repair jobs.** Each machine has its own repair history, so a machine that comes back is booked in against the same record.
- **Booking in** records the work requested, condition on arrival, an items-received checklist (board, shields, case, keyboard, floppy, PSU, box, accessories), accessories and the quote.
- **Bench log**: timestamped notes on each job. Every stage change is recorded with who made it and when.
- **Tools** (admins): import from the old Jetpack CRM, and download a backup.
- **Admin** (`/admin/`) gives full editing of everything, plus user management.

Every page needs a login.

---

## Deploying on Unraid

Nothing to configure: no secrets, no hostnames, no custom Docker network. The app creates its own secret key in its data folder on first start.

### 1. Add the containers
On Unraid, copy the templates onto the flash drive:

```sh
cd /boot/config/plugins/dockerMan/templates-user/
wget -O my-pureamiga-crm-test.xml https://raw.githubusercontent.com/thepillock/pureamiga-crm/main/unraid/pureamiga-crm-test.xml
wget -O my-pureamiga-crm.xml      https://raw.githubusercontent.com/thepillock/pureamiga-crm/main/unraid/pureamiga-crm.xml
```

Docker → **Add Container** → pick **pureamiga-crm-test** from the *Template* dropdown → **Apply**. Repeat for **pureamiga-crm**.

| Container | Image | Port | Data |
|---|---|---|---|
| pureamiga-crm-test | `ghcr.io/thepillock/pureamiga-crm:test` | 3301 | `/mnt/user/appdata/pureamiga-crm-test` |
| pureamiga-crm | `ghcr.io/thepillock/pureamiga-crm:latest` | 3300 | `/mnt/user/appdata/pureamiga-crm` |

The test image shows a yellow-and-black **TEST** banner, and every page shows its version in the footer. Unraid's health column uses the built-in `/healthz` check.

### 2. First login
Click the container's icon → **WebUI** (or browse to `http://<unraid-ip>:3301`). With no accounts yet, it asks you to create the first one, which becomes an administrator. Add other staff in **Admin → Users**. Give technicians a first name (e.g. "Chris"): it's shown on the board and used by the importer.

The setup page only exists until the first account is created, so do this straight after starting each container.

### 3. Import the old Jetpack CRM data
Do this on **test** first. Create the technician accounts first, so jobs marked "Chris - …" get assigned to them. Then **Tools → Import from Jetpack CRM**: upload the phpMyAdmin `.sql` export and run it as a dry run. If the summary looks right, upload again with **Import for real** ticked. When you're happy with how test looks, do the same on live.

What the importer does:
- Imports the contacts that have repair jobs. Contact-form leads with no jobs (mostly spam) are skipped unless you tick the box.
- Turns each quote into a repair job: title, value, accepted date, costs, work requested, condition, accessories and the parts-sent checklist.
- Creates a machine per job from make/model + serial. Model names are normalised ("A1200" → Amiga 1200), and a customer's jobs with the same serial share one machine.
- Splits "Chris - In test" into stage + technician. Jobs with no status, or "Completed", go to **Returned**.
- Copies the bench log and quote notes across, splitting the bench log into one entry per date line (`21/2/2022`), and keeps the old status text on each job.
- Picks up the repair ref from the bench log ("Repair Ref B12", "Repair number A04", "Repair A11"). If two jobs share a ref, the later one is left blank and listed in the summary.
- Re-running is safe: anything already imported is skipped.

### 4. NPM+ (optional, recommended)
Add a Proxy Host pointing at `http://<unraid-ip>:3300` (and one for `:3301` if you want test behind it too). Turn on SSL, Force SSL and HSTS, and put an access list or authentication in front of it. Over HTTPS the app marks its cookies Secure automatically; nothing to set. If you upload the Jetpack dump through NPM+, make sure its upload size limit allows a file of that size, or do the import at `http://<unraid-ip>:port` on the LAN instead.

---

## Test and live

GitHub Actions runs the tests on every push. If they pass, it builds the image:

| You do | Image | Container |
|---|---|---|
| Push to `main` | `:test` | pureamiga-crm-test |
| Publish a release `vX.Y.Z` | `:latest` (also `:X.Y.Z`, `:X.Y`) | pureamiga-crm |

**To release:** on GitHub, go to Releases → *Draft a new release* → create tag `v1.0.0` → *Publish*. About two minutes later, Unraid's Docker tab shows *update ready* on pureamiga-crm. Database migrations run automatically on start.

**To roll back live:** edit the container and change `:latest` to the previous version, e.g. `:1.0.0`.

## Backups

**Tools → Download backup now** gives you a copy of the whole database, and also keeps one in the data folder under `backups/` (last 14). For scheduled backups, the Appdata Backup plugin covers `/mnt/user/appdata/pureamiga-crm`. Or run this nightly with User Scripts:

```sh
docker exec -u 99:100 pureamiga-crm python manage.py backup_db
```

It's customer personal data, so keep off-site copies encrypted.

To copy live data into test, stop test, copy a backup over it, and start it again:

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
DJANGO_DEBUG=1 python manage.py runserver     # data goes in ./data
python manage.py test                         # what CI runs
```

Model changes need a migration: `python manage.py makemigrations`. CI fails if you forget.

Optional environment overrides: `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `CRM_ENVIRONMENT` (banner text; set it empty to hide the banner), `PUID`/`PGID`, `PORT`.

## Day to day

- **New repair:** **+ Book in** → find or create the customer → pick their machine or enter a new one → it lands in **Received**.
- Move jobs with the arrow buttons on the board, or the stage bar on the job page. Moving a job to *Being worked on* assigns it to you if it has no technician yet.
- Search anywhere by name, email, serial, job ref (`PA0042`) or repair ref (`B55`).
- **Job ref vs repair ref:** every job gets a job ref (`PA0042`). Jobs that turn into a repair also get a repair ref: two digits, or a letter and two digits (`36`, `A04`, `B55`). Set it on the job's Edit page, or click **Assign** on the job page to take the next free one.
- **Bench log:** each entry can be edited (text and date) or deleted. If an entry has dates on their own lines (`21/2/2022`), **Split by date** turns it into one entry per date.
- Returned jobs stay on the board for 14 days. All of them are under **All jobs**.
