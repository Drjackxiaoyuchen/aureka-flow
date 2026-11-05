# Run Aureka Flow as a server

A visitor opens your server's URL, uploads FCS files, draws gates and clicks **Download analysis · ZIP**. Visitors need a browser; Python and FlowKit run on the server.

Each browser receives a separate opaque, HttpOnly session cookie. Samples, gates and downloads are scoped to that session. Tabs in the same browser on the same server share it; another browser gets an empty workspace. No user account is required by the application.

## Deploy on Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Drjackxiaoyuchen/aureka-flow)

1. Open the button and sign in to your Render account. Select the repository/Blueprint deployment.
2. Review the included `render.yaml`. It defines one Docker web service on the **free** compute plan, with a health check and reduced input limits for a small demo server. Do not select an upgrade unless you intend to pay for it.
3. Deploy it and wait for `/api/health` to pass. Render assigns an HTTPS `onrender.com` address.
4. Open that address and try the synthetic demo. Draw and save a population, then download the analysis ZIP. Share that app address with colleagues.

The button is a deployment setup link, not an already-running analyzer. The first deployment needs access to your hosting account. Render's [Blueprint reference](https://render.com/docs/blueprint-spec) documents the configuration.

Render's [free web-service limits](https://render.com/docs/free) include idle shutdown and loss of in-memory sessions on restart. Its free service can sleep after 15 minutes without traffic, earlier than our configured 30-minute session timeout. Download results during the working session. Choose and size a persistent compute service for regular shared use; this application does not provide durable event storage across restarts.

## Self-host with Docker

Install Docker, then from a source checkout:

```sh
docker compose up --build -d
```

Open **http://localhost:8080**. On a reachable server, visitors use that server's address and port. Inspect logs with `docker compose logs -f`; stop it with `docker compose down`. Restarting clears in-memory sessions.

The image runs as a non-root user. Its build context includes only the application and required package files; local FCS files, workspaces, reports, exports and credentials are excluded. CI builds the image and checks its health endpoint and session bootstrap.

For HTTPS, put the service behind your reverse proxy. Set `AUREKA_SECURE_COOKIES=1` for the HTTPS deployment. Keep the browser interface and API on the same origin. The app uses same-origin cookies and rejects cross-site browser mutations.

## Run directly with Python

After the normal installation:

```sh
python -m aureka_flow --host 0.0.0.0 --port 8080 --no-browser
```

Binding to a non-loopback host enables server mode. `PORT` and `HOST` environment variables are also supported. The default command without `--host` still binds to `127.0.0.1` for local use.

Use **one process and one replica**. The provided launcher enforces one Uvicorn worker because workspaces are held in that process. Multiple workers/replicas need a shared session and event store, which is not implemented here.

## Session and resource settings

Set these environment variables before starting the process:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `AUREKA_SERVER_MODE` | `0` | `1` enables hosted-service labeling and disables local validation-report serving. Set automatically for non-loopback CLI hosts and in Docker. |
| `AUREKA_ALLOWED_HOSTS` | Loopback names | Comma-separated hostnames accepted by TrustedHost middleware. The server launcher/Docker default to `*`; an operator can restrict this to the deployed hostname. |
| `AUREKA_SECURE_COOKIES` | `0` | Set to `1` behind HTTPS. Direct HTTPS requests also set Secure automatically. |
| `AUREKA_SESSION_TTL` | `3600` | Idle timeout in seconds. In-flight requests are not expired. |
| `AUREKA_MAX_SESSIONS` | `16` | Maximum simultaneous browser workspaces. New sessions get a busy response when full. |
| `AUREKA_MAX_FILE_MB` | `100` | Maximum individual FCS size, in MiB. |
| `AUREKA_SESSION_INPUT_MB` | `300` | FCS input budget per browser session. |
| `AUREKA_GLOBAL_INPUT_MB` | `768` | FCS input budget across sessions, including reservations during upload parsing. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Trusted reverse-proxy addresses for forwarded headers. |

There are also limits of 24 samples and 100 gates per workspace. RAM use exceeds FCS input size because parsing, transformations and analysis create additional arrays. Input budgets are not total-RAM limits. Size the host and limits for the actual event counts, channel counts and concurrent analyses.

The Compose example uses a 100 MiB session budget and 256 MiB global input budget. The free Render demo uses **20 MiB/file, 40 MiB/session, 80 MiB globally, eight sessions and a 30-minute idle timeout**. The app displays its configured upload limit.

Idle sessions are removed when the service receives a subsequent API request. **Clear my workspace** releases a user's samples and gates immediately. No other user's workspace is cleared.

## What users download

**Download analysis · ZIP** exports the current population for the selected sample in Explore & gate, or the checked samples and chosen population in Compare samples:

| Archive file | Contents |
| --- | --- |
| `population-statistics.csv` | Full-event counts, parent/total percentages, transformed medians, axes and source hashes. |
| `events/*.csv` | Optional full gated populations in every channel, with original zero-based event indices and source hashes. Channel values are uncompensated or compensated, without display transforms. |
| `project.json` | Saved gate hierarchy, per-gate settings, versions and source metadata; no FCS event bytes. |
| `gates.xml` | GatingML definitions and human-name mapping. |
| `manifest.json` | Downloaded population, selected sources, hashes, axis/compensation settings and software versions. |
| `README.txt` | Definitions and interpretation notes. |

The server writes event CSVs in chunks to temporary files rather than constructing a full CSV string in RAM. Temporary download files are deleted after the response completes. Incompatible samples stop a bundle download with an error instead of producing an apparently complete archive.

## Data handling

Hosted FCS files are uploaded to and processed on the host, with per-browser isolation. Local mode processes them on your computer. The app does not publish uploads to GitHub. Server mode does not expose the machine owner's local FlowJo-validation report or report directory.

Session cookies identify workspaces; they are not a substitute for organizational sign-in or a durable audit system. If access must be limited to a team, configure authentication at the hosting/reverse-proxy layer. Keep FCS sources and downloaded projects/statistics in your own records. The anonymous service is intended for research analysis.
