# Škoda Mate on Unraid

Unraid runs the same container as Docker; only the paths and the way the container is started differ. These files are an
**extra option for Unraid only** — `docker-compose.yml` in the repository root stays the normal way to run Mate on a
Docker host, and neither replaces the other. Two files in `unraid/` do the Unraid part:

- `unraid/docker-compose.yml` — for Unraid's **Docker Compose Manager** plugin (or `docker compose` over SSH).
- `unraid/skoda-mate.xml` — an **Unraid template**: the app's entry for Community Applications, installed straight
from the Apps tab ([skoda-mate](https://ca.unraid.net/apps/skoda-mate-182eamj1i7s3dj)).

The repository root carries `ca_profile.xml` (the repository profile CA shows next to the app) and the AGPL-3.0
`LICENSE`; together with the template they are what the Community Applications submission scans ([section 8](#8-community-applications-submission)).

Unraid itself has no built-in Docker Compose support ([Docker overview](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/overview/)),
so the template is the native route and Compose Manager is a community plugin from the Apps tab.

The image is published on Docker Hub as [`steffenr/skoda-mate`](https://hub.docker.com/r/steffenr/skoda-mate) for
`linux/amd64` and `linux/arm64`, so both files **pull it and nothing is built on the server**. Everything after that
happens in the browser, exactly like the Docker setup in the [README](../README.md): the setup form asks for the
dashboard login and the Škoda API key, and no secret goes into a template field.

Škoda Mate is **listed in Community Applications**
([skoda-mate](https://ca.unraid.net/apps/skoda-mate-182eamj1i7s3dj)): search the Apps tab and install (step 2). The
*private*-folder route below is only for testing a template change before the next submission update.

## 1. The image

Unraid pulls `steffenr/skoda-mate:latest` on the first start, tagged `latest`, `X.Y` and `X.Y.Z`. Prefer a version that
only moves when you decide? Replace `:latest` with a release tag (`steffenr/skoda-mate:0.1.0`) in the template field or
in `unraid/docker-compose.yml`.

To fetch a new release by hand (Compose Manager, or over SSH): `docker pull steffenr/skoda-mate:latest`.

## 2. Start it

### Community Applications (the native Unraid way)

1. *Apps → search `skoda-mate`* and press *Install*. Adjust port and data path in the template if
   you like; Unraid creates the data path on first start. The template uses `/mnt/user/appdata/skoda-mate` and port `8080`.
2. Switch **Autostart** on for the container in the Docker tab so it comes back with the array, and check that the health
   indicator turns green (the image ships a health check against `/health`). The *WebUI* entry in the container's context
   menu opens the dashboard.

Testing a template change before the next submission update? Load it as a private template first — CA shows private
entries like listed apps, under category **Private**
([Unraid FAQ: private repositories](https://forums.unraid.net/topic/57181-docker-faq/)):
```bash
mkdir -p /boot/config/plugins/community.applications/private/skoda-mate
curl -fL https://raw.githubusercontent.com/steffenr/skoda-mate/main/unraid/skoda-mate.xml \
  -o /boot/config/plugins/community.applications/private/skoda-mate/skoda-mate.xml
```

### Docker Compose Manager (for the compose file)

1. Install the *Docker Compose Manager* plugin from the Apps tab, create a project named `skoda-mate`.
2. Paste the contents of [`unraid/docker-compose.yml`](../unraid/docker-compose.yml) into its compose editor and press *Compose up*.
   It uses `/mnt/user/appdata/skoda-mate` and port 8080; put `APPDATA=/mnt/user/other-share/skoda-mate` and/or
   `PORT=8099` in the project's `.env` file to change either.
3. Open `http://<unraid-ip>:8080/`.

Either way Unraid's **update check works**: *Docker → check for updates* compares the running container with
`steffenr/skoda-mate:latest` in the registry, and a new release shows up as an update — *Apply* (or *Compose up* after
`docker compose pull`) replaces the container. The appdata folder is untouched, and the database schema is migrated on
start.

## 3. First start

Open the WebUI. Until the setup form is finished, nothing else answers:

1. Dashboard login (e-mail and password, stored as a hash in the database).
2. Škoda API key from the MyŠkoda app plus your VIN(s) — Mate tests it right away and stores it encrypted.

The one-time **setup code** is only asked for when the first login is created from a public address (for example through
a reverse proxy that forwards one). Read it in the container log (*Logs* in the Docker tab) or from `setup-code.txt` in
the data path.

## 4. Behind a reverse proxy (SWAG, Nginx Proxy Manager, Traefik)

Mate speaks plain HTTP on port 8080; the proxy terminates TLS. Two things matter there, both about the client address:

- **Proxy headers.** Uvicorn only trusts `X-Forwarded-For` from `127.0.0.1` by default, so behind a proxy in another
  container every request looks like it comes from the proxy. Add to the container's *Extra Parameters* (template) or
  uncomment the `command:` line in the compose file:
  ```
  --proxy-headers --forwarded-allow-ips=172.16.0.0/12
  ```
  Use the network your proxy is in (the default Docker bridges are `172.16.0.0/12`; a `br0`/custom-network proxy needs
  your LAN range instead) and never `0.0.0.0/0` or `*` — anyone could then claim any address. With the right range the
  brute-force limit and the setup-code check see real visitors.
- **Cookie and HTTPS.** The session cookie gets the `Secure` flag automatically when the proxy sends
  `X-Forwarded-Proto: https` (Nginx Proxy Manager and SWAG do). Do not set `COOKIE_SECURE` there — set it to `true` only
  if a proxy sends no such header, otherwise the browser drops the cookie and login seems to "not stick".

Proxy target: scheme `http`, host = the Unraid IP (or the container name, if the proxy is in Mate's Docker network), port
`8080`. No websockets needed.

## 5. Data, backup and privacy

- Everything lives in the data path (`/data` in the container), by default `/mnt/user/appdata/skoda-mate`: SQLite
  database, `secret.key` (encrypts the Škoda API key and S-PIN) and, before the setup is done, `setup-code.txt`.
- **Keep it private.** Do not export this folder over SMB/NFS to other household users or devices, and keep it out of
  widely readable backups — whoever reads it can decrypt the Škoda API key. Mate creates the folder mode 0700 for uid
  10001, so a normal Unraid user cannot open it through a share; root and the file manager still can.
- **Keep it on the cache.** The `appdata` share is `Prefer` by default; `Cache-only` avoids a mover shuffle and SQLite
  writes on a spinning-down array. With no array started, `/mnt/user/...` paths do not exist, so the container waits.
- **Back up** by stopping the container and copying the folder, or let the *Appdata Backup* plugin do it while the
  container is stopped. An update never touches existing backups; the database schema is migrated on start.
- **No PUID/PGID.** Mate always runs as uid 10001 (not as `nobody`); the entrypoint takes ownership of the data path on
  start. Where `chown` is refused (mounted NFS, unusual ZFS setups), run `chown -R 10001:10001
  /mnt/user/appdata/skoda-mate` once as root. Commands inside the container need `-u 10001`
  (`docker exec -u 10001 skoda-mate python -m skoda_mate reset-password`), so no root-owned files land in the folder.
- Data on an *Unassigned Device*? Use access mode **Read/Write Slave** for that mapping, as Unraid's
  [container docs](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/managing-and-customizing-containers/)
  recommend.

## 6. Home Assistant

Set the broker up in the dashboard under *Settings → MQTT* (encrypted, with a test button); the `MQTT_*` variables are
only a fallback for older installs, and the Unraid files here leave them off. As broker address use your Home Assistant
host's LAN IP, not `localhost` — inside Mate's container that is Mate itself. See [HOME-ASSISTANT.md](HOME-ASSISTANT.md).

## 7. Trial run without a car

Set *Demo mode* (`DEMO=1`) in the template or compose file and restart: a fictional Enyaq with 60 days of history
appears, no account, no network. `DEMO_CARS=2` adds a second car. Clear it again afterwards.

## 8. Community Applications submission

The listing is live: [skoda-mate on ca.unraid.net](https://ca.unraid.net/apps/skoda-mate-182eamj1i7s3dj). CA still reads
the repository itself, not an upload: it must stay public and active, carry an OSI-approved `LICENSE` at the
root, a `ca_profile.xml` with a non-empty `<Profile>`, and at least one template XML with `<Repository>` (Docker) or
`<PluginURL>` (plugin). All three are in place; the template is `unraid/skoda-mate.xml` — changes to it go through the
submission flow again, so this section is also the maintenance recipe.

- **Validate and scan** in the submission flow at [ca.unraid.net/submit/new](https://ca.unraid.net/submit/new) after
every meaningful XML change, before pushing a release. The scan is what flags a broken `<TemplateURL>`, a dead icon or
screenshot URL, or a missing tag.
- **Fields the scan reads.** `<Name>`, `<Repository>`, `<Registry>`, `<Network>`, `<WebUI>`, `<Overview>`,
`<Category>`, `<Support>`, `<Project>`, `<TemplateURL>`, `<ReadMe>`, `<Icon>`, `<Screenshot>`, `<License>`,
`<Requires>` and one `<Config>` per port, path and variable. CA only rewrites `DateInstalled` and the saved values on
install; everything else is the file in this repository.
- **The icon and screenshots are hot-linked** from `raw.githubusercontent.com` on the `main` branch, so renaming
`skoda_mate/static/icon.svg` or a file in `docs/screenshots/` breaks the listing.
- **No Compose source package.** CA can package a repository as an immutable Compose archive (`<AppTemplateType>` plus a
pinned `<ComposeSourceCommit>`), but that SHA would have to be bumped for every release. The Docker template covers the
Apps tab, and `unraid/docker-compose.yml` covers Compose Manager for anyone who prefers it.
- **Nothing secret in the template.** The dashboard login, the API key and the S-PIN are asked by the setup form and
stored in `/data`; the template carries only the port, the data path and the optional variables.
