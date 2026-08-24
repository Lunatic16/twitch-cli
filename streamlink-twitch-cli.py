#!/usr/bin/env python3
"""
Twitch CLI Player - enhanced single-file version.

Implements the recommended improvements except splitting into modules.
"""

from __future__ import annotations

import argparse
import atexit
import difflib
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import quote, urlparse

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
    "block_ads": True,
}

UI_WIDTH = 58

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
    block_ads: bool = True


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

    def get_stream_playback_token(self, channel_name: str) -> Tuple[Optional[str], Optional[str]]:
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
            "params": {
                "platform": "android",
                "playerBackend": "mediaplayer",
                "playerType": "mobile",
            },
        }

        result = self._gql_post(query, variables)
        token_data = (result.get("data") or {}).get("streamPlaybackAccessToken")

        if token_data:
            return token_data.get("value"), token_data.get("signature")

        return None, None

    def get_stream_url(self, channel_name: str) -> Optional[str]:
        token, signature = self.get_stream_playback_token(channel_name)
        if not token or not signature:
            return None

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
# Ad blocking
# ---------------------------------------------------------------------------
def streamlink_installed() -> bool:
    return shutil.which("streamlink") is not None


def build_streamlink_cmd(url: str, opts: Options, stream_title: Optional[str] = None) -> Optional[List[str]]:
    """Build a streamlink command that blocks Twitch ads.

    Streamlink fetches the HLS stream itself, so the player only needs
    display/cache options. We use --player for the executable and
    --player-args for flags. Streamlink replaces {filename} with the
    temporary stream pipe/URL.
    """
    if not streamlink_installed():
        return None

    cmd = ["streamlink", "--twitch-disable-ads"]

    # Determine player executable
    if opts.custom_player:
        player_exe = shlex.split(opts.custom_player)[0]
    else:
        player_exe = resolve_player(opts.player)

    # Build player args (no user-agent/referrer needed — Streamlink handles HTTP)
    player_args: List[str] = []

    if player_exe == "mpv":
        player_args = ["--vo=gpu", "--hwdec=auto"]
        if opts.audio_only:
            player_args.append("--no-video")
        if opts.low_latency:
            player_args.extend(["--profile=low-latency", "--cache=no"])
        elif opts.cache:
            player_args.append("--cache=yes")
        bitrate = mpv_bitrate_from_quality(opts.quality)
        if bitrate:
            player_args.append(f"--hls-bitrate={bitrate}")
        if stream_title:
            # Quote the title so spaces survive Streamlink's shlex.split
            player_args.append(f'--force-media-title="{stream_title}"')

    elif player_exe in ("vlc", "flatpak-vlc"):
        if opts.audio_only:
            player_args.append("--no-video")
        if opts.low_latency:
            player_args.append("--network-caching=300")
        elif opts.cache:
            player_args.append("--network-caching=1000")
        if stream_title:
            player_args.append(f'--meta-title="{stream_title}"')

    elif player_exe == "ffplay":
        player_args = ["-autoexit"]
        if opts.audio_only:
            player_args.append("-nodisp")
        if opts.low_latency:
            player_args.extend(["-fflags", "nobuffer"])
        if stream_title:
            player_args.append(f'-window_title="{stream_title}"')

    # Streamlink replaces {filename} with the stream URL
    player_args.append("{filename}")

    cmd.extend(["--player", player_exe])
    if player_args:
        # Join with spaces; Streamlink internally uses shlex.split on this string.
        # We only quote values that contain spaces (titles), not the whole arg.
        cmd.extend(["--player-args", " ".join(player_args)])

    cmd.append(url)
    cmd.append("best")
    return cmd


