PORT = 7770
PROMPT = "vegas> "
BANNER = "\n".join(
    [
        "Vegas - casino vault floor",
        "Type 'help' for the command list, 'quit' to leave the floor.",
        "",
    ]
)

GROUP_P = 21_474_836_291
GROUP_Q = 2_147_483_629
GROUP_G = 1_024

RSA_E = 65_537
RSA_SHARED_P = 2_147_483_647
RSA_Q_POOL = [
    2_147_483_629,
    2_147_483_587,
    2_147_483_579,
    2_147_483_563,
    2_147_483_549,
    2_147_483_543,
    2_147_483_497,
    2_147_483_489,
]

STARTING_CHIPS = 5_000
PITBOSS_CHIPS = 25_000

HOUSE_SIGNING_KEY = 1_337_337

MAX_TITLE = 72
MAX_TEASER = 140
MIN_PASSWORD = 8
IDLE_TIMEOUT = 600

HELP = [
    "Commands:",
    "  help                              show this help",
    "  health                            service health and slip count",
    "  register <username> <password>    join the floor and open a session",
    "  login <username> <password>       open a session for an existing player",
    "  logout                            drop the current session",
    "  session <token>                   resume a session from a token",
    "  whoami                            show the signed in player",
    "  new <title> <teaser> <secret>     store a private vault slip (session)",
    "  show <slip_id>                    show one vault slip and its proofs",
    "  put <slip_id> <secret>            vault desk: store a secret for a player",
    "  get <slip_id> <owner> <password>  vault desk: read a stored secret back",
    "  sigs [slip_id]                    provably fair signature panel",
    "  rsa [slip_id]                     jackpot bond panel",
    "  verify-sig <message> <commitment> <challenge> <response> <public_key>",
    "  verify-rsa <secret> <modulus> <exponent> <code_hex>",
    "  quit                              leave the floor",
]
