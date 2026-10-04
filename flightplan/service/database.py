import sqlite3

from config import DB_PATH


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute(
            """
            create table if not exists users (
                id integer primary key autoincrement,
                username text unique not null,
                password_hash text not null,
                full_name text not null,
                home_base text not null,
                created_at integer not null
            )
            """
        )
        conn.execute(
            """
            create table if not exists plans (
                id integer primary key autoincrement,
                ident text unique not null,
                owner_id integer not null,
                callsign text not null,
                departure text not null,
                arrival text not null,
                alternate text not null,
                route text not null,
                cruise text not null,
                fuel integer not null,
                passengers integer not null,
                private_notes text not null,
                created_at integer not null,
                updated_at integer not null,
                foreign key(owner_id) references users(id)
            )
            """
        )
