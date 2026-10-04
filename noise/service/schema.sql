CREATE TABLE IF NOT EXISTS users (
    id      INTEGER                             NOT NULL
        CONSTRAINT users_pk
            PRIMARY KEY AUTOINCREMENT,
    name    TEXT                                NOT NULL,
    pub     TEXT                                NOT NULL
        CONSTRAINT users_pub_ui
            UNIQUE,
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS groups (
    id      INTEGER                             NOT NULL
        CONSTRAINT groups_pk
            PRIMARY KEY AUTOINCREMENT,
    name    TEXT                                NOT NULL,
    pub     TEXT                                NOT NULL
        CONSTRAINT groups_pub_ui
            UNIQUE,
    priv    TEXT                                NOT NULL
        CONSTRAINT groups_priv_ui
            UNIQUE,
    owner   INT                                 NOT NULL
        CONSTRAINT groups_owner_fk
            REFERENCES users,
    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS dm (
    id      INTEGER                             NOT NULL
        CONSTRAINT dm_pk
            PRIMARY KEY AUTOINCREMENT,
    src_uid INT                                 NOT NULL
        CONSTRAINT dm_src_uid_fk
            REFERENCES users,
    dst_uid INT                                 NOT NULL
        CONSTRAINT dm_dst_uid_fk
            REFERENCES users,
    time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    message TEXT                                NOT NULL
);

CREATE INDEX IF NOT EXISTS dm_dst_uid_ix ON dm (dst_uid);

CREATE TABLE IF NOT EXISTS gmsg (
    id      INTEGER                             NOT NULL
        CONSTRAINT gmsg_pk
            PRIMARY KEY AUTOINCREMENT,
    src_uid INT                                 NOT NULL
        CONSTRAINT gmsg_src_uid_fk
            REFERENCES users,
    gid     INT                                 NOT NULL
        CONSTRAINT gmsg_gid_fk
            REFERENCES groups,
    time    TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
    message TEXT                                NOT NULL
);

CREATE INDEX IF NOT EXISTS gmsg_gid_ix ON gmsg (gid);

CREATE TABLE IF NOT EXISTS group_members (
    id   INTEGER                             NOT NULL
        CONSTRAINT group_members_pk
            PRIMARY KEY AUTOINCREMENT,
    gid  INT                                 NOT NULL
        CONSTRAINT group_members_gid_fk
            REFERENCES groups,
    uid  INT                                 NOT NULL
        CONSTRAINT group_members_uid_fk
            REFERENCES users,
    time TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS group_members_gid_ix ON group_members (gid);
CREATE INDEX IF NOT EXISTS group_members_uid_ix ON group_members (uid);
