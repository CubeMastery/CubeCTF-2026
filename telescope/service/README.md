# TelescopeNet Manual

### Connection

| Command | Arguments | Response | Description |
|---------|-----------|----------|-------------|
| `PING` | _none_ | `OK ORION` | Health check / keepalive |
| `BANNER` | _none_ | `OK TelescopeNet station=mesquite seed=<N>` | Station identification. The seed value is used in deterministic calculations (e.g., ephemeris, job IDs). |
| `QUIT` | _none_ | — | Close the connection |

### Authentication

| Command | Arguments | Response | Description |
|---------|-----------|----------|-------------|
| `REGISTER <username> <password>` | username (alphanumeric, `_`, `-`, `.`, max 40 chars), password | `OK registered` / `ERR exists` / `ERR register` | Create a new account. Passwords are hashed with FNV-1a 64-bit internally. |
| `LOGIN <username> <password>` | username, password | `OK session <username>` / `ERR auth` | Authenticate and start a session. |

### Telescope management (auth required)

| Command | Arguments | Response | Description |
|---------|-----------|----------|-------------|
| `ADD_SCOPE <name> <lat> <lon> <aperture> <mount ...>` | telescope name, latitude, longitude, aperture, mount type (rest of line after 5th field) | `OK scope` / `ERR scope` | Register a new telescope. Mount is everything after the 5th whitespace-delimited field. |
| `LIST_SCOPES` | _none_ | `OK <name,lat,lon,aperture,mount>\|...` | List all telescopes owned by the authenticated user. Fields are pipe-separated; multiple scopes are separated by `\|`. Newlines and pipes in values are replaced with spaces. |

### Notes (auth required)

| Command | Arguments | Response | Description |
|---------|-----------|----------|-------------|
| `STORE_NOTE <scope> <title> <body ...>` | telescope scope name, title, body (rest of line) | `OK note` / `ERR note` | Save an observation note. Body is everything after the 3rd field. |
| `GET_NOTE <title>` | title | `OK <body>` / `ERR missing` | Retrieve the most recent note matching the given title for the current user. |
| `LIST_NOTES` | _none_ | `OK <title,scope>\|...` | List all notes owned by the authenticated user. Each entry is `title,scope`. Ordered newest first. |

### Sky data (auth required)

| Command | Arguments | Response | Description |
|---------|-----------|----------|-------------|
| `CONSTELLATIONS <lat> <lon> <month>` | latitude, longitude, month (1-12) | `OK <constellation> ...` / `ERR sky` | Returns 4 constellations visible during the given month. Seasons: winter (Dec-Feb), spring (Mar-May), summer (Jun-Aug), autumn (Sep-Nov). |
| `EPHEMERIS <target>` | target name | `OK alt=<N> az=<N> seeing=<1-5>` / `ERR eph` | Deterministic simulated ephemeris. Altitude, azimuth, and seeing are derived from `FNV-1a(user + target)`. Seeing is on a scale of 1-5. |

### Job queue (auth required)

| Command | Arguments | Response | Description |
|---------|-----------|----------|-------------|
| `QUEUE_AUDIT <target>` | target identifier | `OK job <id>` / `ERR job` | Submit an audit job for the given target. The job ID is a 16-hex-character FNV-1a hash of `user:target:counter`. Uses the target's most recent note in its result. |
| `JOB_RESULT <job-id>` | job ID (hex string) | `OK <result>` / `ERR missing` | Retrieve the result of a previously queued audit job. Format: `audit target=<target> last-note=<note-body>`. |

### Calibration workflow (auth required)

| Command | Arguments | Response | Description |
|---------|-----------|----------|-------------|
| `CAL_OPEN <scope>` | scope name | `OK cal` / `ERR cal` | Open a new calibration buffer for the given scope. Initializes default quality of 7. |
| `CAL_PREFETCH <user>` | target username | `OK prefetched` / `ERR cal` | Copy calibration data from another user's note preview into the current session's buffer. Uses that user's most recent note as a preview. |
| `CAL_COMMIT` | _none_ | `OK committed [<memo>]` / `ERR cal` | Persist the current calibration buffer to the database. If it was opened for a different user, the buffer is kept (cross-user cal). Otherwise it is discarded. |
| `CAL_DISCARD` | _none_ | `OK discarded` / `ERR cal` | Discard the current calibration buffer without saving. |

