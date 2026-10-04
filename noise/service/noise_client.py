#!/usr/bin/env python3
"""Textual TUI for noise.

Single two-pane screen, chat-client style:
  * left  = channels: a DIRECT MESSAGES section (one row per user) and a GROUPS
            section (one row per group)
  * right = the selected channel's conversation (a header + a messages table)

Keyboard: arrows/Enter pick a channel on the left, Tab focuses the table to
scroll it, and the footer keys act on the selected channel -- (r)efresh,
(s)end, (g) new group, (i)nvite, (q)uit.

Messages are RSA-encrypted client-side with the recipient's / group's public key
before sending (RSA only, no AES). A direct message is double-sent: one copy
encrypted to the recipient, and one encrypted to yourself (tagged with the peer
id) so your own sent messages appear in the conversation. All blocking work
(HTTP, RSA keygen) runs off the UI thread.
"""
import asyncio
import json
import os
import sys

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from noise import crypto
from noise.binapi import ApiError, BinaryNoiseClient
from noise.binproto import BIN_PORT


def make_client(url: str) -> BinaryNoiseClient:
    """Build a binary client from `host`, `host:port`, or `bin://host:port`."""
    hostport = url[len("bin://"):] if url.startswith("bin://") else url
    host, _, port = hostport.partition(":")
    return BinaryNoiseClient(host, int(port) if port else BIN_PORT)


STATE_PATH = os.environ.get("NOISE_CLIENT_STATE", "noise_client_state.json")
DEFAULT_HOST = os.environ.get("NOISE_HOST", "bin://127.0.0.1:6426")

# Self-copy tag for double-sent DMs: marker + "<peer_id>\0" + text, encrypted to
# our own key. Lets us recognize and group messages we sent.
SENT_MARKER = "\x00noise-sent\x00"


def load_state() -> dict | None:
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return None


def save_state(state: dict):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f)


# --- modal dialogs ----------------------------------------------------------


class PromptScreen(ModalScreen[str | None]):
    """One-line text input. Enter submits, Escape cancels (returns None)."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str):
        super().__init__()
        self._prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._prompt)
            yield Input(id="field")

    def on_mount(self):
        self.query_one("#field", Input).focus()

    def on_input_submitted(self, event: Input.Submitted):
        self.dismiss(event.value)

    def action_cancel(self):
        self.dismiss(None)


class PickScreen(ModalScreen[int | None]):
    """Pick one row from a list, returns its id. Escape cancels."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, items: list[tuple[int, str]]):
        super().__init__()
        self._title = title
        self._items = items

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._title)
            yield OptionList(id="picker")

    def on_mount(self):
        ol = self.query_one("#picker", OptionList)
        if not self._items:
            ol.add_option(Option("(nobody here)", disabled=True))
        for item_id, label in self._items:
            ol.add_option(Option(Text(label), id=str(item_id)))
        if self._items:
            ol.highlighted = 0
        ol.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        self.dismiss(int(event.option.id))

    def action_cancel(self):
        self.dismiss(None)


# --- main app ---------------------------------------------------------------