def filter_hls_playlist(playlist_url: str, session: requests.Session) -> Optional[str]:
    """
    Fetch an HLS variant playlist and strip out ad segments.

    Twitch ads are injected as blocks between #EXT-X-DISCONTINUITY tags.
    Segments inside these blocks often come from different CDNs than the
    main content. We detect ad blocks by comparing segment domains and
    remove them, writing a cleaned playlist to a temp file.
    """
    try:
        resp = session.get(playlist_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:
        log.debug("HLS filter fetch failed: %s", exc)
        return None

    lines = resp.text.splitlines()
    base_url = playlist_url.rsplit("/", 1)[0] + "/"

    # Determine the "content domain" from the first non-ad segment
    content_domain: Optional[str] = None
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            url = stripped if stripped.startswith("http") else base_url + stripped
            content_domain = urlparse(url).netloc
            break

    if not content_domain:
        return None

    filtered: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("#EXT-X-DISCONTINUITY"):
            # Peek ahead to see if the next segment belongs to a different domain
            j = i + 1
            seg_domain: Optional[str] = None
            while j < len(lines):
                peek = lines[j].strip()
                if peek.startswith("#EXT-X-DISCONTINUITY"):
                    break
                if peek and not peek.startswith("#"):
                    url = peek if peek.startswith("http") else base_url + peek
                    seg_domain = urlparse(url).netloc
                    break
                j += 1

            if seg_domain and seg_domain != content_domain:
                # Skip the entire ad block (until next discontinuity or end)
                i += 1
                while i < len(lines) and not lines[i].startswith("#EXT-X-DISCONTINUITY"):
                    i += 1
                # Skip the closing discontinuity too
                if i < len(lines) and lines[i].startswith("#EXT-X-DISCONTINUITY"):
                    i += 1
                continue

        # Make relative segment URLs absolute so the temp file works
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("http"):
            line = base_url + stripped

        filtered.append(line)
        i += 1

    if not filtered:
        return None

    # Write cleaned playlist to a temp file
    fd, path = tempfile.mkstemp(suffix=".m3u8")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(filtered))

    return path


