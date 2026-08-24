#!/usr/bin/env python3
"""
Twitch CLI Player - enhanced single-file version.

Implements the recommended improvements except splitting into modules.
Includes a local HLS proxy that filters mid-roll ad injections by rotating
playback-access tokens across player types.
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import parse_qs, quote, urlparse

__version__ = "3.1.0"

# ---------------------------------------------------------------------------
# Required / optional dependencies
# ---------------------------------------------------------------------------
try:
    import requests
except ImportError:
    print("\033[31mError: requests library required. Install with: pip install requests\033[0m")
    sys.exit(1)

try:
    import qrcode
    HAS_QRCODE = True
except Exception:
    qrcode = None
    HAS_QRCODE = False

try:
    import keyring
    HAS_KEYRING = True
except Exception:
    keyring = None
    HAS_KEYRING = False

RICH_AVAILABLE = False
console = None

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.markup import escape as rich_escape

    console = Console()
    RICH_AVAILABLE = True
except Exception:
    Console = None
    Panel = None
    Table = None

    def rich_escape(value: Any) -> str:
        return str(value)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GQL_CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
OAUTH_CLIENT_ID = "l2wx7tow5m77hvmg883p3a985618os"
OAUTH_SCOPES = "chat:read chat:edit user:read:follows"
REDIRECT_URI = "http://localhost"

GQL_URL = "https://gql.twitch.tv/gql"
GQL_HEADERS = {
    "Client-ID": GQL_CLIENT_ID,
    "Content-Type": "application/json",
    "Referer": "https://www.twitch.tv/",
}

ANDROID_USER_AGENT = "Twitch/14.9.1 (Linux; U; Android 13; en) ExoPlayer"
DEFAULT_PLAYER = "mpv"

REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

TOKEN_ENV_VAR = "TWITCH_TOKEN"
CONFIG_ENV_VAR = "TWITCH_CLI_CONFIG"
KEYRING_ENV_VAR = "TWITCH_CLI_KEYRING"

KEYRING_SERVICE = "twitch-cli"
KEYRING_ACCOUNT = "oauth_token"

AVAILABLE_PLAYERS: Dict[str, str] = {
    "mpv": "Lightweight media player",
    "vlc": "Cross-platform media player",
    "flatpak-vlc": "VLC via Flatpak",
    "ffplay": "FFplay-based player",
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "player": DEFAULT_PLAYER,
    "custom_player": None,
    "audio_only": False,
    "low_latency": False,
    "cache": False,
    "quality": None,
    "use_keyring": False,
    "page_size": 20,
    "no_rich": False,
    "debug": False,
    "log_file": None,
    "adblock": True,
}

UI_WIDTH = 58

# --- Ad blocking ----------------------------------------------------------
HLS_MIME = "application/vnd.apple.mpegurl"

# Token flavors tried when the current one serves ads. Order matters:
# the first entry is the default used for direct (non-proxied) playback.
AD_FREE_PARAM_SETS: List[Dict[str, str]] = [
    {"platform": "android", "playerBackend": "mediaplayer", "playerType": "mobile"},
    {"platform": "web", "playerBackend": "mediaplayer", "playerType": "frontpage"},
    {"platform": "web", "playerBackend": "mediaplayer", "playerType": "embed"},
    {"platform": "ios", "playerBackend": "mediaplayer", "playerType": "ios"},
    {"platform": "web", "playerBackend": "mediaplayer", "playerType": "site"},
]

AD_MARKERS: Tuple[str, ...] = (
    "twitch-stitched-ad",
    "stitched-ad",
    "EXT-X-SCTE35",
    "stitchedad",
)

log = logging.getLogger("twitch-cli")


# ---------------------------------------------------------------------------
# Terminal colors
# ---------------------------------------------------------------------------
class C:
    R = "\033[0m"
    B = "\033[1m"
    D = "\033[2m"

    RED = "\033[38;5;196m"
    PURPLE = "\033[38;5;91m"
    PINK = "\033[38;5;207m"
    ORANGE = "\033[38;5;214m"
    GREEN = "\033[38;5;84m"
    YELLOW = "\033[38;5;220m"
    BLUE = "\033[38;5;75m"
    WHITE = "\033[38;5;255m"
    GRAY = "\033[38;5;245m"


COLOR_ENABLED = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(text: Any, color: str) -> str:
    text = str(text)
    if not COLOR_ENABLED:
        return text
    return f"{color}{text}{C.R}"


# ---------------------------------------------------------------------------
# Rich / ANSI UI helpers
# ---------------------------------------------------------------------------
USE_RICH = False


def set_rich_enabled(enabled: bool) -> None:
    global USE_RICH
    USE_RICH = bool(enabled and RICH_AVAILABLE)


def rich_enabled() -> bool:
    return bool(USE_RICH and RICH_AVAILABLE and console is not None)


def hr() -> str:
    return c("─" * UI_WIDTH, C.GRAY)


def title_bar(title: str, subtitle: Optional[str] = None) -> None:
    line_len = max(6, UI_WIDTH - len(title) - 6)

    print()
    print(f"  {c('╭─', C.PURPLE)} {c(title, C.B)} {c('─' * line_len, C.PURPLE)}")

    if subtitle:
        print(f"  {c('│', C.PURPLE)}  {c(subtitle, C.GRAY)}")

    print(f"  {c('╰─', C.PURPLE)}{c('─' * (UI_WIDTH - 2), C.PURPLE)}")
    print()


def ui_banner() -> None:
    if rich_enabled():
        console.print(
            Panel.fit(
                "[bold]Twitch CLI[/]\n"
                "[dim]Ad-free streaming · OAuth · Android player impersonation[/]",
                title="Twitch CLI",
                border_style="magenta",
            )
        )
        console.print()
    else:
        title_bar(
            "Twitch CLI",
            "Ad-free streaming · OAuth · Android player impersonation",
        )


def ui_section(title: str) -> None:
    if rich_enabled():
        console.rule(f"[bold]{rich_escape(title)}[/]")
    else:
        print()
        print(f"  {c(title, C.B)}")
        print(f"  {hr()}")


def ui_ok(message: Any) -> None:
    if rich_enabled():
        console.print(f"[green]✔[/] {rich_escape(message)}")
    else:
        print(f"  {c('✔', C.GREEN)} {message}")


def ui_warn(message: Any) -> None:
    if rich_enabled():
        console.print(f"[yellow]▲[/] {rich_escape(message)}")
    else:
        print(f"  {c('▲', C.YELLOW)} {message}")


def ui_err(message: Any) -> None:
    if rich_enabled():
        console.print(f"[red]✖[/] {rich_escape(message)}")
    else:
        print(f"  {c('✖', C.RED)} {message}")


def ui_note(message: Any) -> None:
    if rich_enabled():
        console.print(f"[blue]▸[/] {rich_escape(message)}")
    else:
        print(f"  {c('▸', C.BLUE)} {message}")


def ui_kv(key: Any, value: Any) -> None:
    if rich_enabled():
        console.print(f"[dim]{rich_escape(key)}[/] · {rich_escape(value)}")
    else:
        print(f"  {c(key, C.GRAY)} {c('·', C.D)} {value}")


def ui_table(headers: List[str], rows: List[List[Any]]) -> None:
    if rich_enabled():
        table = Table(show_header=True, header_style="bold")
        for header in headers:
            table.add_column(str(header))

        for row in rows:
            table.add_row(*[str(item) for item in row])

        console.print(table)
        return

    text_headers = [str(header) for header in headers]
    print("  " + " | ".join(text_headers))
    print("  " + c("-" * min(UI_WIDTH, max(30, len(" | ".join(text_headers)))), C.GRAY))

    for row in rows:
        print("  " + " | ".join(str(item) for item in row))


def ui_prompt(prompt: str, default: Optional[str] = None) -> Optional[str]:
    suffix = f" ({default})" if default else ""
    full_prompt = f"{prompt}{suffix}:"

    try:
        if rich_enabled():
            raw = console.input(f"{rich_escape(full_prompt)} ").strip()
        else:
            raw = input(f"{full_prompt} ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if not raw and default is not None:
        return default

    return raw


@contextmanager
def ui_spinner(message: str):
    if rich_enabled():
        with console.status(f"[bold]{rich_escape(message)}[/]"):
            yield
    else:
        ui_note(message)
        yield


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def format_uptime(started_at: Optional[str]) -> str:
    started = parse_iso_timestamp(started_at)
    if not started:
        return ""

    now = datetime.now(timezone.utc)
    delta = now - started

    if delta.total_seconds() < 0:
        return "live"

    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m"

    if minutes:
        return f"{minutes}m"

    return "<1m"


def format_date(value: Optional[str]) -> str:
    dt = parse_iso_timestamp(value)
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%d")


def format_viewers(value: Any) -> str:
    try:
        return f"{int(value or 0):,}"
    except Exception:
        return str(value)


def parse_twitch_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    parsed = urlparse(url)
    netloc = (parsed.netloc or "").lower()

    if "clips.twitch.tv" in netloc:
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if parts:
            return "clip", parts[0]
        return None, None

    if "twitch.tv" not in netloc:
        return None, None

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if not parts:
        return None, None

    if parts[0] == "videos" and len(parts) >= 2:
        return "vod", parts[1]

    if len(parts) >= 3 and parts[1] == "clip":
        return "clip", parts[2]

    if parts[0] and parts[0] != "videos":
        return "channel", parts[0]

    return None, None


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class Options:
    player: str = DEFAULT_PLAYER
    custom_player: Optional[str] = None
    token: Optional[str] = None
    use_keyring: bool = False
    audio_only: bool = False
    low_latency: bool = False
    cache: bool = False
    quality: Optional[str] = None
    debug: bool = False
    page_size: int = 20
    force_login: bool = False
    adblock: bool = True


@dataclass
class Game:
    id: str
    name: str

    @classmethod
    def from_helix(cls, item: Dict[str, Any]) -> "Game":
        return cls(
            id=str(item.get("id", "")),
            name=str(item.get("name", "Unknown")),
        )


@dataclass
class Stream:
    user_id: str
    user_login: str
    user_name: str
    game_name: str
    viewer_count: int
    started_at: Optional[str]
    title: str

    @classmethod
    def from_helix(cls, item: Dict[str, Any]) -> "Stream":
        return cls(
            user_id=str(item.get("user_id", "")),
            user_login=str(item.get("user_login", "")),
            user_name=str(item.get("user_name", "Unknown")),
            game_name=str(item.get("game_name", "N/A")),
            viewer_count=int(item.get("viewer_count", 0) or 0),
            started_at=item.get("started_at"),
            title=str(item.get("title", "")),
        )


@dataclass
class Vod:
    id: str
    title: str
    channel: str
    display_name: str
    duration: str
    view_count: int
    created_at: Optional[str]

    @classmethod
    def from_helix(cls, item: Dict[str, Any]) -> "Vod":
        return cls(
            id=str(item.get("id", "")),
            title=str(item.get("title", "VOD")),
            channel=str(item.get("user_login", "Unknown")),
            display_name=str(item.get("user_name", "Unknown")),
            duration=str(item.get("duration", "")),
            view_count=int(item.get("view_count", 0) or 0),
            created_at=item.get("created_at"),
        )

    @classmethod
    def from_gql(cls, item: Dict[str, Any]) -> "Vod":
        owner = item.get("owner") or {}
        return cls(
            id=str(item.get("id", "")),
            title=str(item.get("title", "VOD")),
            channel=str(owner.get("login", "Unknown")),
            display_name=str(owner.get("displayName", "Unknown")),
            duration=str(item.get("duration", "")),
            view_count=int(item.get("viewCount", 0) or 0),
            created_at=item.get("createdAt"),
        )


@dataclass
class StreamInfo:
    online: bool
    user_id: Optional[str]
    login: str
    display_name: str
    title: Optional[str] = None
    game: Optional[str] = None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def get_config_path(custom_path: Optional[str] = None) -> Path:
    if custom_path:
        return Path(custom_path).expanduser()

    env_path = os.environ.get(CONFIG_ENV_VAR)
    if env_path:
        return Path(env_path).expanduser()

    return Path.home() / ".config" / "twitch-cli" / "config.json"


def load_config(custom_path: Optional[str] = None) -> Tuple[Dict[str, Any], Path]:
    path = get_config_path(custom_path)
    config = dict(DEFAULT_CONFIG)

    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config.update(loaded)
        except Exception as exc:
            print(f"Warning: could not load config file {path}: {exc}")

    return config, path


def write_default_config(custom_path: Optional[str] = None) -> Path:
    path = get_config_path(custom_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------
class TokenStorage:
    def __init__(self, use_keyring: bool = False):
        self.use_keyring = bool(use_keyring and HAS_KEYRING)
        self.token_file = Path.home() / ".config" / "twitch-cli" / "token"
        self.legacy_token_file = Path(__file__).resolve().parent / ".twitch_token"

    def _read_file_token(self, path: Path) -> Optional[str]:
        if not path.exists():
            return None

        try:
            token = path.read_text(encoding="utf-8").strip()
            return token or None
        except OSError:
            return None

    def get_token(self) -> Optional[str]:
        if self.use_keyring and HAS_KEYRING:
            try:
                token = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
                if token:
                    return token
            except Exception as exc:
                log.debug("Keyring get failed: %s", exc)

        token = self._read_file_token(self.token_file)
        if token:
            return token

        return self._read_file_token(self.legacy_token_file)

    def _save_file_token(self, token: str) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(token, encoding="utf-8")

        try:
            os.chmod(self.token_file, 0o600)
        except OSError:
            pass

    def save_token(self, token: str) -> None:
        if self.use_keyring and HAS_KEYRING:
            try:
                keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, token)
                return
            except Exception as exc:
                log.debug("Keyring save failed, falling back to file: %s", exc)

        self._save_file_token(token)

    def delete_token(self) -> None:
        if self.use_keyring and HAS_KEYRING:
            try:
                keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
            except Exception as exc:
                log.debug("Keyring delete failed: %s", exc)

        try:
            self.token_file.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

        try:
            self.legacy_token_file.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------
def generate_qr_code(url: str) -> Optional[str]:
    if not HAS_QRCODE:
        return None

    try:
        qr = qrcode.QRCode(version=1, box_size=1, border=1)
        qr.add_data(url)
        qr.make()
        return qr.print_ascii(tty=False)
    except Exception:
        return None


def get_oauth_token_interactive() -> Optional[str]:
    ui_section("Twitch OAuth Login")
    ui_note("Open the URL on your phone, approve, then paste the redirect URL.")

    auth_url = (
        "https://id.twitch.tv/oauth2/authorize"
        f"?client_id={OAUTH_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        "&response_type=token"
        f"&scope={OAUTH_SCOPES.replace(' ', '+')}"
    )

    ui_kv("URL", auth_url)

    qr_ascii = generate_qr_code(auth_url)
    if qr_ascii:
        print()
        for line in qr_ascii.splitlines():
            print(f"  {line}")

    print()

    redirect_url = ui_prompt("Paste redirect URL")
    if redirect_url is None:
        ui_warn("Login canceled")
        return None

    match = re.search(r"access_token=([^&]+)", redirect_url)
    if match:
        ui_ok("Got access token")
        return match.group(1)

    ui_err("Could not extract token from redirect URL")
    return None


# ---------------------------------------------------------------------------
# Twitch API client
# ---------------------------------------------------------------------------
class TwitchPlayer:
    def __init__(self, token: Optional[str] = None, use_keyring: bool = False):
        self.token_storage = TokenStorage(use_keyring=use_keyring)
        self.token = token or os.environ.get(TOKEN_ENV_VAR) or self.token_storage.get_token()
        self.session = requests.Session()
        self.session.headers.update(GQL_HEADERS)
        self.auth_user: Optional[str] = None
        self.auth_user_id: Optional[str] = None

    # -----------------------------------------------------------------------
    # Low-level request helpers
    # -----------------------------------------------------------------------
    def _request(self, method: str, url: str, retries: int = MAX_RETRIES, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        last_exc: Optional[Exception] = None

        for attempt in range(1, retries + 1):
            try:
                response = self.session.request(method, url, **kwargs)
                log.debug("HTTP %s %s -> %s", method, url, response.status_code)

                if response.status_code == 429 and attempt < retries:
                    retry_after = response.headers.get("Retry-After", "2")
                    try:
                        delay = int(retry_after)
                    except ValueError:
                        delay = 2

                    ui_warn(f"Rate limited. Retrying in {delay}s.")
                    time.sleep(delay)
                    continue

                if response.status_code in RETRYABLE_STATUS and attempt < retries:
                    delay = 2 ** attempt
                    ui_warn(f"HTTP {response.status_code}. Retrying in {delay}s.")
                    time.sleep(delay)
                    continue

                return response

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_exc = exc

                if attempt < retries:
                    delay = 2 ** attempt
                    ui_warn(f"Network error. Retrying in {delay}s.")
                    time.sleep(delay)
                    continue

                raise

        if last_exc:
            raise last_exc

        raise RuntimeError("Request failed")

    def _gql_post(self, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = self._request(
                "POST",
                GQL_URL,
                json={"query": query, "variables": variables},
            )
        except requests.exceptions.RequestException as exc:
            log.debug("GQL request failed: %s", exc)
            return {}

        if response.status_code != 200:
            log.debug("GQL HTTP %s", response.status_code)
            return {}

        try:
            return response.json()
        except ValueError:
            return {}

    def _helix_get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        if not self.token:
            return None

        try:
            response = self._request(
                "GET",
                f"https://api.twitch.tv/helix/{endpoint}",
                params=params,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Client-ID": OAUTH_CLIENT_ID,
                },
            )
        except requests.exceptions.RequestException as exc:
            ui_err(f"Helix request failed: {exc}")
            return None

        if response.status_code == 401:
            ui_err("OAuth token is invalid or expired.")
            return None

        if response.status_code != 200:
            details = response.text.strip().replace("\n", " ")[:180]
            ui_err(f"Helix error {response.status_code}: {details}")
            return None

        try:
            return response.json()
        except ValueError:
            return None

    # -----------------------------------------------------------------------
    # Auth
    # -----------------------------------------------------------------------
    def validate_token(self) -> Optional[Dict[str, Any]]:
        if not self.token:
            return None

        try:
            response = self._request(
                "GET",
                "https://id.twitch.tv/oauth2/validate",
                headers={"Authorization": f"OAuth {self.token}"},
            )
        except requests.exceptions.RequestException:
            return None

        if response.status_code != 200:
            return None

        try:
            data = response.json()
        except ValueError:
            return None

        self.auth_user = data.get("login") or data.get("user_name")
        self.auth_user_id = data.get("user_id")
        return data

    def ensure_auth(self, interactive: bool = True, show_status: bool = False) -> bool:
        if not self.token:
            if not interactive:
                return False

            self.token = get_oauth_token_interactive()
            if not self.token:
                return False

            self.token_storage.save_token(self.token)

        data = self.validate_token()

        if not data:
            ui_warn("OAuth token is invalid or expired.")
            self.token_storage.delete_token()
            self.token = None

            if not interactive:
                return False

            self.token = get_oauth_token_interactive()
            if not self.token:
                return False

            self.token_storage.save_token(self.token)

            data = self.validate_token()
            if not data:
                ui_err("New token failed validation.")
                return False

        self.session.headers["Authorization"] = f"OAuth {self.token}"

        if show_status:
            ui_ok(f"Logged in as {self.auth_user or 'unknown user'}")

        return True

    def get_user_id(self) -> Optional[str]:
        if self.auth_user_id:
            return self.auth_user_id

        data = self._helix_get("users")
        if data and data.get("data"):
            return str(data["data"][0].get("id"))

        return None

    # -----------------------------------------------------------------------
    # Stream / channel info
    # -----------------------------------------------------------------------
    def get_stream_info(self, channel_name: str) -> Optional[StreamInfo]:
        query = """
        query ChannelInfo($channelName: String!) {
            user(login: $channelName) {
                id
                login
                displayName
                stream {
                    id
                    title
                    game {
                        name
                    }
                }
            }
        }
        """

        result = self._gql_post(query, {"channelName": channel_name})
        user = (result.get("data") or {}).get("user")

        if not user:
            return None

        stream = user.get("stream")
        game = (stream or {}).get("game") or {}

        return StreamInfo(
            online=bool(stream),
            user_id=user.get("id"),
            login=str(user.get("login", channel_name)),
            display_name=str(user.get("displayName", channel_name)),
            title=stream.get("title") if stream else None,
            game=game.get("name") if stream and game else None,
        )

    def get_stream_playback_token(
        self,
        channel_name: str,
        params: Optional[Dict[str, str]] = None,
    ) -> Tuple[Optional[str], Optional[str]]:
        query = """
        query PlaybackAccessToken_Template($channelName: String!, $params: PlaybackAccessTokenParams!) {
            streamPlaybackAccessToken(channelName: $channelName, params: $params) {
                value
                signature
                __typename
            }
        }
        """

        variables = {
            "channelName": channel_name,
            "params": params or AD_FREE_PARAM_SETS[0],
        }

        result = self._gql_post(query, variables)
        token_data = (result.get("data") or {}).get("streamPlaybackAccessToken")

        if token_data:
            return token_data.get("value"), token_data.get("signature")

        return None, None

    @staticmethod
    def build_usher_url(channel_name: str, token: str, signature: str) -> str:
        return (
            f"https://usher.ttvnw.net/api/channel/hls/{channel_name}.m3u8"
            f"?token={quote(token, safe='')}"
            f"&sig={quote(signature, safe='')}"
            "&player=twitchweb"
            "&allow_audio_only=true"
            "&allow_source=true"
            "&playlist_include_framerate=true"
            "&type=any"
        )

    def get_stream_url(self, channel_name: str) -> Optional[str]:
        token, signature = self.get_stream_playback_token(channel_name)
        if not token or not signature:
            return None

        return self.build_usher_url(channel_name, token, signature)

    # -----------------------------------------------------------------------
    # VODs
    # -----------------------------------------------------------------------
    def get_vod_playback_token(self, vod_id: str) -> Tuple[Optional[str], Optional[str]]:
        query = """
        query PlaybackAccessToken_Template($id: ID!, $params: PlaybackAccessTokenParams!) {
            videoPlaybackAccessToken(id: $id, params: $params) {
                value
                signature
                __typename
            }
        }
        """

        variables = {
            "id": vod_id,
            "params": {
                "platform": "android",
                "playerBackend": "mediaplayer",
                "playerType": "mobile",
            },
        }

        result = self._gql_post(query, variables)
        token_data = (result.get("data") or {}).get("videoPlaybackAccessToken")

        if token_data:
            return token_data.get("value"), token_data.get("signature")

        return None, None

    def get_vod_info(self, vod_id: str) -> Optional[Vod]:
        query = """
        query VideoInfo($id: ID!) {
            video(id: $id) {
                id
                title
                createdAt
                duration
                viewCount
                owner {
                    displayName
                    login
                }
            }
        }
        """

        result = self._gql_post(query, {"id": vod_id})
        video = (result.get("data") or {}).get("video")

        if not video:
            return None

        return Vod.from_gql(video)

    def get_vod_url(self, vod_id: str) -> Optional[str]:
        token, signature = self.get_vod_playback_token(vod_id)
        if not token or not signature:
            return None

        return (
            f"https://usher.ttvnw.net/vod/{vod_id}.m3u8"
            "?player=twitchweb"
            f"&token={quote(token, safe='')}"
            f"&sig={quote(signature, safe='')}"
            "&allow_audio_only=true"
            "&allow_source=true"
            "&playlist_include_framerate=true"
            "&type=any"
        )

    def get_user_by_login(self, login: str) -> Optional[Dict[str, Any]]:
        data = self._helix_get("users", {"login": login})
        if data and data.get("data"):
            return data["data"][0]
        return None

    def get_videos(
        self,
        user_id: str,
        first: int = 20,
        after: Optional[str] = None,
    ) -> Tuple[List[Vod], Optional[str]]:
        params: Dict[str, Any] = {
            "user_id": user_id,
            "first": first,
            "type": "archive",
            "sort": "time",
        }

        if after:
            params["after"] = after

        data = self._helix_get("videos", params)
        if not data:
            return [], None

        vods = [Vod.from_helix(item) for item in data.get("data", [])]
        cursor = (data.get("pagination") or {}).get("cursor")
        return vods, cursor

    def get_latest_vod(self, user_id: str) -> Optional[Vod]:
        vods, _ = self.get_videos(user_id, first=1)
        return vods[0] if vods else None

    # -----------------------------------------------------------------------
    # Clips
    # -----------------------------------------------------------------------
    def get_clip_info(self, slug: str) -> Tuple[Optional[str], Optional[str]]:
        query = """
        query ClipInfo($slug: String!) {
            clip(slug: $slug) {
                title
                url
                videoQualities {
                    quality
                    sourceURL
                    frameRate
                }
            }
        }
        """

        result = self._gql_post(query, {"slug": slug})
        clip = (result.get("data") or {}).get("clip")

        if not clip:
            return None, None

        title = clip.get("title") or "Twitch Clip"
        qualities = clip.get("videoQualities") or []

        if qualities:
            def frame_rate(item: Dict[str, Any]) -> float:
                try:
                    return float(item.get("frameRate") or 0)
                except Exception:
                    return 0.0

            qualities = sorted(qualities, key=frame_rate, reverse=True)

            for quality in qualities:
                source = quality.get("sourceURL")
                if source:
                    return source, title

        return None, title

    # -----------------------------------------------------------------------
    # Helix discovery / browsing
    # -----------------------------------------------------------------------
    def get_top_games(self, first: int = 100) -> List[Game]:
        data = self._helix_get("games/top", {"first": first})
        if not data:
            return []

        return [Game.from_helix(item) for item in data.get("data", [])]

    def search_game(self, query: str) -> Optional[Game]:
        data = self._helix_get("search/categories", {"query": query, "first": 1})

        if data and data.get("data"):
            return Game.from_helix(data["data"][0])

        top_games = self.get_top_games(first=100)
        if not top_games:
            return None

        names = [game.name for game in top_games]
        matches = difflib.get_close_matches(query, names, n=1, cutoff=0.6)

        if matches:
            for game in top_games:
                if game.name == matches[0]:
                    return game

        return None

    def get_followed_live_streams(
        self,
        user_id: str,
        first: int = 20,
        after: Optional[str] = None,
    ) -> Tuple[List[Stream], Optional[str]]:
        params: Dict[str, Any] = {
            "user_id": user_id,
            "first": first,
        }

        if after:
            params["after"] = after

        data = self._helix_get("streams/followed", params)
        if not data:
            return [], None

        streams = [Stream.from_helix(item) for item in data.get("data", [])]
        cursor = (data.get("pagination") or {}).get("cursor")
        return streams, cursor

    def get_streams_by_game(
        self,
        game_id: str,
        first: int = 20,
        after: Optional[str] = None,
    ) -> Tuple[List[Stream], Optional[str]]:
        params: Dict[str, Any] = {
            "game_id": game_id,
            "first": first,
            "type": "live",
        }

        if after:
            params["after"] = after

        data = self._helix_get("streams", params)
        if not data:
            return [], None

        streams = [Stream.from_helix(item) for item in data.get("data", [])]
        cursor = (data.get("pagination") or {}).get("cursor")
        return streams, cursor

    def search_channels(self, query: str, first: int = 20) -> List[Dict[str, Any]]:
        data = self._helix_get("search/channels", {"query": query, "first": first})
        if not data:
            return []

        return data.get("data", [])


# ---------------------------------------------------------------------------
# Ad blocking: local HLS filtering proxy with token rotation
# ---------------------------------------------------------------------------
def playlist_has_ads(playlist_text: str) -> bool:
    return any(marker in playlist_text for marker in AD_MARKERS)


def _attr(line: str, name: str) -> str:
    match = re.search(rf'{name}="([^"]*)"', line)
    return match.group(1) if match else ""


@dataclass
class MasterVariant:
    attrs: str
    uri: str
    bandwidth: int
    video: str
    name: str
    height: int


def parse_master_variants(master: str) -> List[MasterVariant]:
    variants: List[MasterVariant] = []
    pending = ""

    for raw in master.splitlines():
        line = raw.strip()

        if line.startswith("#EXT-X-STREAM-INF:"):
            pending = line
        elif line and not line.startswith("#") and pending:
            bw = re.search(r"BANDWIDTH=(\d+)", pending)
            res = re.search(r"RESOLUTION=(\d+)x(\d+)", pending)
            variants.append(
                MasterVariant(
                    attrs=pending,
                    uri=line,
                    bandwidth=int(bw.group(1)) if bw else 0,
                    video=_attr(pending, "VIDEO"),
                    name=_attr(pending, "NAME"),
                    height=int(res.group(2)) if res else 0,
                )
            )
            pending = ""

    return variants


def is_audio_only_variant(variant: MasterVariant) -> bool:
    return variant.video.lower() == "audio_only" or "audio only" in variant.name.lower()


def best_variant(variants: List[MasterVariant]) -> Optional[MasterVariant]:
    pool = [v for v in variants if not is_audio_only_variant(v)] or variants
    return max(pool, key=lambda v: (v.video.lower() == "chunked", v.bandwidth))


def select_variant(
    variants: List[MasterVariant],
    quality: Optional[str],
) -> Optional[MasterVariant]:
    q = (quality or "").strip().lower()

    if q in {"audio", "audio_only", "audioonly"}:
        for v in variants:
            if is_audio_only_variant(v):
                return v
        return None

    if q in {"", "source", "max", "best", "chunked"}:
        return best_variant(variants)

    match = re.match(r"(\d+)p?(\d+)?$", q)
    if match:
        height, fps = match.group(1), match.group(2)
        exact = f"{height}p{fps}" if fps else None

        matches: List[MasterVariant] = []
        for v in variants:
            vid = v.video.lower()
            if exact and vid == exact:
                matches.append(v)
            elif vid == f"{height}p" or vid.startswith(f"{height}p") or str(v.height) == height:
                matches.append(v)

        if matches:
            return max(matches, key=lambda v: v.bandwidth)

    return best_variant(variants)


class HLSAdBlockProxy:
    """Local HLS proxy that hides Twitch mid-roll ad injections.

    The player talks to 127.0.0.1. The proxy serves a single-variant master
    for the requested quality (best/source by default), so the player cannot
    pick a lower rendition. Variant playlists are scanned for ad markers;
    when ads are found, tokens for other player types are tried, but a
    flavor is only used if it offers the SAME quality id at >= 70% of the
    requested bandwidth. If nothing matches, ads pass through unchanged
    rather than degrading quality.
    """

    ROTATE_COOLDOWN = 4.0
    MIN_BW_RATIO = 0.7

    def __init__(self, twitch: TwitchPlayer, channel: str, quality: Optional[str] = None):
        self.twitch = twitch
        self.channel = channel
        self.quality = quality
        self._lock = threading.Lock()
        self._tokens: Dict[int, Tuple[str, str]] = {}
        self._preset = 0
        self._preferred: Dict[str, str] = {}
        self._last_rotate = 0.0
        self._last_flavor: Optional[str] = None
        self._noted_quality: Optional[str] = None
        self._ad_warned = False
        self._server: Optional[ThreadingHTTPServer] = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> bool:
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:
                pass

            def do_GET(self) -> None:
                proxy.handle_request(self)

        Handler.protocol_version = "HTTP/1.1"

        try:
            self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        except OSError as exc:
            ui_warn(f"Could not start ad-block proxy: {exc}")
            return False

        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return True

    @property
    def port(self) -> int:
        return self._server.server_port if self._server else 0

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/master"

    # -- HTTP handling -----------------------------------------------------
    def handle_request(self, h: BaseHTTPRequestHandler) -> None:
        parsed = urlparse(h.path)
        qs = parse_qs(parsed.query)

        try:
            if parsed.path == "/master":
                code, body = self.build_master()
                ctype = HLS_MIME
            elif parsed.path == "/variant":
                upstream = (qs.get("u") or [""])[0]
                video_id = (qs.get("n") or [""])[0]
                try:
                    min_bw = int((qs.get("bw") or ["0"])[0])
                except ValueError:
                    min_bw = 0

                if not upstream:
                    code, ctype, body = 400, "text/plain", "bad request"
                else:
                    code, ctype, body = self.handle_variant(upstream, video_id, min_bw)
            else:
                code, ctype, body = 404, "text/plain", "not found"
        except Exception as exc:
            log.debug("adblock proxy error: %s", exc)
            code, ctype, body = 502, "text/plain", "proxy error"

        data = body.encode("utf-8", "replace")
        h.send_response(code)
        h.send_header("Content-Type", ctype)
        h.send_header("Content-Length", str(len(data)))
        h.send_header("Cache-Control", "no-store")
        h.end_headers()
        h.wfile.write(data)

    # -- playlist plumbing -------------------------------------------------
    def _fetch(self, url: str) -> Optional[str]:
        try:
            response = self.twitch.session.get(
                url,
                timeout=REQUEST_TIMEOUT,
                headers={
                    "User-Agent": ANDROID_USER_AGENT,
                    "Referer": "https://www.twitch.tv/",
                },
            )
            if response.status_code == 200:
                return response.text
            log.debug("adblock: HTTP %s for %s", response.status_code, url)
        except requests.exceptions.RequestException as exc:
            log.debug("adblock: fetch failed: %s", exc)
        return None

    def _master_url(self, preset: int) -> Optional[str]:
        with self._lock:
            cached = self._tokens.get(preset)

        if cached is None:
            token, signature = self.twitch.get_stream_playback_token(
                self.channel, params=AD_FREE_PARAM_SETS[preset]
            )
            if not token or not signature:
                return None
            cached = (token, signature)
            with self._lock:
                self._tokens[preset] = cached

        return TwitchPlayer.build_usher_url(self.channel, cached[0], cached[1])

    def _fetch_master(self, preset: int) -> Optional[str]:
        url = self._master_url(preset)
        if not url:
            return None

        master = self._fetch(url)
        return master if master and "#EXT-X-STREAM-INF" in master else None

    def build_master(self) -> Tuple[int, str]:
        # Always start from preset 0 (android/mobile) so the rendition list
        # matches what direct playback would give.
        for preset in range(len(AD_FREE_PARAM_SETS)):
            master = self._fetch_master(preset)
            if not master:
                continue

            variants = parse_master_variants(master)
            if not variants:
                continue

            chosen = select_variant(variants, self.quality)
            if not chosen:
                continue

            label = chosen.name or chosen.video
            if self._noted_quality != label:
                self._noted_quality = label
                ui_note(f"Ad-block: serving '{label}'")

            return 200, self._render_master(chosen)

        return 502, "could not fetch master playlist"

    def _render_master(self, variant: MasterVariant) -> str:
        video_id = variant.video or variant.name
        uri = (
            f"/variant?u={quote(variant.uri, safe='')}"
            f"&n={quote(video_id, safe='')}"
            f"&bw={variant.bandwidth}"
        )
        return "\n".join(["#EXTM3U", variant.attrs, uri]) + "\n"

    def handle_variant(
        self,
        upstream: str,
        video_id: str,
        min_bw: int,
    ) -> Tuple[int, str, str]:
        with self._lock:
            preferred = self._preferred.get(video_id)

        if preferred and preferred != upstream:
            text = self._fetch(preferred)
            if text is not None and not playlist_has_ads(text):
                return 200, HLS_MIME, text
            with self._lock:
                self._preferred.pop(video_id, None)

        text = self._fetch(upstream)
        if text is None:
            # Upstream URL may have expired; re-derive it from a fresh master.
            refreshed = self._refresh_variant(video_id, min_bw)
            if refreshed is not None:
                return 200, HLS_MIME, refreshed
            return 502, "text/plain", "upstream fetch failed"

        if not playlist_has_ads(text):
            with self._lock:
                self._preferred[video_id] = upstream
            return 200, HLS_MIME, text

        clean = self._rotate_for_clean(video_id, min_bw)
        if clean is not None:
            return 200, HLS_MIME, clean

        if not self._ad_warned:
            self._ad_warned = True
            ui_warn("Mid-roll ads detected; no same-quality ad-free flavor, passing through")

        return 200, HLS_MIME, text

    def _variant_from_master(
        self,
        variants: List[MasterVariant],
        video_id: str,
        min_bw: int,
    ) -> Optional[MasterVariant]:
        vid = (video_id or "").lower()

        candidates = [
            v for v in variants
            if v.video.lower() == vid and not is_audio_only_variant(v)
        ]

        if not candidates and not vid:
            candidates = [v for v in variants if not is_audio_only_variant(v)]

        if min_bw:
            floor = min_bw * self.MIN_BW_RATIO
            candidates = [v for v in candidates if v.bandwidth >= floor]

        if candidates:
            return max(candidates, key=lambda v: v.bandwidth)

        return None

    def _rotate_for_clean(self, video_id: str, min_bw: int) -> Optional[str]:
        now = time.monotonic()
        if now - self._last_rotate < self.ROTATE_COOLDOWN:
            return None
        self._last_rotate = now

        for offset in range(1, len(AD_FREE_PARAM_SETS) + 1):
            preset = (self._preset + offset) % len(AD_FREE_PARAM_SETS)
            master = self._fetch_master(preset)
            if not master:
                continue

            variant = self._variant_from_master(
                parse_master_variants(master), video_id, min_bw
            )
            if not variant:
                log.debug(
                    "adblock: flavor '%s' lacks matching quality",
                    AD_FREE_PARAM_SETS[preset]["playerType"],
                )
                continue

            text = self._fetch(variant.uri)
            if text is not None and not playlist_has_ads(text):
                with self._lock:
                    self._preset = preset
                    self._preferred[video_id] = variant.uri

                flavor = AD_FREE_PARAM_SETS[preset]["playerType"]
                if self._last_flavor != flavor:
                    self._last_flavor = flavor
                    ui_note(f"Ad-block: switched to '{flavor}' token at same quality")

                return text

        return None

    def _refresh_variant(self, video_id: str, min_bw: int) -> Optional[str]:
        for offset in range(len(AD_FREE_PARAM_SETS)):
            preset = (self._preset + offset) % len(AD_FREE_PARAM_SETS)
            master = self._fetch_master(preset)
            if not master:
                continue

            variant = self._variant_from_master(
                parse_master_variants(master), video_id, min_bw
            )
            if not variant:
                continue

            text = self._fetch(variant.uri)
            if text is not None:
                with self._lock:
                    self._preferred[video_id] = variant.uri
                return text

        return None


def wrap_with_adblock_proxy(
    twitch: TwitchPlayer,
    channel_name: str,
    stream_url: Optional[str],
    opts: Options,
) -> Optional[str]:
    if not stream_url or not opts.adblock:
        return stream_url

    proxy = HLSAdBlockProxy(twitch, channel_name, quality=opts.quality)
    if not proxy.start():
        ui_warn("Ad-block proxy unavailable; using direct URL")
        return stream_url

    ui_ok(f"Ad-block proxy listening on 127.0.0.1:{proxy.port}")
    return proxy.url()


# ---------------------------------------------------------------------------
# Player detection / launching
# ---------------------------------------------------------------------------
def player_installed(player_name: str) -> bool:
    if player_name == "flatpak-vlc":
        return shutil.which("flatpak") is not None

    return shutil.which(player_name) is not None


def resolve_player(requested_player: str) -> str:
    if requested_player not in AVAILABLE_PLAYERS:
        return requested_player

    if player_installed(requested_player):
        return requested_player

    for player_name in AVAILABLE_PLAYERS:
        if player_installed(player_name):
            return player_name

    return requested_player


def mpv_bitrate_from_quality(quality: Optional[str]) -> Optional[str]:
    if not quality:
        return None

    q = str(quality).lower().strip()

    if q in {"max", "min", "source"}:
        return "max" if q in {"max", "source"} else "min"

    q = q.rstrip("p")

    if q.isdigit():
        return str(int(q) * 1000)

    return None


def get_player_args(
    player_name: str,
    stream_url: str,
    stream_title: Optional[str],
    opts: Options,
) -> Tuple[Union[str, List[str]], bool]:
    if opts.custom_player:
        return opts.custom_player.replace("{url}", stream_url), True

    if player_name == "mpv":
        args = [
            "mpv",
            "--vo=gpu",
            "--hwdec=auto",
            f"--user-agent={ANDROID_USER_AGENT}",
            "--referrer=https://www.twitch.tv/",
        ]

        if opts.audio_only:
            args.append("--no-video")

        if opts.low_latency:
            args.extend(["--profile=low-latency", "--cache=no"])
        elif opts.cache:
            args.append("--cache=yes")

        bitrate = mpv_bitrate_from_quality(opts.quality)
        if bitrate:
            args.append(f"--hls-bitrate={bitrate}")

        if stream_title:
            args.append(f"--force-media-title={stream_title}")

        args.append(stream_url)
        return args, False

    if player_name == "vlc":
        args = [
            "vlc",
            "--intf=rc",
            f"--http-user-agent={ANDROID_USER_AGENT}",
        ]

        if opts.audio_only:
            args.append("--no-video")

        if opts.low_latency:
            args.append("--network-caching=300")
        elif opts.cache:
            args.append("--network-caching=1000")

        if stream_title:
            args.extend(["--meta-title", stream_title])

        args.append(stream_url)
        return args, False

    if player_name == "flatpak-vlc":
        args = [
            "flatpak",
            "run",
            "org.videolan.VLC",
            "--intf=rc",
            f"--http-user-agent={ANDROID_USER_AGENT}",
        ]

        if opts.audio_only:
            args.append("--no-video")

        if opts.low_latency:
            args.append("--network-caching=300")
        elif opts.cache:
            args.append("--network-caching=1000")

        if stream_title:
            args.extend(["--meta-title", stream_title])

        args.append(stream_url)
        return args, False

    if player_name == "ffplay":
        headers = (
            f"User-Agent: {ANDROID_USER_AGENT}\r\n"
            "Referer: https://www.twitch.tv/\r\n"
        )

        args = [
            "ffplay",
            "-autoexit",
            "-headers",
            headers,
        ]

        if opts.audio_only:
            args.append("-nodisp")

        if opts.low_latency:
            args.extend(["-fflags", "nobuffer"])

        if stream_title:
            args.extend(["-window_title", stream_title])

        args.append(stream_url)
        return args, False

    return (
        f"mpv --vo=gpu --hwdec=auto --user-agent='{ANDROID_USER_AGENT}' '{stream_url}'",
        True,
    )


# ---------------------------------------------------------------------------
# UI lists / menus
# ---------------------------------------------------------------------------
def list_players() -> None:
    ui_section("Players")

    rows: List[List[Any]] = []

    for name, desc in AVAILABLE_PLAYERS.items():
        installed = "installed" if player_installed(name) else "missing"
        default = "default" if name == DEFAULT_PLAYER else ""
        rows.append([name, desc, installed, default])

    ui_table(["Player", "Description", "Status", "Default"], rows)

    print()
    ui_kv("Tip", "Use -p PLAYER or --custom-player CMD")


def build_twitch(opts: Options) -> TwitchPlayer:
    return TwitchPlayer(token=opts.token, use_keyring=opts.use_keyring)


def maybe_play_latest_vod(
    twitch: TwitchPlayer,
    info: StreamInfo,
    opts: Options,
) -> bool:
    if not info.user_id:
        return False

    if not sys.stdin.isatty():
        ui_err(f"{info.display_name or info.login} is offline")
        return False

    answer = ui_prompt(
        f"{info.display_name or info.login} is offline. Play latest VOD? [y/N]",
        default="N",
    )

    if not answer or not answer.lower().startswith("y"):
        return False

    latest = twitch.get_latest_vod(info.user_id)
    if not latest:
        ui_err("No recent VOD found")
        return False

    return play_stream(f"https://www.twitch.tv/videos/{latest.id}", opts)


def list_followed_streams(opts: Options) -> bool:
    opts.force_login = False
    twitch = build_twitch(opts)

    if not twitch.ensure_auth(interactive=True, show_status=False):
        return False

    user_id = twitch.get_user_id()
    if not user_id:
        ui_err("Could not resolve user ID from OAuth token")
        return False

    after: Optional[str] = None
    history: List[Optional[str]] = []

    while True:
        with ui_spinner("Fetching followed channels"):
            streams, next_cursor = twitch.get_followed_live_streams(
                user_id,
                first=opts.page_size,
                after=after,
            )

        if not streams:
            ui_section("Followed channels")
            ui_kv("Status", "No followed channels are live right now")
            return True

        ui_section("Live from your follows")

        rows = []
        for i, stream in enumerate(streams, 1):
            rows.append(
                [
                    f"{i:02d}",
                    stream.user_name,
                    stream.game_name,
                    format_viewers(stream.viewer_count),
                    format_uptime(stream.started_at),
                ]
            )

        ui_table(["#", "Channel", "Game", "Viewers", "Uptime"], rows)

        print()
        ui_kv("Keys", "number play · n next · p previous · q quit")

        choice = ui_prompt("Choose")
        if choice is None or choice.lower() == "q":
            return True

        if choice.lower() == "n":
            if next_cursor:
                history.append(after)
                after = next_cursor
                continue

            ui_warn("No more pages")
            continue

        if choice.lower() == "p":
            if history:
                after = history.pop()
                continue

            ui_warn("Already at first page")
            continue

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(streams):
                play_stream(streams[idx].user_login, opts)
                continue

        ui_warn("Invalid selection")


def search_streams(game_query: str, opts: Options) -> bool:
    opts.force_login = False
    twitch = build_twitch(opts)

    if not twitch.ensure_auth(interactive=True, show_status=False):
        return False

    with ui_spinner(f"Searching for game/category: {game_query}"):
        game = twitch.search_game(game_query)

    if not game:
        ui_err(f"Game/category not found: {game_query}")
        return False

    after: Optional[str] = None
    history: List[Optional[str]] = []

    while True:
        ui_section(f"Live streams · {game.name}")

        with ui_spinner("Fetching live streams"):
            streams, next_cursor = twitch.get_streams_by_game(
                game.id,
                first=opts.page_size,
                after=after,
            )

        if not streams:
            ui_kv("Status", f"No live streams found for {game.name}")
            return True

        rows = []
        for i, stream in enumerate(streams, 1):
            rows.append(
                [
                    f"{i:02d}",
                    stream.user_name,
                    format_viewers(stream.viewer_count),
                    format_uptime(stream.started_at),
                ]
            )

        ui_table(["#", "Channel", "Viewers", "Uptime"], rows)

        print()
        ui_kv("Keys", "number play · n next · p previous · q quit")

        choice = ui_prompt("Choose")
        if choice is None or choice.lower() == "q":
            return True

        if choice.lower() == "n":
            if next_cursor:
                history.append(after)
                after = next_cursor
                continue

            ui_warn("No more pages")
            continue

        if choice.lower() == "p":
            if history:
                after = history.pop()
                continue

            ui_warn("Already at first page")
            continue

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(streams):
                play_stream(streams[idx].user_login, opts)
                continue

        ui_warn("Invalid selection")


def find_channels(query: str, opts: Options) -> bool:
    opts.force_login = False
    twitch = build_twitch(opts)

    if not twitch.ensure_auth(interactive=True, show_status=False):
        return False

    with ui_spinner(f"Searching channels for: {query}"):
        results = twitch.search_channels(query, first=opts.page_size)

    if not results:
        ui_err(f"No channel results for: {query}")
        return False

    while True:
        ui_section(f"Channel search · {query}")

        rows = []
        for i, item in enumerate(results, 1):
            live = "live" if item.get("is_live") else "offline"
            rows.append(
                [
                    f"{i:02d}",
                    item.get("display_name", "Unknown"),
                    live,
                    item.get("game_name", ""),
                    str(item.get("title", ""))[:40],
                ]
            )

        ui_table(["#", "Channel", "Status", "Game", "Title"], rows)

        print()
        ui_kv("Keys", "number play · q quit")

        choice = ui_prompt("Choose")
        if choice is None or choice.lower() == "q":
            return True

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(results):
                login = results[idx].get("broadcaster_login")
                if login:
                    play_stream(str(login), opts)
                    continue

        ui_warn("Invalid selection")


def browse_vods(channel: str, opts: Options) -> bool:
    opts.force_login = False
    twitch = build_twitch(opts)

    if not twitch.ensure_auth(interactive=True, show_status=False):
        return False

    with ui_spinner(f"Looking up channel: {channel}"):
        user = twitch.get_user_by_login(channel)

    if not user:
        ui_err(f"Channel not found: {channel}")
        return False

    user_id = str(user.get("id"))
    display_name = str(user.get("display_name", channel))

    after: Optional[str] = None
    history: List[Optional[str]] = []

    while True:
        ui_section(f"VODs · {display_name}")

        with ui_spinner("Fetching VODs"):
            vods, next_cursor = twitch.get_videos(
                user_id,
                first=opts.page_size,
                after=after,
            )

        if not vods:
            ui_kv("Status", "No VODs found")
            return True

        rows = []
        for i, vod in enumerate(vods, 1):
            rows.append(
                [
                    f"{i:02d}",
                    vod.title[:50],
                    vod.duration,
                    format_viewers(vod.view_count),
                    format_date(vod.created_at),
                ]
            )

        ui_table(["#", "Title", "Duration", "Views", "Date"], rows)

        print()
        ui_kv("Keys", "number play · n next · p previous · q quit")

        choice = ui_prompt("Choose")
        if choice is None or choice.lower() == "q":
            return True

        if choice.lower() == "n":
            if next_cursor:
                history.append(after)
                after = next_cursor
                continue

            ui_warn("No more pages")
            continue

        if choice.lower() == "p":
            if history:
                after = history.pop()
                continue

            ui_warn("Already at first page")
            continue

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(vods):
                play_stream(f"https://www.twitch.tv/videos/{vods[idx].id}", opts)
                continue

        ui_warn("Invalid selection")


def interactive_mode(opts: Options) -> bool:
    opts.force_login = False

    while True:
        ui_section("Interactive mode")

        rows = [
            ["1", "Play channel or URL"],
            ["2", "Browse followed live channels"],
            ["3", "Browse game/category"],
            ["4", "Search channel"],
            ["5", "Browse channel VODs"],
            ["6", "Login"],
            ["7", "Logout"],
            ["q", "Quit"],
        ]

        ui_table(["#", "Action"], rows)

        choice = ui_prompt("Choose")
        if choice is None or choice.lower() in {"q", "quit", "exit"}:
            return True

        if choice == "1":
            channel = ui_prompt("Channel or URL")
            if channel:
                play_stream(channel, opts)

        elif choice == "2":
            list_followed_streams(opts)

        elif choice == "3":
            game = ui_prompt("Game/category")
            if game:
                search_streams(game, opts)

        elif choice == "4":
            query = ui_prompt("Search channels")
            if query:
                find_channels(query, opts)

        elif choice == "5":
            channel = ui_prompt("Channel for VODs")
            if channel:
                browse_vods(channel, opts)

        elif choice == "6":
            twitch = build_twitch(opts)
            twitch.ensure_auth(interactive=True, show_status=True)

        elif choice == "7":
            TokenStorage(use_keyring=opts.use_keyring).delete_token()
            ui_ok("Logged out. Token cleared.")

        else:
            ui_warn("Invalid selection")


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------
def play_stream(channel_input: Optional[str], opts: Options) -> bool:
    twitch = build_twitch(opts)

    if opts.force_login:
        if not twitch.ensure_auth(interactive=True, show_status=True):
            return False

        opts.force_login = False

    if not channel_input:
        return True

    stream_title: Optional[str] = None
    stream_url: Optional[str] = None
    channel_name: Optional[str] = None

    try:
        if channel_input.startswith("http"):
            url_type, identifier = parse_twitch_url(channel_input)

            if url_type is None or identifier is None:
                ui_err(f"Invalid Twitch URL: {channel_input}")
                return False

            if url_type == "clip":
                with ui_spinner("Fetching clip"):
                    stream_url, stream_title = twitch.get_clip_info(identifier)

            elif url_type == "vod":
                with ui_spinner("Fetching VOD info"):
                    vod = twitch.get_vod_info(identifier)

                if vod:
                    stream_title = f"{vod.title} - {vod.display_name}"

                    ui_section("VOD")
                    ui_kv("Title", stream_title)
                    ui_kv("Duration", vod.duration or "N/A")
                    ui_kv("Views", format_viewers(vod.view_count))
                    ui_kv("Date", format_date(vod.created_at))

                with ui_spinner("Building VOD URL"):
                    stream_url = twitch.get_vod_url(identifier)

            else:
                channel_name = identifier
        else:
            channel_name = channel_input.strip().rstrip("/").lower().split("/")[-1]

        if channel_name:
            with ui_spinner(f"Fetching stream for {channel_name}"):
                info = twitch.get_stream_info(channel_name)

            if not info:
                ui_err(f"Channel not found: {channel_name}")
                return False

            if not info.online:
                return maybe_play_latest_vod(twitch, info, opts)

            stream_title = f"{info.title} - {info.display_name}"

            ui_section("Stream")
            ui_kv("Channel", info.display_name)
            ui_kv("Title", info.title or "")
            ui_kv("Game", info.game or "")

            with ui_spinner("Building stream URL"):
                stream_url = twitch.get_stream_url(channel_name)

            stream_url = wrap_with_adblock_proxy(twitch, channel_name, stream_url, opts)

    except requests.exceptions.RequestException as exc:
        ui_err(f"Network error: {exc}")
        return False

    if not stream_url:
        ui_err("Could not resolve a playable stream URL")
        return False

    player = resolve_player(opts.player)
    player_args, use_shell = get_player_args(player, stream_url, stream_title, opts)

    ui_kv("Player", opts.custom_player or player)
    ui_note("Starting player (Ctrl+C to stop)")

    try:
        result = subprocess.run(player_args, shell=use_shell)
        return result.returncode == 0
    except KeyboardInterrupt:
        print()
        return True
    except FileNotFoundError:
        ui_err(f"Player not found: {player}")
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twitch-cli",
        description="Twitch CLI player with OAuth, browsing, and ad blocking.",
    )

    playback = parser.add_argument_group("playback")
    playback.add_argument(
        "channel", nargs="?", default=None,
        help="channel name, or a twitch.tv stream/VOD/clip URL",
    )
    playback.add_argument("-p", "--player", default=None,
                          help="player to use (mpv, vlc, flatpak-vlc, ffplay)")
    playback.add_argument("--custom-player", default=None, metavar="CMD",
                          help="custom player command; use {url} as the URL placeholder")
    playback.add_argument("-q", "--quality", default=None,
                          help="quality preference (source, 720p60, min, max)")
    playback.add_argument("-a", "--audio-only", action="store_true",
                          help="audio-only playback")
    playback.add_argument("-l", "--low-latency", action="store_true",
                          help="optimize for low latency")
    playback.add_argument("--cache", action="store_true",
                          help="enable extra buffering")

    ads = parser.add_mutually_exclusive_group()
    ads.add_argument("--adblock", dest="adblock", action="store_true", default=None,
                     help="filter mid-roll ads via local proxy (default: on)")
    ads.add_argument("--no-adblock", dest="adblock", action="store_false",
                     help="connect directly to Twitch without ad filtering")

    auth = parser.add_argument_group("auth")
    auth.add_argument("--login", action="store_true",
                      help="force interactive OAuth login before playing")
    auth.add_argument("--logout", action="store_true",
                      help="clear stored OAuth token and exit")
    auth.add_argument("--token", default=None,
                      help=f"OAuth token (defaults to ${TOKEN_ENV_VAR} or stored token)")
    auth.add_argument("--keyring", action="store_true",
                      help="store the token in the system keyring")

    browse = parser.add_argument_group("browse")
    browse.add_argument("-f", "--followed", action="store_true",
                        help="browse live channels you follow")
    browse.add_argument("-s", "--game", metavar="GAME",
                        help="browse live streams for a game/category")
    browse.add_argument("--find", metavar="QUERY",
                        help="search channels")
    browse.add_argument("--vods", metavar="CHANNEL",
                        help="browse VODs for a channel")
    browse.add_argument("-i", "--interactive", action="store_true",
                        help="open the interactive menu")

    misc = parser.add_argument_group("misc")
    misc.add_argument("--list-players", action="store_true",
                      help="list supported players and exit")
    misc.add_argument("--config", default=None, metavar="PATH",
                      help="config file path")
    misc.add_argument("--no-rich", action="store_true",
                      help="disable rich output")
    misc.add_argument("--debug", action="store_true",
                      help="enable debug logging")
    misc.add_argument("--log-file", default=None, metavar="PATH",
                      help="write logs to a file")
    misc.add_argument("--version", action="version",
                      version=f"%(prog)s {__version__}")

    return parser


def setup_logging(debug: bool = False, log_file: Optional[str] = None) -> None:
    level = logging.DEBUG if debug else logging.WARNING
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stderr)]

    if log_file:
        try:
            path = Path(log_file).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(path, encoding="utf-8"))
        except OSError as exc:
            print(f"Warning: could not open log file {log_file}: {exc}", file=sys.stderr)

    logging.basicConfig(
        level=level,
        handlers=handlers,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config, _config_path = load_config(args.config)

    debug = args.debug or bool(config.get("debug", False))
    log_file = args.log_file or config.get("log_file")
    setup_logging(debug=debug, log_file=log_file)

    set_rich_enabled(not (args.no_rich or bool(config.get("no_rich", False))))
    ui_banner()

    if args.adblock is None:
        adblock = bool(config.get("adblock", True))
    else:
        adblock = args.adblock

    opts = Options(
        player=args.player or str(config.get("player") or DEFAULT_PLAYER),
        custom_player=args.custom_player or config.get("custom_player"),
        token=args.token,
        use_keyring=args.keyring or bool(config.get("use_keyring", False)),
        audio_only=args.audio_only or bool(config.get("audio_only", False)),
        low_latency=args.low_latency or bool(config.get("low_latency", False)),
        cache=args.cache or bool(config.get("cache", False)),
        quality=args.quality or config.get("quality"),
        debug=debug,
        page_size=int(config.get("page_size", 20) or 20),
        force_login=args.login,
        adblock=adblock,
    )

    if args.list_players:
        list_players()
        return 0

    if args.logout:
        TokenStorage(use_keyring=opts.use_keyring).delete_token()
        ui_ok("Logged out. Token cleared.")
        return 0

    if args.followed:
        return 0 if list_followed_streams(opts) else 1

    if args.game:
        return 0 if search_streams(args.game, opts) else 1

    if args.find:
        return 0 if find_channels(args.find, opts) else 1

    if args.vods:
        return 0 if browse_vods(args.vods, opts) else 1

    if args.interactive or not args.channel:
        return 0 if interactive_mode(opts) else 1

    return 0 if play_stream(args.channel, opts) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
