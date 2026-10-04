#!/usr/bin/env python3
"""Full-screen terminal client for the Cairn Flight Plan Exchange HTTP API."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from typing import Any, Optional

import httpx
from rich.syntax import Syntax
from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Container, Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Static, TextArea

from flightplan_api import ApiError, FlightPlanClient, default_url


TAGLINE = "AIRAC coordination, route filing, dispatch release, and station briefing workspace."
SAMPLE_RELEASE = "CFX1204 KMSP-KBOS FL370\nDCT DLL J34 ALB DCT\nALT KBDL / FUEL 17300"
BRIEF_BG = "#05090e"

# Design tokens for the dark terminal theme. Widget CSS needs its own copy,
# so every stylesheet below starts with these.
TOKENS = """
$ink: #e6edf3;
$muted: #8b98a5;
$line: #2a3644;
$paper: #161f2a;
$runway: #0b1219;
$signal: #149a92;
$amber: #e5a640;
$danger: #e06c60;
$slate: #4a5a6e;
$page: #0e151d;
$lead: #b6c2cf;
$fieldink: #a9b6c2;
$inputline: #3a4a5a;
$tagink: #a9b6c2;
$tagline: #3a4a5a;
$tagbg: #1c2632;
$notebg: #2a2410;
$noteline: #4a3d1a;
$noteink: #e8d9a8;
$errbg: #2a1512;
$errline: #4a2420;
$briefbg: #05090e;
$briefink: #dce8ef;
$briefline: #22303e;
$brieflabel: #7d8f9e;
$navink: #e6edf3;
$amberline: #e5a640;
$chrome: #1a2430;
$footerink: #7d8f9e;

$footer-item-background: $chrome;
$footer-key-background: $signal;
$footer-key-foreground: #06201e;
$footer-description-foreground: $lead;
$footer-description-background: $chrome;

$input-cursor-background: $signal;
$input-cursor-foreground: #06201e;
$input-selection-background: $signal;
$input-selection-foreground: #06201e;
"""

PORTAL_CSS = TOKENS + """
Screen {
    background: $page;
    color: $ink;
    align-horizontal: center;
}

#wrap {
    width: 100%;
    max-width: 112;
    height: 1fr;
    padding: 1 2;
}

VerticalScroll {
    scrollbar-color: $muted;
    scrollbar-background: $page;
    scrollbar-color-active: $signal;
    scrollbar-color-hover: $signal;
    scrollbar-corner-color: $page;
}

#body {
    height: auto;
    width: 100%;
}

#banner {
    display: none;
    margin-bottom: 1;
}

.h1 {
    color: $ink;
    text-style: bold;
    margin-bottom: 1;
    width: 100%;
}

.h2 {
    color: $ink;
    text-style: bold;
    margin-bottom: 1;
    width: 100%;
}

.h3 {
    color: $ink;
    text-style: bold;
    margin-bottom: 1;
    width: 100%;
}

.lead {
    color: $lead;
    margin-bottom: 1;
    width: 100%;
}

.label {
    color: $muted;
    text-style: bold;
    height: 1;
    width: 100%;
}

.value {
    color: $ink;
    text-style: bold;
    height: auto;
    width: 100%;
}

.strip {
    layout: grid;
    grid-size: 4;
    grid-gutter: 1;
    background: $line;
    height: auto;
    margin-bottom: 1;
}

.stat {
    layout: vertical;
    height: auto;
    background: $paper;
    padding: 0 1;
}

.panel {
    background: $paper;
    border: solid $line;
    height: auto;
    padding: 1 2;
    margin-bottom: 1;
}

.card {
    background: $paper;
    border: solid $line;
    height: auto;
    padding: 1 2;
    margin-bottom: 1;
}

.formbox {
    background: $paper;
    border: solid $line;
    height: auto;
    padding: 1 2;
    margin-bottom: 1;
}

