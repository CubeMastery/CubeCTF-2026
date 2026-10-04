# Doors Command Service

### Manual

## Connecting

```bash
nc localhost 4783
```

On connection you will see:

```
DOORS 1.0
C:\Doors>
```

All commands are terminated by a newline (`\n`). Responses are echoed back with the `C:\Doors>` prompt prefix. Command names and paths are case-insensitive.

## Commands

### PING

Health check. Returns `OK PONG`.

```
PING
```

### HELP

Lists all available commands.

```
HELP
```

Returns: `REGISTER LOGIN DIR CD MKDIR PUT GET COPY RUN SET SESSION ATTACH RECOVER`

### REGISTER <username> <password>

Creates a new user account. Usernames must be 3–40 characters, match `[A-Za-z0-9_.-]`, and must not already exist.

```
REGISTER alice secret123
```

Response: `OK registered` or `ERR exists` / `ERR invalid user`

### LOGIN <username> <password>

Authenticates as a user. Creates a session scoped to the user's home directory (`C:/Users/<username>`).

```
LOGIN alice secret123
```

Response: `OK logged in` or `ERR auth`

### ATTACH <session_token>

Borrow another user's session by their token (see SESSION command). Useful for sharing sessions.

```
ATTACH D5f3kX9aX4
```

Response: `OK attached` or `ERR attach`

### RECOVER <username>

Returns an encrypted recovery blob containing all files in the user's `Vault/` directory. The response contains a nonce and base64-encoded payload. Used for account recovery.

```
RECOVER alice
```

Response: `OK <nonce> <blob>` or `ERR no user`

### WHOAMI

Shows the current username.

```
WHOAMI
```

Response: `OK alice` (requires login)

### PWD / CD [path]

Without arguments, prints the current working directory. With a path argument, changes it.

```
PWD
CD Documents
CD ..
```

Response: `OK C:\Users\alice` or `ERR access denied`

### DIR [path]

Lists files and directories in the given path (defaults to current directory). Returns base64-encoded output. Directories are prefixed with `[DIR]`, files show their byte size.

```
DIR
DIR Documents
```

Response: `OK <base64_encoded_listing>` or `ERR access denied` / `ERR missing`

### MKDIR <path>

Creates a directory (and any parent directories).

```
MKDIR Projects
MKDIR Documents/Notes/Personal
```

Response: `OK created` or `ERR access denied`

### PUT <filename> <base64_data>

Writes base64-encoded data to a file. Creates parent directories as needed.

```
PUT hello.txt SGVsbG8gV29ybGQhCg==
```

Response: `OK stored` or `ERR access denied`

### GET <filename>

Reads a file and returns its contents base64-encoded.

```
GET hello.txt
```

Response: `OK <base64_data>` or `ERR missing` / `ERR access denied`

### COPY <source> <destination>

Copies a file from source to destination within the user's accessible paths.

```
COPY hello.txt backup.txt
```

Response: `OK copied` or `ERR access denied` / `ERR missing`

### SET <name> <value>

Sets an environment variable for the current session.

```
SET GREETING Hello
```

Response: `OK set`

### SESSION

Returns the current user's session token, which can be shared with others to attach via the ATTACH command.

```
SESSION
```

Response: `OK D5f3kX9aX4`

### RUN <script.door> [args...]

Executes a `.door` script file (max 48 lines). Scripts support `ECHO`, `SET`, `TYPE`, and `COPY` commands. Variables can be referenced as `%%VAR%%` and positional arguments as `%%1%%`, `%%2%%`, etc.

Example script at `C:/Users/alice/scripts/hello.door`:
```
ECHO Hello %%1%%
SET NAME %%1%%
TYPE Documents/welcome.txt
```

```
RUN scripts/hello.door Alice
```

Response: `OK <base64_encoded_output>` or `ERR ...`

## File System Layout

The service provides a virtual filesystem rooted at `C:`. After registration, each user gets:

| Path | Purpose |
|---|---|
| `C:/Users/<user>/` | Home directory |
| `C:/Users/<user>/Desktop/` | Desktop files |
| `C:/Users/<user>/Documents/` | Documents |
| `C:/Users/<user>/Vault/` | Encrypted vault (recoverable) |
| `C:/Users/<user>/Public/` | Public files shared across users |
| `C:/Users/<user>/Inbox/` | Inbox area |
| `C:/Users/<user>/AppData/Local/Doors/` | Application data |

All users can read/write within their own home directory and in `C:/Users/Public`. Paths outside these areas return "access denied".

## Script Format (`.door`)

Scripts are plain text files with `.door` extension, max 48 lines. Comments start with `::` or `REM`. Supported commands:

| Command | Description |
|---|---|
| `ECHO <message>` | Output a message to script output |
| `SET <var> <value>` | Set session environment variable |
| `TYPE <file>` | Read and output file contents |
| `COPY <src> <dst>` | Copy a file within accessible paths |

Variables expand at runtime using the user's session state. Positional arguments are passed as `%%1%%`, `%%2%%`, etc.

## Environment Variables

The following environment variables are available to scripts:

| Variable | Description |
|---|---|
| `%USER%` / `%%USER%%` | Current username |
| `%HOME%` / `%%HOME%%` | User's home directory path |
| `%CD%` / `%%CD%%` | Current working directory |
