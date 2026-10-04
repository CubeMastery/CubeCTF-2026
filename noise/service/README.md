# noise
The better e2ee messaging app.

Why have Signal when you could have Noise.

## Server

With Docker:

    docker compose up --build

Data persists in the `data` dir. To run it directly instead:

    pip install -r requirements.txt
    python noise_socket_server.py

Environment: `NOISE_BIN_PORT` (default 6426), `NOISE_DB` (sqlite path).

## Client

A keyboard driven text UI (Textual).

    pip install -r requirements-client.txt
    python noise_client.py bin://127.0.0.1:6426

Pick a user or group on the left, read messages on the right. Keys: arrows move,
Enter selects, s send, g new group, i invite, r refresh, q quit.
