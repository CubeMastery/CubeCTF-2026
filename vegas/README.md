## vegas

A casino vault service that players drive over raw TCP rather than a browser:

```
nc <host> 7770
```

The service speaks a line protocol.  You type one command, it replies with
`key=value` lines (values containing spaces are quoted) and then prints the
`vegas>` prompt.  `help` lists every command.

| Command | Description |
| --- | --- |
| `register <username> <password>` | create a player (password 8+ chars) and open a session |
| `login <username> <password>` / `logout` | manage the session on the current connection |
| `session <token>` | resume a session returned by `register`, `login` or `put` |
| `whoami` | show the signed in player and chip balance |
| `lobby` | list the recent tables |
| `new <title> <teaser> <secret>` | store a private vault slip (requires a session) |
| `show <slip_id>` | show one slip; the vault blob is only revealed to its owner |
| `put <slip_id> <secret>` | vault desk: store a secret, returns owner/password/session |
| `get <slip_id> <owner> <password>` | vault desk: read a stored secret back |
| `sigs [slip_id]` / `rsa [slip_id]` | public provably fair signature and jackpot bond panels |
| `verify-sig` / `verify-rsa` | ask the house to verify one of its own proofs |
| `health` | service status and slip count |
| `quit` | disconnect |

Two weaknesses are baked into the house crypto, one per exploit in `exploits/`:
signing nonces are drawn from a small fixed pool that repeats, and every
jackpot bond is built from a shared prime.  `patches/` contains the fixes.

### Service layout

The service is a plain Python package, no third party dependencies:

| Module | Responsibility |
| --- | --- |
| `service/main.py` | entry point, starts the server |
| `service/vegas/config.py` | port, framing, crypto parameters, help text |
| `service/vegas/util.py` | randomness, time, ids, `key=value` formatting |
| `service/vegas/crypto.py` | vault cipher, Schnorr proofs, RSA bonds |
| `service/vegas/database.py` | players, sessions and slips |
| `service/vegas/views.py` | renders slips and proofs into wire format |
| `service/vegas/commands.py` | one function per command |
| `service/vegas/session.py` | per-connection session token |
| `service/vegas/server.py` | TCP server and command dispatch |