.grid {
    layout: grid;
    grid-size: 3;
    grid-gutter: 1;
    height: auto;
    margin-bottom: 1;
}

.row {
    layout: grid;
    grid-size: 2;
    grid-gutter: 1;
    height: auto;
}

.plans {
    layout: grid;
    grid-size: 3;
    grid-gutter: 1;
    height: auto;
}

.field {
    layout: vertical;
    height: auto;
    margin-bottom: 1;
}

.fieldlabel {
    color: $fieldink;
    text-style: bold;
    height: 1;
}

Input {
    background: $paper;
    color: $ink;
    border: solid $inputline;
    height: 3;
}

Input:focus {
    border: tall $signal;
}

Input > .input--cursor {
    background: $signal;
    color: $paper;
}

Input > .input--placeholder, Input > .input--suggestion {
    color: $muted;
}

TextArea {
    background: $paper;
    color: $ink;
    border: solid $inputline;
    height: 7;
}

TextArea:focus {
    border: tall $signal;
}

TextArea > .text-area--cursor {
    background: $signal;
    color: $paper;
}

.btn {
    background: $signal;
    color: $paper;
    text-style: bold;
    border: none;
    height: 3;
    min-width: 16;
    margin-right: 1;
}

.btn.secondary {
    background: $slate;
}

.btn.warn {
    background: $amber;
}

.btn:hover {
    text-style: bold underline;
}

Button.navlink {
    width: auto;
    min-width: 0;
    height: 3;
    border: none;
    background: transparent;
    color: $navink;
    text-style: none;
    padding: 0 1;
}

Button.navlink:hover {
    background: #33465a;
    color: $paper;
}

.actions {
    height: auto;
    margin-bottom: 1;
}

.card .actions {
    margin: 1 0 0 0;
}

.meta {
    height: auto;
    margin-top: 1;
}

.tag {
    background: $tagbg;
    color: $tagink;
    border: round $tagline;
    padding: 0 1;
    margin-right: 1;
    height: 3;
}

.route {
    color: $ink;
    height: 1;
    text-overflow: ellipsis;
}

.note {
    background: $notebg;
    border: solid $noteline;
    color: $noteink;
    height: auto;
    padding: 1 2;
}

.error {
    background: $errbg;
    border: solid $errline;
    color: $danger;
    height: auto;
    padding: 1 2;
}

.brief {
    background: $briefbg;
    border: solid $briefline;
    color: $briefink;
    height: auto;
    padding: 1 2;
    margin-bottom: 1;
}

.brief .label {
    color: $brieflabel;
}

.brief Static {
    height: auto;
}

.hero {
    layout: grid;
    grid-size: 2;
    grid-gutter: 1;
    height: auto;
}

.hero > * {
    height: auto;
}
"""


# CSS has no auto-fill grid, so each grid class declares its column budget here:
# (most columns, narrowest column) in cells.
GRID_COLUMNS = {
    "strip": (4, 12),
    "grid": (3, 20),
    "row": (2, 28),
    "plans": (3, 32),
    "hero": (2, 44),
}


def stat(label: str, value: str, value_id: Optional[str] = None) -> Container:
    """One cell of a `.strip`: a small uppercase label above a bold value."""
    return Container(
        Label(label.upper(), classes="label"),
        Label(value, classes="value", id=value_id),
        classes="stat",
    )


def strip(*cells: tuple[str, str, Optional[str]]) -> Grid:
    return Grid(*[stat(*cell) for cell in cells], classes="strip")


def field(label: str, *widgets: Any) -> Container:
    return Container(Label(label.upper(), classes="fieldlabel"), *widgets, classes="field")


def tag(text: str) -> Label:
    return Label(text, classes="tag")


class FieldInput(Input):
    """Text input that puts the caret in the field instead of selecting its contents."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("select_on_focus", False)
        super().__init__(*args, **kwargs)


