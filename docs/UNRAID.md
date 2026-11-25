# Škoda Mate on Unraid

Unraid runs the same container as Docker; only the paths and the way the container is started differ. These files are an
**extra option for Unraid only** — `docker-compose.yml` in the repository root stays the normal way to run Mate on a
Docker host, and neither replaces the other. Two files in `unraid/` do the Unraid part:

- `unraid/docker-compose.yml` — for Unraid's **Docker Compose Manager** plugin (or `docker compose` over SSH).
- `unraid/skoda-mate.xml` — an **Unraid template**, installed as a private Community Applications template.

Unraid itself has no built-in Docker Compose support ([Docker overview](https://docs.unraid.net/unraid-os/using-unraid-to/run-docker-containers/overview/)),
so the template is the native route and Compose Manager is a community plugin from the Apps tab.

The image is published on Docker Hub as [`steffenr/skoda-mate`](https://hub.docker.com/r/steffenr/skoda-mate) for
`linux/amd64` and `linux/arm64`, so both files **pull it and nothing is built on the server**. Everything after that
happens in the browser, exactly like the Docker setup in the [README](../README.md): the setup form asks for the
dashboard login and the Škoda API key, and no secret goes into a template field.

There is no Community Applications entry yet. The template goes into CA's *private* folder, which makes it show up in
the Apps tab like a listed app (step 2).

## 1. The image

Unraid pulls `steffenr/skoda-mate:latest` on the first start, tagged `latest`, `X.Y` and `X.Y.Z`. Prefer a version that
only moves when you decide? Replace `:latest` with a release tag (`steffenr/skoda-mate:0.1.0`) in the template field or
in `unraid/docker-compose.yml`.

To fetch a new release by hand (Compose Manager, or over SSH): `docker pull steffenr/skoda-mate:latest`.

## 2. Start it

### Private Community Applications template (native Unraid way)

1. In a terminal on the server (web terminal or SSH), create the folder for private templates and download the template
   into it ([Unraid FAQ: private repositories](https://forums.unraid.net/topic/57181-docker-faq/)):
   ```bash
   mkdir -p /boot/config/plugins/community.applications/private/skoda-mate
   curl -fL https://raw.githubusercontent.com/steffenr/skoda-mate/main/unraid/skoda-mate.xml \
     -o /boot/config/plugins/community.applications/private/skoda-mate/skoda-mate.xml
   ```
2. *Apps → search `skoda-mate`*, category **Private**, and press *Install*. Adjust port and data path in the template if
   you like; Unraid creates the data path on first start.
3. Switch **Autostart** on for the container in the Docker tab so it comes back with the array, and check that the health
   indicator turns green (the image ships a health check against `/health`). The *WebUI* entry in the container's context
   menu opens the dashboard.

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
