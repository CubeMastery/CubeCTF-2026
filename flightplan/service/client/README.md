# Flight Plan Terminal Client

Full-screen dark-mode terminal client for the Cairn Flight Plan Exchange. The
service is an API-only HTTP service, so this client talks to it over HTTP and
renders the portal layout (runway masthead, panels, stat strips, dark packet
blocks) as a TUI.

## Install

```bash
cd client
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
# defaults to http://localhost:4729
.venv/bin/python flightplan_tui.py

# point at another service
.venv/bin/python flightplan_tui.py --host 10.0.0.8 --port 4729
.venv/bin/python flightplan_tui.py --url http://10.0.0.8:4729

# or set the URL in the environment
FLIGHTPLAN_URL=http://10.0.0.8:4729 .venv/bin/python flightplan_tui.py
```

If the service cannot be reached at startup the client prints
`cannot connect to <url>: <reason>` and exits with status 1. Proxy environment
variables (`http_proxy`, `HTTP_PROXY`, `https_proxy`, `ALL_PROXY`, ...) are
ignored; connections are always direct.

## Options

| Flag | Effect                                                  |
| ---- | ------------------------------------------------------- |
| `-v` | Log every API request and response to stdout after exit |

The verbose log shows each request line, its JSON body, and the response status
and body, for example:

```
→ POST /api/login
  {"username":"op123","password":"hunter2hunter2"}
← 200 OK
  {"ok":true,"username":"op123","full_name":"Op One","home_base":"KMSP"}
```

## Screens

- **Home** — portal landing page, AIRAC cycle strip, and a sample station briefing.
- **Login / Register** — operator sign-in and account creation.
- **Dashboard** — operator stats, the flight plan filing form, and every filed plan.
- **Plan** — dispatch release with the private crew remarks.
- **Briefing** — the public station packet for a plan (JSON).

## Keys

| Key     | Action                              |
| ------- | ----------------------------------- |
| `enter` | Submit a form from any input        |
| `tab`   | Move focus between fields           |
| `esc`   | Back to the previous screen         |
| `q`     | Quit                                |

## API used

| Endpoint                                | Purpose                    |
| --------------------------------------- | -------------------------- |
| `GET /`                                | Portal metadata            |
| `GET /airac.json`                       | AIRAC cycle and beacon     |
| `POST /api/register`                    | Create operator account    |
| `POST /api/login`                       | Log in (sets session cookie) |
| `POST /api/logout`                      | End the session            |
| `GET /api/plans`                        | List own filed plans       |
| `POST /api/plans`                       | File a plan                |
| `GET /api/briefing/{ident}`             | Public station packet      |
| `GET /api/plans/{ident}/private`        | Crew remarks               |
| `GET /api/plans/{ident}/navlog`         | Unsealed navlog record     |
| `GET /api/briefing/{ident}/loadsheet`   | Dispatch loadsheet packet  |