class NoiseApp(App):
    TITLE = "noise"
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    #body { height: 1fr; }
    #sidebar { width: 30; border-right: solid $panel; padding: 0; }
    #content { width: 1fr; }
    #content-title { padding: 0 1; color: $text; }
    #messages { height: 1fr; }
    PromptScreen, PickScreen { align: center middle; }
    #dialog {
        width: 64; height: auto; max-height: 80%;
        border: solid $panel; background: $surface; padding: 1 2;
    }
    #dialog Label { padding-bottom: 1; }
    #picker { height: auto; max-height: 20; }
    """
    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("s", "send", "Send"),
        ("g", "new_group", "New group"),
        ("i", "invite", "Invite"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, host: str):
        super().__init__()
        self.host = host
        self.api = make_client(host)
        self.state: dict | None = None
        self.token: str | None = None
        self.users: list = []  # other users (DM peers)
        self.groups: list = []
        self.keys: list[str] = []  # ordered selectable channel keys: "u:<id>" / "g:<id>"
        self.current: tuple[str | None, object] = (None, None)  # ("dm", user) | ("group", group)
        self._active_key: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield OptionList(id="sidebar")
            with Vertical(id="content"):
                yield Static("", id="content-title")
                yield DataTable(id="messages", cursor_type="row")
        yield Footer()

    # --- blocking-work helpers ------------------------------------------

    async def off_thread(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    async def guard(self, fn, *args):
        """Run an API call, surfacing ApiError as a toast. Returns None on error."""
        try:
            return await self.off_thread(fn, *args)
        except ApiError as e:
            self.notify(f"Error: {e.message}", severity="error")
            return None

    # --- startup ---------------------------------------------------------

    def on_mount(self):
        self.query_one("#messages", DataTable).add_columns("Time", "From", "Message")
        self.state = load_state()
        self.run_worker(self._startup())

    async def _startup(self):
        if self.state is not None:
            self.token = await self.guard(self.api.authenticate, self.state["pubkey"], self.state["privkey"])
            if self.token is None:
                self.notify("Stored login rejected; create a new user.", severity="warning")
                self.state = None
        if self.state is None:
            if not await self._create_user():
                self.exit()
                return
        self.sub_title = f"{self.state['name']} (#{self.state['uid']})  @ {self.host}"
        await self._load_lists()

    async def _create_user(self) -> bool:
        name = await self.push_screen_wait(PromptScreen("Choose a name:"))
        if not name:
            return False
        key = await self.off_thread(crypto.generate_keypair)
        pub, priv = crypto.pubkey_to_base64(key.public_key()), crypto.privkey_to_base64(key)
        user = await self.guard(self.api.register, pub, name)
        if user is None:
            return False
        self.token = await self.off_thread(self.api.authenticate, pub, priv)
        self.state = {"uid": user.id, "name": user.name, "pubkey": pub, "privkey": priv}
        save_state(self.state)
        self.notify(f"Registered as {user.name} (uid {user.id}).")
        return True

    # --- sidebar ---------------------------------------------------------

    async def _load_lists(self):
        all_users = await self.guard(self.api.get_users) or []
        self.users = [u for u in all_users if u.id != self.state["uid"]]
        self.groups = await self.guard(self.api.list_groups, self.token) or []
        self._populate_sidebar()

    def _populate_sidebar(self):
        ol = self.query_one("#sidebar", OptionList)
        want = self._active_key
        ol.clear_options()
        ol.add_option(Option(Text("DIRECT MESSAGES", style="dim"), disabled=True))
        for u in self.users:
            ol.add_option(Option(Text(f"  {u.name} (#{u.id})"), id=f"u:{u.id}"))
        ol.add_option(Option(Text("GROUPS", style="dim"), disabled=True))
        for g in self.groups:
            ol.add_option(Option(Text(f"  {g.name} (#{g.id})"), id=f"g:{g.id}"))

        self.keys = [f"u:{u.id}" for u in self.users] + [f"g:{g.id}" for g in self.groups]
        if not self.keys:
            self.current = (None, None)
            self._active_key = None
            self._show_empty()
            ol.focus()
            return
        target = want if want in self.keys else self.keys[0]
        self._active_key = None  # force the highlight handler to load it
        ol.highlighted = ol.get_option_index(target)
        ol.focus()

    def _show_empty(self):
        self.query_one("#content-title", Static).update(
            "No conversations yet. Press (g) to create a group, or wait for other users."
        )
        self.query_one("#messages", DataTable).clear()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted):
        if event.option_list.id != "sidebar" or event.option is None:
            return
        key = event.option.id
        if key is None or key == self._active_key:
            return
        if key.startswith("u:"):
            uid = int(key[2:])
            user = next((u for u in self.users if u.id == uid), None)
            if user is None:
                return
            self.current = ("dm", user)
        else:
            gid = int(key[2:])
            group = next((g for g in self.groups if g.id == gid), None)
            if group is None:
                return
            self.current = ("group", group)
        self.run_worker(self._load_current(), exclusive=True, group="load")

    # --- content pane ----------------------------------------------------

    async def _load_current(self):
        kind, obj = self.current
        if kind is None:
            self._show_empty()
            return
        self._active_key = f"u:{obj.id}" if kind == "dm" else f"g:{obj.id}"
        table = self.query_one("#messages", DataTable)
        title = self.query_one("#content-title", Static)
        if kind == "dm":
            inbox = await self.guard(self.api.get_messages, self.token) or []
            rows = self._conversation_rows(inbox, obj)
            title.update(f"Conversation with {obj.name} (#{obj.id})   .   {len(rows)} message(s)")
            self._fill_table(table, rows)
        else:
            gtoken = await self.guard(self.api.group_token, obj.pubkey, obj.privkey)
            data = await self.guard(self.api.group_messages, gtoken) if gtoken else []
            data = data or []
            rows = []
            for m in data:
                rows.append((str(m.time), f"{m.src_name} (#{m.src_id})", self._decrypt(obj.privkey, m.message)))
            title.update(f"Group: {obj.name} (#{obj.id})   .   {len(rows)} message(s)")
            self._fill_table(table, rows)

    def _conversation_rows(self, inbox, peer) -> list[tuple[str, str, str]]:
        """Build an ordered conversation with `peer` from our inbox (dst=me).

        Incoming: rows whose sender is the peer. Outgoing: our self-copies
        (SENT_MARKER) tagged with the peer id.
        """
        rows = []
        for m in inbox:
            body = self._decrypt(self.state["privkey"], m.message)
            if body.startswith(SENT_MARKER):
                try:
                    peer_id_str, text = body[len(SENT_MARKER) :].split("\x00", 1)
                    if int(peer_id_str) == peer.id:
                        rows.append((str(m.time), "you", text))
                except ValueError:
                    continue
            elif m.src_id == peer.id:
                rows.append((str(m.time), f"{m.src_name} (#{m.src_id})", body))
        rows.sort(key=lambda r: r[0])
        return rows

    @staticmethod
    def _decrypt(privkey: str, ciphertext: str) -> str:
        try:
            return crypto.decrypt_with(privkey, ciphertext).decode(errors="replace")
        except Exception:
            return "<undecryptable>"

    @staticmethod
    def _fill_table(table: DataTable, rows):
        table.clear()
        if not rows:
            table.add_row("", "", "(no messages yet)")
            return
        for time_s, who, text in rows:
            table.add_row(time_s, who, text)

    # --- actions (footer keys) ------------------------------------------

    def action_refresh(self):
        self.run_worker(self._load_lists())

    def action_send(self):
        self.run_worker(self._send())

    def action_new_group(self):
        self.run_worker(self._new_group())

    def action_invite(self):
        self.run_worker(self._invite())

    async def _send(self):
        kind, obj = self.current
        if kind is None:
            self.notify("Select a conversation first.", severity="warning")
            return
        if kind == "dm":
            text = await self.push_screen_wait(PromptScreen(f"Message to {obj.name}:"))
            if not text:
                return
            # copy to the recipient, then a self-copy tagged with the peer id
            if (
                await self.guard(self.api.send_dm, self.token, obj.id, crypto.encrypt_for(obj.pubkey, text.encode()))
                is None
            ):
                return
            tagged = f"{SENT_MARKER}{obj.id}\x00{text}".encode()
            await self.guard(
                self.api.send_dm, self.token, self.state["uid"], crypto.encrypt_for(self.state["pubkey"], tagged)
            )
        else:
            text = await self.push_screen_wait(PromptScreen(f"Message to {obj.name}:"))
            if not text:
                return
            if (
                await self.guard(self.api.send_group, self.token, obj.id, crypto.encrypt_for(obj.pubkey, text.encode()))
                is None
            ):
                return
        self.notify("Sent.")
        await self._load_current()

    async def _new_group(self):
        name = await self.push_screen_wait(PromptScreen("New group name:"))
        if not name:
            return
        group = await self.guard(self.api.create_group, self.token, name)
        if group is None:
            return
        self.notify(f"Created group {name} (#{group.id}).")
        self._active_key = f"g:{group.id}"
        await self._load_lists()

    async def _invite(self):
        kind, obj = self.current
        if kind != "group":
            self.notify("Select a group first to invite someone.", severity="warning")
            return
        users = await self.guard(self.api.get_users)
        if users is None:
            return
        pick = await self.push_screen_wait(
            PickScreen(f"Invite to {obj.name}:", [(u.id, f"{u.name} (#{u.id})") for u in users])
        )
        if pick is None:
            return
        if await self.guard(self.api.invite, self.token, obj.id, pick) is None:
            return
        self.notify("Invited.")


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_HOST
    NoiseApp(host).run()


if __name__ == "__main__":
    main()
