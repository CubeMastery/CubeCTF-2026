# noise

Why use Signal when you could use Noise. The better* end-to-end encrypted messaging TUI.


## Run the service standalone

```bash
cd service && docker compose up --build       # binary protocol on :6426
```

## Client

A keyboard-driven [Textual](https://textual.textualize.io/) TUI.

```bash
cd service
python -m venv .venv && .venv/bin/pip install -r requirements-client.txt
.venv/bin/python noise_client.py bin://127.0.0.1:6426
```

## Binary protocol

```
header: !4sBBBI = magic "NOIZ", version, flags(req/ok/err), opcode, payload_len
fields: u8/u16/u32 (!B/!H/!I) and length-prefixed bytes/str (u32 + raw)
```

One opcode per `NoiseService` method; the token is a request field (no header).

## Vulns

| id | description | exploit | patch |
|----|-------------|---------|-------|
| V1 | Group RSA keys use near-equal primes, so the modulus factors | `weak_group_key` | `patches/weak_group_key.patch` |
| V2 | The token kind is never verified, so any token works anywhere | (none) | (none) |
| V3 | Invite checks the invitee's membership, not the caller's | `backwards_invite` | `patches/backwards_invite.patch` |
| V4 | Tokens are an unsalted hash of the id, so they are forgeable | `predictable_token` | `patches/predictable_token.patch` |

V2 ships without an exploit or patch. The flag_id is the group id; exploits resolve the
group's pubkey and owner from the public groups listing. Each exploit takes
`exploit.py <host> <flag_id>`.

## Performance

100 iterations each against the Dockerized binary service. Exploits run as a fresh process
per flag id. Flag gets and all exploits returned the correct flag for every id (100/100).

| op (x100)                 | total | per op |
|---------------------------|-------|--------|
| check                     | 86.1s | 861ms  |
| put                       | 64.2s | 642ms  |
| get                       | 6.1s  | 61ms   |
| exploit weak_group_key    | 16.8s | 168ms  |
| exploit backwards_invite  | 22.1s | 221ms  |
| exploit predictable_token | 14.2s | 142ms  |

Server container CPU (one core): avg 55%, peak ~100%.

check and put reuse one client and are bound by server-side RSA group-key generation.
Exploit timing is per fresh process, so it includes interpreter and library startup.