def get_ad_free_url(
    twitch: TwitchPlayer,
    stream_url: str,
    channel_name: Optional[str] = None,
    is_live: bool = True,
    opts: Optional[Options] = None,
    stream_title: Optional[str] = None,
) -> Tuple[Optional[str], Optional[List[str]]]:
    """
    Returns (filtered_url, streamlink_cmd).

    - If Streamlink is available, returns (None, streamlink_cmd).
    - Otherwise tries HLS playlist filtering and returns (filtered_url, None).
    - Falls back to (stream_url, None) if everything fails.
    """
    if not opts or not opts.block_ads:
        return stream_url, None

    # 1. Try Streamlink (most reliable)
    if is_live and channel_name and streamlink_installed():
        sl_cmd = build_streamlink_cmd(f"twitch.tv/{channel_name}", opts, stream_title=stream_title)
        if sl_cmd:
            ui_note("Using Streamlink for ad-free playback")
            return None, sl_cmd

    # VODs can also use Streamlink directly with the URL
    if not is_live and streamlink_installed():
        sl_cmd = build_streamlink_cmd(stream_url, opts, stream_title=stream_title)
        if sl_cmd:
            ui_note("Using Streamlink for ad-free VOD playback")
            return None, sl_cmd

    # 2. Fallback: HLS playlist filtering
    if is_live and channel_name:
        # For live streams, we need to pick a variant from the master playlist
        try:
            resp = twitch.session.get(stream_url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except Exception as exc:
            log.debug("Master playlist fetch failed: %s", exc)
            return stream_url, None

        master_lines = resp.text.splitlines()
        variants: List[Tuple[Optional[int], str]] = []

        for idx, line in enumerate(master_lines):
            if line.startswith("#EXT-X-STREAM-INF"):
                bw = None
                for attr in line.split(","):
                    attr = attr.strip()
                    if attr.startswith("BANDWIDTH="):
                        try:
                            bw = int(attr.split("=", 1)[1])
                        except ValueError:
                            pass
                if idx + 1 < len(master_lines):
                    url = master_lines[idx + 1].strip()
                    if url and not url.startswith("#"):
                        variants.append((bw, url))

        if not variants:
            return stream_url, None

        # Select variant: match quality hint or pick highest bandwidth
        variant_url = variants[0][1]
        if opts and opts.quality:
            q = opts.quality.lower().rstrip("p")
            if q.isdigit():
                target = int(q)
                for bw, url in variants:
                    # Resolution info may be in the URL or we just pick by bandwidth order
                    pass
            # For simplicity, pick highest bandwidth
            variants_sorted = sorted(variants, key=lambda x: x[0] or 0, reverse=True)
            variant_url = variants_sorted[0][1]
        else:
            variants_sorted = sorted(variants, key=lambda x: x[0] or 0, reverse=True)
            variant_url = variants_sorted[0][1]

        # Make absolute
        if not variant_url.startswith("http"):
            base = stream_url.rsplit("/", 1)[0] + "/"
            variant_url = base + variant_url

        filtered = filter_hls_playlist(variant_url, twitch.session)
        if filtered:
            ui_note("Using built-in HLS ad filter (best-effort)")
            return filtered, None

    else:
        # VOD: filter the VOD playlist directly
        filtered = filter_hls_playlist(stream_url, twitch.session)
        if filtered:
            ui_note("Using built-in HLS ad filter for VOD (best-effort)")
            return filtered, None

    ui_warn("Ad blocking unavailable — ads may play (install Streamlink for best results)")
    return stream_url, None


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
    is_live = True

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
                is_live = False
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

                with ui_spinner(f"Fetching stream for {channel_name}"):
                    info = twitch.get_stream_info(channel_name)

                if not info:
                    ui_err(f"Channel not found: {channel_name}")
                    return False

                if not info.online:
                    return maybe_play_latest_vod(twitch, info, opts)

                stream_title = f"{info.title or 'Live'} - {info.display_name or info.login}"
                if info.game:
                    stream_title += f" | {info.game}"

                with ui_spinner("Building playback URL"):
                    stream_url = twitch.get_stream_url(info.login)

        else:
            channel_name = channel_input.lstrip("@")

            with ui_spinner(f"Fetching stream for {channel_name}"):
                info = twitch.get_stream_info(channel_name)

            if not info:
                ui_err(f"Channel not found: {channel_name}")
                return False

            if not info.online:
                return maybe_play_latest_vod(twitch, info, opts)

            stream_title = f"{info.title or 'Live'} - {info.display_name or info.login}"
            if info.game:
                stream_title += f" | {info.game}"

            with ui_spinner("Building playback URL"):
                stream_url = twitch.get_stream_url(info.login)

    except requests.exceptions.RequestException as exc:
        ui_err(f"Network/API error: {exc}")
        return False
    except Exception as exc:
        ui_err(f"Error: {exc}")
        return False

    if not stream_url:
        ui_err("Could not build playback URL")
        return False

    # -----------------------------------------------------------------------
    # Ad blocking path
    # -----------------------------------------------------------------------
    filtered_url: Optional[str] = None
    streamlink_cmd: Optional[List[str]] = None

    if opts.block_ads:
        filtered_url, streamlink_cmd = get_ad_free_url(
            twitch, stream_url, channel_name=channel_name, is_live=is_live, opts=opts, stream_title=stream_title
        )
    else:
        filtered_url = stream_url

    player = opts.player

    if not opts.custom_player:
        resolved = resolve_player(opts.player)

        if resolved != opts.player:
            ui_warn(f"Player '{opts.player}' not found. Falling back to '{resolved}'.")

        player = resolved

    ui_section("Now playing")

    if stream_title:
        ui_kv("Title", stream_title)

    if streamlink_cmd:
        ui_kv("Backend", "streamlink (ad-free)")
    elif filtered_url != stream_url:
        ui_kv("Backend", "HLS filter (ad-free)")
    else:
        ui_kv("Player", opts.custom_player or player)

    mode_bits = []
    if opts.audio_only:
        mode_bits.append("audio-only")
    if opts.low_latency:
        mode_bits.append("low-latency")
    if opts.cache:
        mode_bits.append("cache")
    if opts.quality:
        mode_bits.append(f"quality={opts.quality}")
    if not opts.block_ads:
        mode_bits.append("ads-allowed")

    if mode_bits:
        ui_kv("Mode", ", ".join(mode_bits))

    ui_kv("Status", "starting playback")
    print()

    # Launch playback
    try:
        if streamlink_cmd:
            subprocess.run(streamlink_cmd)
        else:
            player_cmd, use_shell = get_player_args(player, filtered_url or stream_url, stream_title, opts)
            if use_shell:
                subprocess.run(str(player_cmd), shell=True)
            else:
                subprocess.run(player_cmd)

        return True

    except FileNotFoundError:
        ui_err(f"Player not found: {player}")
        return False

    except KeyboardInterrupt:
        print()
        ui_warn("Playback interrupted")
        return True

    except Exception as exc:
        ui_err(f"Playback error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Help / CLI
# ---------------------------------------------------------------------------
def print_help() -> None:
    ui_banner()

    ui_section("Usage")
    print("  twitch_cli.py [CHANNEL] [options]")

    ui_section("Core options")
    options = [
        ("CHANNEL", "Channel name, URL, VOD URL, or clip URL"),
        ("-p, --player", "Player: mpv, vlc, flatpak-vlc, ffplay"),
        ("--custom-player", "Custom player command, use {url}"),
        ("--token", "OAuth token"),
        ("--login", "Force OAuth login"),
        ("--logout", "Delete stored OAuth token"),
        ("--config", "Custom config file path"),
        ("--write-default-config", "Write default config file"),
    ]

    for name, desc in options:
        print(f"  {c(name, C.BLUE)} {c('·', C.D)} {desc}")

    ui_section("Browse options")
    browse_options = [
        ("--followed", "Browse followed live channels"),
        ("--search GAME", "Browse live channels in game/category"),
        ("--find CHANNEL", "Search channels"),
        ("--vods CHANNEL", "Browse channel VODs"),
        ("--interactive", "Interactive menu"),
        ("--list-players", "List players"),
    ]

    for name, desc in browse_options:
        print(f"  {c(name, C.BLUE)} {c('·', C.D)} {desc}")

    ui_section("Playback options")
    playback_options = [
        ("--audio-only", "Play without video where supported"),
        ("--low-latency", "Prefer lower latency where supported"),
        ("--cache", "Enable player cache where supported"),
        ("--quality", "Quality hint: max, min, or bitrate value"),
        ("--block-ads", "Enable ad blocking (default: true)"),
        ("--no-block-ads", "Disable ad blocking"),
    ]

    for name, desc in playback_options:
        print(f"  {c(name, C.BLUE)} {c('·', C.D)} {desc}")

    ui_section("Advanced options")
    advanced_options = [
        ("--keyring", "Force keyring token storage"),
        ("--no-keyring", "Force file token storage"),
        ("--no-rich", "Disable Rich UI"),
        ("--debug", "Debug logging"),
        ("--log-file FILE", "Write logs to file"),
        ("--limit N", "Page size for menus"),
        ("--self-test", "Run simple self tests"),
        ("--completion SHELL", "Print shell completion: bash, zsh, fish"),
        ("--version", "Print version"),
    ]

    for name, desc in advanced_options:
        print(f"  {c(name, C.BLUE)} {c('·', C.D)} {desc}")

    ui_section("Examples")
    examples = [
        ("twitch_cli.py willneff", "Play channel"),
        ("twitch_cli.py willneff --audio-only", "Audio-only"),
        ("twitch_cli.py --followed", "Browse followed channels"),
        ("twitch_cli.py --search 'just chatting'", "Browse category"),
        ("twitch_cli.py --find shroud", "Search channels"),
        ("twitch_cli.py --vods shroud", "Browse VODs"),
        ("twitch_cli.py --interactive", "Interactive menu"),
        ("twitch_cli.py --login", "Login"),
    ]

    for example, desc in examples:
        print(f"  {c(example, C.BLUE)} {c('·', C.D)} {desc}")

    print()


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="twitch_cli.py",
        description="Enhanced Twitch CLI player",
        add_help=False,
    )

    parser.add_argument("channel", nargs="?", metavar="CHANNEL")

    parser.add_argument("-p", "--player", default=None)
    parser.add_argument("--custom-player", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--config", default=None)

    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--quality", default=None)

    parser.add_argument("--audio-only", action="store_true", default=None)
    parser.add_argument("--low-latency", action="store_true", default=None)
    parser.add_argument("--cache", action="store_true", default=None)

    parser.add_argument("--block-ads", action="store_true", default=None)
    parser.add_argument("--no-block-ads", action="store_true", default=None)

    parser.add_argument("--keyring", action="store_true", default=None)
    parser.add_argument("--no-keyring", action="store_true", default=None)
    parser.add_argument("--no-rich", action="store_true", default=None)
    parser.add_argument("--debug", action="store_true", default=None)
    parser.add_argument("--log-file", default=None)

    parser.add_argument("--list-players", action="store_true")
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--logout", action="store_true")
    parser.add_argument("--followed", action="store_true")
    parser.add_argument("--search", metavar="GAME")
    parser.add_argument("--find", metavar="CHANNEL")
    parser.add_argument("--vods", metavar="CHANNEL")
    parser.add_argument("--interactive", action="store_true")

    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--write-default-config", action="store_true")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--completion", choices=["bash", "zsh", "fish"])

    parser.add_argument("-h", "--help", action="store_true")

    return parser


def setup_logging(debug: bool = False, log_file: Optional[str] = None) -> None:
    log.handlers.clear()
    log.setLevel(logging.DEBUG if debug else logging.WARNING)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    log.addHandler(stderr_handler)

    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            log.addHandler(file_handler)
        except OSError as exc:
            print(f"Warning: could not open log file {log_file}: {exc}")


# ---------------------------------------------------------------------------
# Self-tests
# ---------------------------------------------------------------------------
def run_self_tests() -> int:
    failures: List[str] = []

    def check(name: str, condition: bool) -> None:
        if condition:
            ui_ok(f"PASS {name}")
        else:
            failures.append(name)
            ui_err(f"FAIL {name}")

    check(
        "parse channel URL",
        parse_twitch_url("https://www.twitch.tv/willneff") == ("channel", "willneff"),
    )

    check(
        "parse VOD URL",
        parse_twitch_url("https://www.twitch.tv/videos/123456") == ("vod", "123456"),
    )

    check(
        "parse clip URL",
        parse_twitch_url("https://clips.twitch.tv/SomeClipSlug") == ("clip", "SomeClipSlug"),
    )

    check(
        "parse channel clip URL",
        parse_twitch_url("https://www.twitch.tv/willneff/clip/SomeClipSlug") == ("clip", "SomeClipSlug"),
    )

    check(
        "reject non-Twitch URL",
        parse_twitch_url("https://example.com/videos/123") == (None, None),
    )

    check(
        "format viewers",
        format_viewers(12345) == "12,345",
    )

    opts = Options(player="mpv")
    cmd, use_shell = get_player_args("mpv", "https://example.com/stream.m3u8", "title", opts)

    check(
        "mpv args list",
        isinstance(cmd, list) and not use_shell and cmd[0] == "mpv",
    )

    opts_custom = Options(custom_player="mpv {url}")
    cmd_custom, use_shell_custom = get_player_args(
        "mpv",
        "https://example.com/stream.m3u8",
        None,
        opts_custom,
    )

    check(
        "custom player shell command",
        use_shell_custom and cmd_custom == "mpv https://example.com/stream.m3u8",
    )

    # Ad blocking tests
    check(
        "streamlink detection returns bool",
        isinstance(streamlink_installed(), bool),
    )

    check(
        "build_streamlink_cmd returns None when streamlink missing",
        build_streamlink_cmd("twitch.tv/test", Options()) is None,
    )

    if failures:
        ui_err(f"{len(failures)} self-test(s) failed")
        return 1

    ui_ok("All self tests passed")
    return 0


# ---------------------------------------------------------------------------
# Shell completion
# ---------------------------------------------------------------------------
def print_completion(shell: str) -> None:
    options = [
        "--help",
        "--player",
        "--custom-player",
        "--token",
        "--config",
        "--limit",
        "--quality",
        "--audio-only",
        "--low-latency",
        "--cache",
        "--block-ads",
        "--no-block-ads",
        "--keyring",
        "--no-keyring",
        "--no-rich",
        "--debug",
        "--log-file",
        "--list-players",
        "--login",
        "--logout",
        "--followed",
        "--search",
        "--find",
        "--vods",
        "--interactive",
        "--self-test",
        "--write-default-config",
        "--version",
        "--completion",
    ]

    players = list(AVAILABLE_PLAYERS.keys())
    words = " ".join(options + players)

    if shell == "bash":
        print(f'complete -W "{words}" -o default twitch_cli.py')

    elif shell == "zsh":
        print("#compdef twitch_cli.py")
        print("_twitch_cli() {")
        print(f"  compadd -- {' '.join(options + players)}")
        print("}")
        print("compdef _twitch_cli twitch_cli.py")

    elif shell == "fish":
        for word in options + players:
            print(f"complete -c twitch_cli.py -a '{word}'")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def cli_or_config(cli_value: Any, config: Dict[str, Any], key: str, default: Any = None) -> Any:
    if cli_value is not None:
        return cli_value
    return config.get(key, default)


def main() -> None:
    parser = create_parser()
    args = parser.parse_args()

    config, config_path = load_config(args.config)

    no_rich = bool(cli_or_config(args.no_rich, config, "no_rich", False))
    set_rich_enabled(RICH_AVAILABLE and not no_rich and sys.stdout.isatty())

    debug = bool(cli_or_config(args.debug, config, "debug", False))
    log_file = cli_or_config(args.log_file, config, "log_file", None)
    setup_logging(debug=debug, log_file=log_file)

    if args.version:
        print(f"twitch-cli {__version__}")
        return

    if args.completion:
        print_completion(args.completion)
        return

    if args.self_test:
        sys.exit(run_self_tests())

    if args.write_default_config:
        path = write_default_config(args.config)
        ui_ok(f"Wrote default config to {path}")
        return

    use_keyring_env = os.environ.get(KEYRING_ENV_VAR, "").lower() in {"1", "true", "yes", "on"}
    use_keyring = bool(config.get("use_keyring", False) or use_keyring_env)

    if args.keyring:
        use_keyring = True

    if args.no_keyring:
        use_keyring = False

    page_size = int(cli_or_config(args.limit, config, "page_size", 20) or 20)
    if page_size <= 0:
        page_size = 20

    # Resolve block_ads: CLI flags override config
    block_ads = bool(config.get("block_ads", True))
    if args.block_ads is not None:
        block_ads = args.block_ads
    if args.no_block_ads:
        block_ads = False

    opts = Options(
        player=str(cli_or_config(args.player, config, "player", DEFAULT_PLAYER)),
        custom_player=cli_or_config(args.custom_player, config, "custom_player", None),
        token=args.token or os.environ.get(TOKEN_ENV_VAR),
        use_keyring=use_keyring,
        audio_only=bool(cli_or_config(args.audio_only, config, "audio_only", False)),
        low_latency=bool(cli_or_config(args.low_latency, config, "low_latency", False)),
        cache=bool(cli_or_config(args.cache, config, "cache", False)),
        quality=cli_or_config(args.quality, config, "quality", None),
        debug=debug,
        page_size=page_size,
        force_login=bool(args.login),
        block_ads=block_ads,
    )

    if args.list_players:
        ui_banner()
        list_players()
        return

    if args.logout:
        TokenStorage(use_keyring=opts.use_keyring).delete_token()
        ui_ok("Logged out. Token cleared.")
        return

    if args.interactive:
        ui_banner()
        success = interactive_mode(opts)
        sys.exit(0 if success else 1)

    if args.followed:
        ui_banner()
        success = list_followed_streams(opts)
        sys.exit(0 if success else 1)

    if args.search:
        ui_banner()
        success = search_streams(args.search, opts)
        sys.exit(0 if success else 1)

    if args.find:
        ui_banner()
        success = find_channels(args.find, opts)
        sys.exit(0 if success else 1)

    if args.vods:
        ui_banner()
        success = browse_vods(args.vods, opts)
        sys.exit(0 if success else 1)

    if args.help or (not args.channel and not args.login):
        print_help()
        return

    success = play_stream(args.channel, opts)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        ui_warn("Interrupted")
        sys.exit(130)
    except requests.exceptions.RequestException as exc:
        ui_err(f"Network/API error: {exc}")
        sys.exit(1)