class PortalHeader(Horizontal):
    """Dark masthead: brand on the left, session nav on the right."""

    DEFAULT_CSS = TOKENS + """
    PortalHeader {
        dock: top;
        width: 100%;
        height: 3;
        background: $runway;
        color: $navink;
        border-bottom: heavy $amberline;
    }

    .brand {
        width: 1fr;
        height: 100%;
        padding: 0 2;
        text-style: bold;
        content-align: left middle;
    }

    #nav {
        width: auto;
        height: 100%;
        align-horizontal: right;
    }

    .whoami {
        width: auto;
        height: 100%;
        padding: 0 1;
        color: $navink;
        content-align: right middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label(self.app.portal_name.upper(), classes="brand")
        yield Horizontal(id="nav")

    def on_mount(self) -> None:
        self.refresh_nav()

    def refresh_nav(self) -> None:
        # Queried rather than query_one: a screen on its way out no longer has
        # its nav container, and that must not break the refresh.
        for nav in self.query("#nav"):
            nav.remove_children()
            nav.mount(*self.nav_links())

    def nav_links(self) -> list[Any]:
        if self.app.client.logged_in:
            return [
                Label(self.app.client.operator["username"], classes="whoami"),
                Button("Dashboard", action="app.open_dashboard", classes="navlink"),
                Button("Log out", action="app.log_out", classes="navlink"),
            ]
        return [
            Button("Log in", action="app.open_login", classes="navlink"),
            Button("Register", action="app.open_register", classes="navlink"),
        ]


class PortalFooter(Static):
    """Muted page footer, as in the original layout."""

    DEFAULT_CSS = TOKENS + """
    PortalFooter {
        dock: bottom;
        width: 100%;
        height: 1;
        background: $page;
        color: $footerink;
        padding: 0 2;
    }
    """

    def render(self) -> str:
        return f"{self.app.portal_tagline}   {self.app.client.base_url}"


class PortalScreen(Screen):
    """Base screen: portal chrome around a page body."""

    def compose(self) -> ComposeResult:
        yield PortalHeader()
        with VerticalScroll(id="wrap"):
            yield Static("", id="banner", classes="error")
            with Container(id="body"):
                yield from self.compose_body()
        yield PortalFooter()
        yield Footer()

    def compose_body(self) -> ComposeResult:
        raise NotImplementedError

    def on_mount(self) -> None:
        focused = next(iter(self.query("Input, TextArea")), None)
        if focused is None and not self.app.client.logged_in:
            focused = next(iter(self.query(Button)), None)
        if focused is not None:
            focused.focus()

    def on_resize(self, event: events.Resize) -> None:
        for name, (most_columns, narrowest) in GRID_COLUMNS.items():
            columns = max(1, min(most_columns, event.size.width // narrowest))
            for grid in self.query(f".{name}"):
                grid.styles.grid_size_columns = columns

    def set_error(self, message: str) -> None:
        banner = self.query_one("#banner", Static)
        banner.update(message)
        banner.display = bool(message)

    def api_problem(self, error: Exception) -> str:
        if isinstance(error, ApiError):
            return error.detail
        return f"{self.app.client.base_url} unreachable: {error}"


class HomeScreen(PortalScreen):
    """Portal landing page: operations pitch plus the station briefing sample."""

    def compose_body(self) -> ComposeResult:
        with Grid(classes="hero"):
            with Container(classes="hero-main"):
                yield Label("Flight plan filing for dispatch desks that move fast.", classes="h1")
                yield Label(
                    "Build route releases, protect crew remarks, and publish station-ready "
                    "briefings from a single operational board.",
                    classes="lead",
                )
                yield strip(
                    ("Cycle", self.app.airac.get("cycle", "2606"), None),
                    ("Tracks", "NAT / PAC", None),
                    ("Release", "Ops", None),
                    ("Status", "Open", None),
                )
                with Horizontal(classes="actions"):
                    if self.app.client.logged_in:
                        yield Button("Open dashboard", action="app.open_dashboard", classes="btn")
                    else:
                        yield Button("Create account", action="app.open_register", classes="btn")
                        yield Button("Log in", action="app.open_login", classes="btn secondary")
            with Container(classes="panel"):
                yield Label("Station Briefing", classes="h2")
                yield Label(
                    "Public station packets expose only dispatch-safe routing data. Crew notes "
                    "remain available to the filing operator after login.",
                    classes="lead",
                )
                with Container(classes="brief"):
                    yield Label("Sample release", classes="label")
                    yield Static(SAMPLE_RELEASE)

    def on_mount(self) -> None:
        super().on_mount()
        if self.app.portal_error:
            self.set_error(self.app.portal_error)


class LoginScreen(PortalScreen):
    """Operator sign-in form."""

    BINDINGS = [("escape", "app.go_back", "Back")]

    def __init__(self, username: str = "") -> None:
        super().__init__()
        self.username = username

    def compose_body(self) -> ComposeResult:
        with Container(classes="formbox"):
            yield Label("Operator Login", classes="h2")
            yield field("Username", FieldInput(value=self.username, id="username"))
            yield field("Password", FieldInput(password=True, id="password"))
            with Horizontal(classes="actions"):
                yield Button("Log in", action="screen.submit", classes="btn")

    @on(Input.Submitted)
    async def submit(self) -> None:
        await self.action_submit()

    async def action_submit(self) -> None:
        username = self.query_one("#username", Input).value.strip()
        password = self.query_one("#password", Input).value
        if not username or not password:
            self.set_error("Enter an operator ID and password.")
            return
        try:
            await self.app.client.login(username, password)
        except (ApiError, httpx.HTTPError) as error:
            self.set_error(
                "Invalid operator credentials."
                if isinstance(error, ApiError) and error.status_code == 403
                else self.api_problem(error)
            )
            return
        self.app.refresh_chrome()
        # Not awaited: this handler runs inside this screen's own message pump,
        # and awaiting the switch would wait for a teardown that cannot finish
        # until the handler returns.
        self.app.switch_screen(DashboardScreen())


class RegisterScreen(PortalScreen):
    """Dispatch operator registration form."""

    BINDINGS = [("escape", "app.go_back", "Back")]

    def compose_body(self) -> ComposeResult:
        with Container(classes="formbox"):
            yield Label("Register Dispatch Operator", classes="h2")
            with Grid(classes="row"):
                yield field("Username", FieldInput(id="username"))
                yield field("Home base", FieldInput(value="KMSP", id="home_base"))
            yield field("Full name", FieldInput(id="full_name"))
            yield field("Password", FieldInput(password=True, id="password"))
            with Horizontal(classes="actions"):
                yield Button("Register", action="screen.submit", classes="btn")

    @on(Input.Submitted)
    async def submit(self) -> None:
        await self.action_submit()

    async def action_submit(self) -> None:
        values = {
            "username": self.query_one("#username", Input).value.strip(),
            "password": self.query_one("#password", Input).value,
            "full_name": self.query_one("#full_name", Input).value.strip(),
            "home_base": self.query_one("#home_base", Input).value.strip(),
        }
        if not values["username"] or not values["full_name"]:
            self.set_error("An operator ID and a full name are required.")
            return
        if len(values["password"]) < 8:
            self.set_error("Pick a password of at least 8 characters.")
            return
        try:
            await self.app.client.register(**values)
        except (ApiError, httpx.HTTPError) as error:
            self.set_error(
                "That operator ID is already assigned."
                if isinstance(error, ApiError) and error.status_code == 409
                else self.api_problem(error)
            )
            return
        # Not awaited: this handler runs inside this screen's own message pump,
        # and awaiting the switch would wait for a teardown that cannot finish
        # until the handler returns.
        self.app.switch_screen(LoginScreen(username=values["username"]))


class DashboardScreen(PortalScreen):
    """Operator board: filing form on top, filed plans underneath."""

    BINDINGS = [("escape", "app.go_back", "Back")]

    def compose_body(self) -> ComposeResult:
        operator = self.app.client.operator or {}
        with Grid(classes="grid"):
            yield stat("Operator", operator.get("full_name", ""), "operator-name")
            yield stat("Home Base", operator.get("home_base", ""), "home-base")
            yield stat("Plans", "…", "plan-count")
        with Container(classes="formbox"):
            yield Label("File Flight Plan", classes="h2")
            with Grid(classes="row"):
                yield field("Callsign", FieldInput(value=f"CFX{secrets.randbelow(899) + 100}", id="callsign"))
                yield field("Plan ID", FieldInput(placeholder="Auto assigned", id="ident"))
            with Grid(classes="row"):
                yield field("Departure", FieldInput(value="KMSP", id="departure"))
                yield field("Arrival", FieldInput(value="KBOS", id="arrival"))
            with Grid(classes="row"):
                yield field("Alternate", FieldInput(value="KBDL", id="alternate"))
                yield field("Cruise", FieldInput(value="FL370", id="cruise"))
            with Grid(classes="row"):
                yield field("Fuel kg", FieldInput(value="17400", type="number", id="fuel"))
                yield field("Passengers", FieldInput(value="82", type="number", id="passengers"))
            yield field("Route", FieldInput(value="DCT DLL J34 ALB DCT", id="route"))
            yield field(
                "Private crew remarks",
                TextArea(id="private_notes", placeholder="Crew-only remarks"),
            )
            with Horizontal(classes="actions"):
                yield Button("File plan", action="screen.submit", classes="btn")
        yield Label("Filed Plans", classes="h2")
        yield Grid(id="plans", classes="plans")

    async def on_screen_resume(self) -> None:
        await self.load_plans()

    async def load_plans(self) -> None:
        try:
            plans = await self.app.client.list_plans()
        except (ApiError, httpx.HTTPError) as error:
            self.set_error(
                "Your session expired, log in again."
                if isinstance(error, ApiError) and error.status_code == 401
                else self.api_problem(error)
            )
            return
        self.set_error("")
        self.query_one("#plan-count", Label).update(str(len(plans)))
        grid = self.query_one("#plans", Grid)
        grid.remove_children()
        if not plans:
            grid.mount(Static("No filed plans yet.", classes="note"))
            return
        grid.mount(*[self.plan_card(plan) for plan in plans])

    def plan_card(self, plan: dict) -> Container:
        ident = plan["ident"]
        return Container(
            Label(ident, classes="h3"),
            Static(f'{plan["departure"]} -> {plan["arrival"]} / {plan["route"]}', classes="route"),
            Horizontal(
                tag(plan["callsign"]),
                tag(plan["cruise"]),
                tag(f'{plan["fuel"]} kg'),
                classes="meta",
            ),
            Horizontal(
                Button("Open", action=f"app.open_plan('{ident}')", classes="btn secondary"),
                Button("Briefing", action=f"app.open_briefing('{ident}')", classes="btn warn"),
                classes="actions",
            ),
            classes="card",
        )

    @on(Input.Submitted)
    async def submit(self) -> None:
        await self.action_submit()

    async def action_submit(self) -> None:
        values = {
            key: self.query_one(f"#{key}", Input).value.strip()
            for key in (
                "callsign",
                "ident",
                "departure",
                "arrival",
                "alternate",
                "route",
                "cruise",
                "fuel",
                "passengers",
            )
        }
        for key in ("callsign", "departure", "arrival", "alternate", "route", "cruise", "fuel", "passengers"):
            if not values[key]:
                self.set_error(f"{key} is required to file a plan.")
                return
        values["private_notes"] = self.query_one("#private_notes", TextArea).text
        try:
            fuel = int(values["fuel"])
            passengers = int(values["passengers"])
        except ValueError:
            self.set_error("Fuel and passengers must be whole numbers.")
            return
        try:
            filed = await self.app.client.create_plan(
                ident=values["ident"],
                callsign=values["callsign"],
                departure=values["departure"],
                arrival=values["arrival"],
                alternate=values["alternate"],
                route=values["route"],
                cruise=values["cruise"],
                fuel=fuel,
                passengers=passengers,
                private_notes=values["private_notes"],
            )
        except (ApiError, httpx.HTTPError) as error:
            self.set_error(
                "That plan ID is already filed."
                if isinstance(error, ApiError) and error.status_code == 409
                else self.api_problem(error)
            )
            return
        self.app.push_screen(PlanScreen(filed["ident"]))


class PlanScreen(PortalScreen):
    """Dispatch release for a single filed plan."""

    BINDINGS = [("escape", "app.go_back", "Back")]

    def __init__(self, ident: str) -> None:
        super().__init__()
        self.ident = ident

    def compose_body(self) -> ComposeResult:
        with Container(classes="panel"):
            yield Label(f"{self.ident} Dispatch Release", classes="h2")
            yield strip(
                ("Callsign", "…", "callsign"),
                ("Route", "…", "leg"),
                ("Cruise", "…", "cruise"),
                ("Fuel", "…", "fuel"),
            )
            yield Label("Route", classes="h3")
            yield Static("…", id="route")
            yield Label("Private crew remarks", classes="h3")
            yield Static("…", id="remarks", classes="note")
            with Horizontal(classes="actions"):
                yield Button("Back", action="app.go_back", classes="btn secondary")
                yield Button("Public briefing", action=f"app.open_briefing('{self.ident}')", classes="btn warn")

    async def on_mount(self) -> None:
        super().on_mount()
        await self.load_plan()

    async def load_plan(self) -> None:
        try:
            packet = await self.app.client.briefing(self.ident)
            private = await self.app.client.private_plan(self.ident)
        except (ApiError, httpx.HTTPError) as error:
            self.set_error(self.api_problem(error))
            return
        self.set_error("")
        self.query_one("#callsign", Label).update(packet["callsign"])
        self.query_one("#leg", Label).update(f'{packet["departure"]}-{packet["arrival"]}')
        self.query_one("#cruise", Label).update(packet["cruise"])
        self.query_one("#fuel", Label).update(f'{packet["fuel"]} kg')
        self.query_one("#route", Static).update(packet["route"])
        remarks = private.get("private_notes", "")
        self.query_one("#remarks", Static).update(remarks or "No crew remarks filed.")


class BriefingScreen(PortalScreen):
    """Public station briefing packet for a plan."""

    BINDINGS = [("escape", "app.go_back", "Back")]

    def __init__(self, ident: str) -> None:
        super().__init__()
        self.ident = ident

    def compose_body(self) -> ComposeResult:
        with Container(classes="panel"):
            yield Label(f"Station Briefing {self.ident}", classes="h2")
            yield strip(
                ("Callsign", "…", "callsign"),
                ("From", "…", "departure"),
                ("To", "…", "arrival"),
                ("Alternate", "…", "alternate"),
            )
            yield Label("Filed route", classes="h3")
            yield Static("…", id="route")
            with Container(classes="brief"):
                yield Label("Packet reference", classes="label")
                yield Static("", id="packet")
            with Horizontal(classes="actions"):
                yield Button("Back", action="app.go_back", classes="btn secondary")

    async def on_mount(self) -> None:
        super().on_mount()
        await self.load_briefing()

    async def load_briefing(self) -> None:
        try:
            packet = await self.app.client.briefing(self.ident)
        except (ApiError, httpx.HTTPError) as error:
            self.set_error(self.api_problem(error))
            return
        self.set_error("")
        for key in ("callsign", "departure", "arrival", "alternate"):
            self.query_one(f"#{key}", Label).update(packet[key])
        self.query_one("#route", Static).update(packet["route"])
        self.query_one("#packet", Static).update(
            Syntax(
                json.dumps(packet, indent=2),
                "json",
                background_color=BRIEF_BG,
                indent_guides=False,
            )
        )


class FlightPlanApp(App):
    """Terminal client for the flight plan exchange."""

    CSS = PORTAL_CSS
    TITLE = "Cairn Flight Plan Exchange"
    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, client: FlightPlanClient) -> None:
        super().__init__()
        self.client = client
        self.portal_name = self.TITLE
        self.portal_tagline = TAGLINE
        self.portal_error = ""
        self.airac: dict = {}
        self.home_screen: Optional[HomeScreen] = None

    async def on_mount(self) -> None:
        await self.load_portal()
        self.home_screen = HomeScreen()
        await self.push_screen(self.home_screen)

    async def load_portal(self) -> None:
        try:
            self.airac = await self.client.airac()
        except (ApiError, httpx.HTTPError) as error:
            self.portal_error = f"airac feed unavailable: {error}"
        try:
            index = await self.client.index()
        except (ApiError, httpx.HTTPError) as error:
            if not self.portal_error:
                self.portal_error = f"{self.client.base_url} unavailable: {error}"
            return
        self.portal_name = index.get("service", self.portal_name)
        self.portal_tagline = index.get("description", self.portal_tagline)

    def refresh_chrome(self) -> None:
        for screen in self.screen_stack:
            for header in screen.query(PortalHeader):
                header.refresh_nav()

    def action_go_back(self) -> None:
        if len(self.screen_stack) > 1 and self.screen is not self.home_screen:
            self.pop_screen()

    def action_open_dashboard(self) -> None:
        self.push_screen(DashboardScreen())

    def action_open_login(self) -> None:
        self.push_screen(LoginScreen())

    def action_open_register(self) -> None:
        self.push_screen(RegisterScreen())

    def action_open_plan(self, ident: str) -> None:
        self.push_screen(PlanScreen(ident))

    def action_open_briefing(self, ident: str) -> None:
        self.push_screen(BriefingScreen(ident))

    async def action_log_out(self) -> None:
        try:
            await self.client.logout()
        except (ApiError, httpx.HTTPError) as error:
            self.notify(str(error), title="Log out failed", severity="error")
            return
        self.refresh_chrome()
        while len(self.screen_stack) > 1 and self.screen is not self.home_screen:
            self.pop_screen()
        for screen in self.screen_stack:
            clear_error = getattr(screen, "set_error", None)
            if callable(clear_error):
                clear_error("")


def check_service(url: str, timeout: float) -> bool:
    """Return True when the service answers a request for its portal index."""
    try:
        response = httpx.get(url, timeout=timeout, trust_env=False)
    except httpx.HTTPError as error:
        print(f"cannot connect to {url}: {error}", file=sys.stderr)
        return False
    if response.status_code >= 400:
        print(f"cannot connect to {url}: HTTP {response.status_code}", file=sys.stderr)
        return False
    return True


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="flightplan", description="Full-screen terminal client for the flight plan API."
    )
    parser.add_argument("--url", help="base URL of the service (default $FLIGHTPLAN_URL or http://localhost:4729)")
    parser.add_argument("--host", default="localhost", help="service host when --url is not given")
    parser.add_argument("--port", type=int, default=4729, help="service port when --url is not given")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout in seconds")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log every API request and response to stdout on exit"
    )
    args = parser.parse_args(argv)
    url = args.url or f"http://{args.host}:{args.port}"
    if not check_service(url, args.timeout):
        return 1
    client = FlightPlanClient(url, timeout=args.timeout, verbose=args.verbose)
    app = FlightPlanApp(client)
    try:
        app.run()
    finally:
        if args.verbose:
            for entry in client.log:
                print(entry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
