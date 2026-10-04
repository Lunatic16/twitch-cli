# proxy-twitch-cli.py — API Documentation

**Version:** 3.1.0
**Type:** Single-file Python application / importable module
**Summary:** A Twitch CLI player with OAuth support, live/VOD/clip playback, and a local HLS filtering proxy that suppresses mid-roll ad injections by rotating playback-access tokens across player types.

> **Note:** The provided source is truncated mid-way through `HLSAdBlockProxy._gather_masters()`. This document covers the complete, visible API surface; the proxy's internal rotation loop beyond `build_master()` is documented only to the extent visible.

---

## Table of Contents

1. [Dependencies](#1-dependencies)
2. [Environment Variables](#2-environment-variables)
3. [Constants](#3-constants)
4. [Configuration Files](#4-configuration-files)
5. [Data Types (Dataclasses)](#5-data-types-dataclasses)
6. [TokenStorage](#6-tokenstorage)
7. [OAuth Helpers](#7-oauth-helpers)
8. [TwitchPlayer (API Client)](#8-twitchplayer-api-client)
9. [Playlist / Ad-Blocking Helpers](#9-playlist--ad-blocking-helpers)
10. [HLSAdBlockProxy](#10-hlsadblockproxy)
11. [Utility Functions](#11-utility-functions)
12. [UI Helpers](#12-ui-helpers)
13. [Error Handling & Retry Semantics](#13-error-handling--retry-semantics)
14. [Usage Examples](#14-usage-examples)

---

## 1. Dependencies

| Package | Required | Purpose |
|---|---|---|
| `requests` | **Yes** (exits on import failure) | All HTTP communication |
| `qrcode` | No | ASCII QR code for OAuth login URL |
| `keyring` | No | Secure OS-level token storage |
| `rich` | No | Enhanced terminal rendering (panels, tables, spinners) |

All optional packages degrade gracefully. Feature flags exposed: `HAS_QRCODE`, `HAS_KEYRING`, `RICH_AVAILABLE`.

---

## 2. Environment Variables

| Variable | Read by | Effect |
|---|---|---|
| `TWITCH_TOKEN` | `TwitchPlayer.__init__` | Fallback OAuth token (precedence: explicit `token` arg → env → storage) |
| `TWITCH_WEB_AUTH_TOKEN` | `TwitchPlayer.__init__` | Browser cookie `auth-token`; enables privileged ("web-login") GQL token requests |
| `TWITCH_CLI_CONFIG` | `get_config_path` | Overrides the default config file path |
| `TWITCH_CLI_KEYRING` | Declared constant | Referenced as `KEYRING_ENV_VAR` (usage in truncated portion) |
| `NO_COLOR` | Module import time | Disables all ANSI color output |

---

## 3. Constants

### Endpoints & Credentials

| Constant | Value / Description |
|---|---|
| `GQL_CLIENT_ID` | Public web GQL client ID (`kimne78kx3ncx6brgo4mv6wki5h1ko`) |
| `OAUTH_CLIENT_ID` | OAuth/Helix client ID (`l2wx7tow5m77hvmg883p3a985618os`) |
| `OAUTH_SCOPES` | `chat:read chat:edit user:read:follows` |
| `REDIRECT_URI` | `http://localhost` (implicit-token flow) |
| `GQL_URL` | `https://gql.twitch.tv/gql` |
| `GQL_HEADERS` | Default headers sent by the shared `requests.Session` |

### Networking

| Constant | Value | Description |
|---|---|---|
| `REQUEST_TIMEOUT` | `15` | Default per-request timeout (seconds) |
| `MAX_RETRIES` | `3` | Retry attempts for retryable responses |
| `RETRYABLE_STATUS` | `{429, 500, 502, 503, 504}` | Status codes that trigger retry |

### Storage & Defaults

| Constant | Value |
|---|---|
| `KEYRING_SERVICE` / `KEYRING_ACCOUNT` | `"twitch-cli"` / `"oauth_token"` |
| `DEFAULT_PLAYER` | `"mpv"` |
| `AVAILABLE_PLAYERS` | `mpv`, `vlc`, `flatpak-vlc`, `ffplay` (with descriptions) |
| `ANDROID_USER_AGENT` | Spoofed ExoPlayer UA used by the ad-block proxy |
| `HLS_MIME` | `application/vnd.apple.mpegurl` |

### Ad-Blocking

**`AD_FREE_PARAM_SETS: List[Dict[str, str]]`** — Ordered list of `PlaybackAccessTokenParams` flavors tried when the current one serves ads. The first entry (`android/mobile`) is the default for direct playback:

1. `platform=android, playerBackend=mediaplayer, playerType=mobile`
2. `platform=web, playerType=frontpage`
3. `platform=web, playerType=embed`
4. `platform=ios, playerType=ios`
5. `platform=web, playerType=site`

**`AD_MARKERS: Tuple[str, ...]`** — Substrings identifying an ad-injected playlist:
`twitch-stitched-ad`, `stitched-ad`, `EXT-X-SCTE35`, `stitchedad`

**`DEFAULT_CONFIG`** — Config-file defaults: `player`, `custom_player`, `audio_only`, `low_latency`, `cache`, `quality`, `use_keyring`, `page_size=20`, `no_rich`, `debug`, `log_file`, `adblock=True`.

---

## 4. Configuration Files

```python
def get_config_path(custom_path: Optional[str] = None) -> Path
```
Resolves the config path. Precedence: `custom_path` arg → `TWITCH_CLI_CONFIG` env → `~/.config/twitch-cli/config.json`.

```python
def load_config(custom_path: Optional[str] = None) -> Tuple[Dict[str, Any], Path]
```
Loads the JSON config over `DEFAULT_CONFIG` defaults. Returns `(config_dict, resolved_path)`. Malformed JSON prints a warning and returns defaults; missing file is silent.

```python
def write_default_config(custom_path: Optional[str] = None) -> Path
```
Creates parent directories and writes `DEFAULT_CONFIG` as pretty-printed JSON. Returns the path written.

---

## 5. Data Types (Dataclasses)

### `Options`
Runtime execution options (populated from CLI args/config):
`player: str`, `custom_player: Optional[str]`, `token: Optional[str]`, `use_keyring: bool`, `audio_only: bool`, `low_latency: bool`, `cache: bool`, `quality: Optional[str]`, `debug: bool`, `page_size: int = 20`, `force_login: bool`, `adblock: bool = True`

### `Game`
| Field | Type |
|---|---|
| `id` | `str` |
| `name` | `str` |

- `Game.from_helix(item: Dict) -> Game` — factory for Helix payloads.

### `Stream`
| Field | Type |
|---|---|
| `user_id` | `str` |
| `user_login` | `str` |
| `user_name` | `str` |
| `game_name` | `str` |
| `viewer_count` | `int` |
| `started_at` | `Optional[str]` |
| `title` | `str` |

- `Stream.from_helix(item: Dict) -> Stream`

### `Vod`
| Field | Type |
|---|---|
| `id` | `str` |
| `title` | `str` |
| `channel` | `str` (login) |
| `display_name` | `str` |
| `duration` | `str` |
| `view_count` | `int` |
| `created_at` | `Optional[str]` |

- `Vod.from_helix(item: Dict) -> Vod` — Helix `videos` payload.
- `Vod.from_gql(item: Dict) -> Vod` — GQL `video` payload (reads `owner.login` / `owner.displayName`).

### `StreamInfo`
| Field | Type | Notes |
|---|---|---|
| `online` | `bool` | True if a stream object exists |
| `user_id` | `Optional[str]` | |
| `login` | `str` | |
| `display_name` | `str` | |
| `title` | `Optional[str]` | None if offline |
| `game` | `Optional[str]` | None if offline |

### `MasterVariant`
Parsed `#EXT-X-STREAM-INF` entry from an HLS master playlist:

| Field | Type | Source |
|---|---|---|
| `attrs` | `str` | Full `#EXT-X-STREAM-INF:` line |
| `uri` | `str` | Variant playlist URL |
| `bandwidth` | `int` | `BANDWIDTH` |
| `video` | `str` | `VIDEO` group ID |
| `name` | `str` | `NAME` attr, falling back to the matching `#EXT-X-MEDIA` group name |
| `height` / `width` | `int` | `RESOLUTION=WxH` |
| `fps` | `float` | `FRAME-RATE` |
| `codecs` | `str` | `CODECS` |

---

## 6. TokenStorage

Persists the OAuth token in the OS keyring (if available and enabled) or in `~/.config/twitch-cli/token` (mode `0600`). A legacy sibling file `.twitch_token` (next to the script) is read as a fallback and removed on delete.

```python
TokenStorage(use_keyring: bool = False)
```

| Method | Returns | Description |
|---|---|---|
| `get_token()` | `Optional[str]` | Keyring first (if enabled), then token file, then legacy file. `None` if unavailable. |
| `save_token(token: str)` | `None` | Keyring if enabled; falls back to file on keyring failure. File is chmod `0600`. |
| `delete_token()` | `None` | Removes keyring entry (if enabled), token file, and legacy file. All failures are swallowed/logged at debug. |

Keyring errors never raise — they log and fall back to file storage.

---

## 7. OAuth Helpers

```python
def generate_qr_code(url: str) -> Optional[str]
```
Returns an ASCII QR rendering of `url`, or `None` if `qrcode` is unavailable or generation fails.

```python
def get_oauth_token_interactive() -> Optional[str]
```
Interactive implicit-token flow:
1. Prints the authorization URL (`https://id.twitch.tv/oauth2/authorize` with `OAUTH_CLIENT_ID`, scopes, redirect URI) and a QR code when possible.
2. Prompts the user to paste the redirect URL.
3. Extracts the token via regex `access_token=([^&]+)`.

**Returns** the token string, or `None` on cancel/parse failure. Handles `EOFError`/`KeyboardInterrupt`.

---

## 8. TwitchPlayer (API Client)

The central client for Twitch GQL and Helix APIs. Uses a single shared `requests.Session` carrying `GQL_HEADERS`.

### Constructor

```python
TwitchPlayer(token: Optional[str] = None, use_keyring: bool = False)
```

**Token resolution order:** explicit `token` → `TWITCH_TOKEN` env → `TokenStorage`.

**Public instance attributes:**

| Attribute | Type | Description |
|---|---|---|
| `token` | `Optional[str]` | Active OAuth (app) token |
| `web_token` | `Optional[str]` | Browser `auth-token` cookie from `TWITCH_WEB_AUTH_TOKEN` |
| `auth_user` / `auth_user_id` | `Optional[str]` | Populated by `validate_token()` |
| `last_gql_error` | `str` | Last GQL error description (empty on success) |
| `token_failures` | `Dict[str, str]` | mode → failure reason, from playback-token attempts |
| `last_token_mode` | `str` | Auth mode that succeeded last (`"web-login"`, `"login"`, `"login-web"`, `"anonymous"`) |

---

### 8.1 Low-Level Request Layer

```python
_request(method: str, url: str, retries: int = MAX_RETRIES, **kwargs) -> requests.Response
```
Core HTTP method with automatic retries:
- **429:** sleeps per `Retry-After` header (default 2s), warns.
- **500/502/503/504:** exponential backoff `2^attempt`.
- **ConnectionError / Timeout:** exponential backoff; re-raises after final attempt.

Applies `timeout=REQUEST_TIMEOUT` unless overridden in `kwargs`.

```python
_gql_post(query: str, variables: Dict[str, Any],
          headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]
```
POSTs a GraphQL operation to `GQL_URL`. **Never raises** — all failures return `{}` and record a description in `last_gql_error` (HTTP errors, JSON decode errors, and GQL `errors` arrays are captured; payloads truncated to ~120–160 chars).

```python
_helix_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]
```
GETs `https://api.twitch.tv/helix/{endpoint}` with `Authorization: Bearer {token}` and the OAuth client ID. **Returns `None` on any failure** (no token, network error, 401, non-200, bad JSON). Requires a token; silently returns `None` without one.

---

### 8.2 Authentication

```python
validate_token() -> Optional[Dict[str, Any]]
```
`GET https://id.twitch.tv/oauth2/validate`. Returns the validation JSON (with `login`, `user_id`, etc.) and caches `auth_user`/`auth_user_id`, or `None` if no token / invalid / network failure.

```python
ensure_auth(interactive: bool = True, show_status: bool = False) -> bool
```
Full auth lifecycle:
1. If no token and `interactive`, runs the interactive OAuth flow and saves the result.
2. Validates the token; on failure **deletes the stored token** and (if interactive) re-runs login once.
3. Prints login status when `show_status=True`.

**Returns** `True` when a valid token is in place, `False` otherwise. Non-interactive mode never prompts.

```python
get_user_id() -> Optional[str]
```
Cached `auth_user_id`, else Helix `users` lookup. `None` on failure.

---

### 8.3 Live Streams

```python
get_stream_info(channel_name: str) -> Optional[StreamInfo]
```
GQL `user(login:) → stream { title, game { name } }`. Returns `None` if the channel doesn't exist; `StreamInfo.online` is `False` if offline.

```python
get_stream_playback_token(channel_name: str,
                          params: Optional[Dict[str, str]] = None) -> Tuple[Optional[str], Optional[str]]
```
GQL `streamPlaybackAccessToken`. `params` defaults to `AD_FREE_PARAM_SETS[0]` (android/mobile).

**Auth-mode rotation:** tries, in order —
1. `web-login` (web token + GQL client ID) — only if `web_token` set
2. `login` (app token + OAuth client ID)
3. `login-web` (app token + GQL client ID)
4. `anonymous`

Modes recorded in `_failed_token_modes` are skipped (except `anonymous`) so subsequent calls don't repeat known-bad flavors. On success sets `last_token_mode`; failures are recorded in `token_failures`.

**Returns** `(token_value, signature)` or `(None, None)`.

```python
@staticmethod
build_usher_url(channel_name: str, token: str, signature: str) -> str
```
Builds the usher master-playlist URL (`https://usher.ttvnw.net/api/channel/hls/{channel}.m3u8`) with URL-encoded token/sig and `allow_audio_only`, `allow_source`, codec negotiation (`av1,h265,h264`), and framerate inclusion flags.

```python
get_stream_url(channel_name: str) -> Optional[str]
```
Convenience: token + signature → usher URL. `None` if the token request fails.

---

### 8.4 VODs

| Method | Returns | Description |
|---|---|---|
| `get_vod_playback_token(vod_id: str)` | `(token, sig)` | GQL `videoPlaybackAccessToken`, fixed android/mobile params |
| `get_vod_info(vod_id: str)` | `Optional[Vod]` | GQL `video` query; `None` if not found |
| `get_vod_url(vod_id: str)` | `Optional[str]` | Usher VOD master URL (`https://usher.ttvnw.net/vod/{id}.m3u8`) |
| `get_user_by_login(login: str)` | `Optional[dict]` | Raw Helix `users?login=` record |
| `get_videos(user_id: str, first: int = 20, after: Optional[str] = None)` | `(List[Vod], Optional[str])` | Helix `videos` (archives, newest first). Second element is the pagination cursor. |
| `get_latest_vod(user_id: str)` | `Optional[Vod]` | `get_videos(first=1)` shorthand |

---

### 8.5 Clips

```python
get_clip_info(slug: str) -> Tuple[Optional[str], Optional[str]]
```
GQL `clip(slug:)` query. Sorts `videoQualities` by framerate (descending) and returns the highest-quality `sourceURL`.

**Returns** `(download_url, title)`; URL is `None` if no qualities exist. Title is still returned on failure to locate media.

---

### 8.6 Discovery & Browsing (Helix)

| Method | Returns | Description |
|---|---|---|
| `get_top_games(first: int = 100)` | `List[Game]` | `games/top` |
| `search_game(query: str)` | `Optional[Game]` | `search/categories` first; falls back to `difflib.get_close_matches` (cutoff 0.6) against the top 100 games |
| `get_followed_live_streams(user_id, first=20, after=None)` | `(List[Stream], cursor)` | `streams/followed` — **requires authenticated token** |
| `get_streams_by_game(game_id, first=20, after=None)` | `(List[Stream], cursor)` | `streams?game_id=…&type=live` |
| `search_channels(query, first=20)` | `List[dict]` | Raw Helix `search/channels` records |

All return empty results (`[]` / `None`) on API failure rather than raising.

---

## 9. Playlist / Ad-Blocking Helpers

Pure functions for parsing and selecting HLS master-playlist renditions.

```python
playlist_has_ads(playlist_text: str) -> bool
```
`True` if any `AD_MARKERS` substring appears.

```python
parse_master_variants(master: str) -> List[MasterVariant]
```
Parses `#EXT-X-STREAM-INF` entries. Friendly names are resolved from `#EXT-X-MEDIA` lines matched by `GROUP-ID` ↔ `VIDEO` attribute (Twitch convention).

```python
parse_master_media(master: str) -> List[str]
```
Returns all raw `#EXT-X-MEDIA:` lines (used to re-emit audio groups in rewritten masters).

```python
codec_family(variant: MasterVariant) -> str
```
Classifies by codec string: `"AV1"` (`av01`), `"HEVC"` (`hvc1`/`hev1`), `"H.264"` (`avc1`), `"audio"` (audio-only), `"?"` otherwise.

```python
variant_key(variant: MasterVariant) -> str
```
Stable rendition ID: `"{video_or_name}|{codec_family}"` — distinguishes the same resolution across codecs.

```python
is_audio_only_variant(variant: MasterVariant) -> bool
```
`VIDEO == "audio_only"` or name contains "audio only" (case-insensitive).

```python
best_variant(variants: List[MasterVariant]) -> Optional[MasterVariant]
```
Highest `(height, fps, bandwidth)` among non-audio variants (falls back to all variants if only audio exists).

```python
select_variant(variants: List[MasterVariant], quality: Optional[str],
               warn: bool = True) -> Optional[MasterVariant]
```
Quality-string selection:
- `"audio"`, `"audio_only"`, `"audioonly"` → first audio-only variant
- `""`, `"source"`, `"max"`, `"best"`, `"chunked"` → `best_variant`
- `"{height}p"` / `"{height}p{fps}"` (e.g. `720p`, `1080p60`) → exact/prefix match on `video` ID, friendly name, or pixel height, filtered by fps tolerance (±1); highest-bandwidth match wins
- No match → `best_variant`, with a UI warning unless `warn=False`
- Unparseable quality strings fall through to `best_variant`

---

## 10. HLSAdBlockProxy

Local HTTP server (bound to `127.0.0.1` on an ephemeral port) that sits between the player and Twitch's HLS infrastructure. It re-serves the master playlist (all renditions, preferred quality first) and scans variant playlists for ad markers. When ads are detected, it rotates playback tokens across `AD_FREE_PARAM_SETS` flavors — **only accepting a substitute flavor if it offers the same rendition at ≥ 70% of the requested bandwidth** (`MIN_BW_RATIO = 0.7`). If no flavor matches, the ad-injected playlist is passed through unchanged rather than degrading quality.

Class constants: `ROTATE_COOLDOWN = 4.0` (seconds between rotations), `MIN_BW_RATIO = 0.7`.

### Constructor

```python
HLSAdBlockProxy(twitch: TwitchPlayer, channel: str, quality: Optional[str] = None)
```

### Lifecycle

| Method | Returns | Description |
|---|---|---|
| `start()` | `bool` | Binds a `ThreadingHTTPServer` (daemon threads, silenced broken-pipe errors) and serves in a background daemon thread. `False` on bind failure. |
| `stop()` | `None` | Shuts down and closes the server. Idempotent. |
| `port` (property) | `int` | Bound port; `0` if not running. |
| `url()` | `str` | `http://127.0.0.1:{port}/master` — the URL to hand to the player. |

### HTTP Endpoints

| Route | Response | Description |
|---|---|---|
| `GET /master` | `200` HLS master, or `502` | Fetches masters for candidate token flavors, selects the flavor whose best rendition matches the requested `quality`, and rewrites the playlist so the chosen rendition is listed first. All renditions are preserved so players can still switch tracks. |
| `GET /variant?u={url}&n={video_id}&bw={min_bandwidth}` | `200` variant playlist, `400` if `u` missing | Serves the upstream variant playlist, filtering/rotating on ad markers. |
| anything else | `404` | `not found` |

All responses carry `Content-Type` (`application/vnd.apple.mpegurl` for playlists), `Content-Length`, and `Cache-Control: no-store`. Unexpected handler exceptions return `502 proxy error`. Client disconnects (`BrokenPipeError`, `ConnectionResetError`, `ConnectionAbortedError`) are logged at debug and ignored.

### Internal Methods (visible portion)

| Method | Description |
|---|---|
| `_fetch(url)` | GET via the shared Twitch session with the spoofed Android UA; returns body text on 200, else `None`. |
| `_master_url(preset)` | Returns the usher URL for a flavor index, caching `(token, signature)` per preset behind a lock. `None` if token acquisition fails. |
| `_fetch_master(preset)` | Fetches and validates a master playlist (must contain `#EXT-X-STREAM-INF`). |
| `_load_variants(preset)` | `(preset, master_text, List[MasterVariant])` or `None`; logs the rendition lineup at debug. |
| `build_master()` | Core `/master` logic — gathers masters across flavors (or the previously pinned one, with fallback to all flavors on failure), scores each by `(height, fps, -preset)` of its selected rendition, pins the winner, emits the rewritten playlist, and logs `Ad-block: serving '{label}'` once per rendition label. Returns `(http_status, body)`. |
| `_gather_masters(presets)` | *Truncated in source.* Concurrently gathers `(preset, master, variants)` tuples for the given preset indices (implementation uses a thread pool). |

Thread safety: token cache and preset pinning are guarded by an internal `threading.Lock`.

---

## 11. Utility Functions

| Function | Signature | Description |
|---|---|---|
| `parse_iso_timestamp` | `(value: Optional[str]) -> Optional[datetime]` | ISO-8601 parse; converts trailing `Z` to `+00:00`. `None` on empty/invalid. |
| `format_uptime` | `(started_at: Optional[str]) -> str` | `"2h 14m"`, `"5m"`, `"<1m"`, or `"live"` if the timestamp is in the future; `""` if unparseable. |
| `format_date` | `(value: Optional[str]) -> str` | `"%Y-%m-%d"`, or `""`. |
| `format_viewers` | `(value: Any) -> str` | Thousands-comma formatted int; falls back to `str(value)`. |
| `parse_twitch_url` | `(url: str) -> Tuple[Optional[str], Optional[str]]` | Classifies a URL → `("vod", id)` from `/videos/{id}`, `("clip", slug)` from `clips.twitch.tv/{slug}` or `/channel/clip/{slug}`, `("channel", login)` otherwise. `(None, None)` for unrecognized hosts/paths. |

### Terminal Color Utilities

```python
class C  # ANSI 256-color escape constants: R (reset), B (bold), D (dim),
         # RED, PURPLE, PINK, ORANGE, GREEN, YELLOW, BLUE, WHITE, GRAY

def c(text: Any, color: str) -> str
```
Wraps text in a color code; returns plain text when stdout is not a TTY or `NO_COLOR` is set (evaluated at import time as `COLOR_ENABLED`).

---

## 12. UI Helpers

All output helpers transparently switch between **Rich** rendering (when enabled via `set_rich_enabled(True)` and the `rich` package is importable) and plain ANSI fallback. Markup is escaped in Rich mode.

| Function | Description |
|---|---|
| `set_rich_enabled(enabled: bool)` | Globally toggles Rich rendering |
| `rich_enabled() -> bool` | Current Rich state |
| `hr() -> str` | `UI_WIDTH` (58) character rule |
| `title_bar(title, subtitle=None)` | Boxed section header (prints immediately) |
| `ui_banner()` | Startup banner (Rich panel or ASCII box) |
| `ui_section(title)` | Section rule |
| `ui_ok(msg)` / `ui_warn(msg)` / `ui_err(msg)` / `ui_note(msg)` | Status lines: `✔` / `▲` / `✖` / `▸` |
| `ui_kv(key, value)` | Aligned `key · value` line |
| `ui_table(headers, rows)` | Table; Rich `Table` or pipe-delimited text |
| `ui_prompt(prompt, default=None) -> Optional[str]` | Input prompt with optional default; `None` on EOF/Ctrl-C |
| `ui_spinner(message)` | Context manager — Rich live status, or a one-line note |

---

## 13. Error Handling & Retry Semantics

| Layer | Behavior |
|---|---|
| `_request` | Retries 429 (honor `Retry-After`), 5xx (exponential backoff), and network errors. Raises the last exception after exhausting `MAX_RETRIES`. |
| `_gql_post` | **Never raises.** Failures → `{}` + `last_gql_error`. |
| `_helix_get` / Helix-backed methods | **Never raise.** Failures → `None` / `[]`. 401 surfaces a user-facing "invalid or expired" error. |
| `get_stream_playback_token` | Rotates auth modes; failures cached in `_failed_token_modes`. `(None, None)` when all modes fail. |
| `ensure_auth` | Invalid tokens are deleted from storage before re-auth is attempted. |
| `TokenStorage` | All I/O/keyring errors are suppressed (debug-logged). |
| `HLSAdBlockProxy` | Handler exceptions → HTTP 502; fetch failures → graceful degradation (ads pass through rather than playback breaking). |

---

## 14. Usage Examples

### Basic programmatic use

```python
from twitch_player import TwitchPlayer, Options  # module name after install/copy

tw = TwitchPlayer()                 # token from env or storage
if tw.ensure_auth(interactive=True, show_status=True):
    info = tw.get_stream_info("shroud")
    if info and info.online:
        url = tw.get_stream_url("shroud")   # hand off to mpv/vlc
```

### VOD listing with pagination

```python
user = tw.get_user_by_login("shroud")
vods, cursor = tw.get_videos(user["id"], first=20)
while cursor:
    more, cursor = tw.get_videos(user["id"], first=20, after=cursor)
    vods.extend(more)
```

### Ad-blocking playback

```python
from twitch_player import HLSAdBlockProxy

proxy = HLSAdBlockProxy(tw, channel="shroud", quality="1080p60")
if proxy.start():
    try:
        print("Play this in your player:", proxy.url())
        ...  # block until playback ends
    finally:
        proxy.stop()
```

The player is pointed at `proxy.url()`; the proxy transparently handles token rotation and ad filtering for the lifetime of the session.

---

*End of documentation. Sections covering `HLSAdBlockProxy._gather_masters` internals, player launching, and the CLI argument parser reflect only what is visible in the supplied source.*
