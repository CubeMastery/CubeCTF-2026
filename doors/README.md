# Doors

Doors is an attack/defense CTF service that exposes a custom Lua TCP server on port `4783`. The service emulates a small Windows command prompt with account registration, login, Windows-style virtual paths, directories, file upload/download, copy operations, and `.door` script execution.

## Service

Start the service from `service/`:

```sh
docker compose up --build -d
```

The prompt is line-oriented and ends responses with `C:\Doors> `. Useful commands include:

- `REGISTER <user> <password>`
- `LOGIN <user> <password>`
- `DIR [path]`, `CD <path>`, `MKDIR <path>`
- `PUT <path> <base64-data>`
- `GET <path>`
- `COPY <src> <dst>`
- `SET <name> <value>`
- `RUN <script.door>`
- `SESSION`, `ATTACH <token>`, `RECOVER <user>`

## Checker

The checker creates randomized users and files, plants flags under the returned username flagID at `Vault\flag.txt`, and verifies normal file and script behavior.

Run the full local test:

```sh
bash test.sh
```

## Exploits And Patches

There are four intentional vulnerabilities with matching exploit and patch directories:

- `path_prefix`: inconsistent path normalization
- `door_env`: script authorization before variable expansion
- `recover_stream`: unauthenticated weakly encrypted vault recovery
- `session_attach`: predictable session reattachment token

Each exploit directory contains `exploit.py`, `requirements.txt`, and `readme.md`. Each patch is in `patches/<exploit-name>.patch`.
