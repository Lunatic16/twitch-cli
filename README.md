<div align="center">

# 🎮 Twitch CLI Player

**A single-file command-line player for Twitch with a built-in ad-filtering proxy — ad-free, fast, and fully scriptable.**

[![Version](https://img.shields.io/badge/version-3.1.0-purple.svg)](https://github.com/Lunatic16)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](#-license)
[![Python](https://img.shields.io/badge/python-3.8+-brightgreen.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)](#)

</div>

---

`proxy-twitch-cli.py` plays Twitch streams, VODs and clips in your own media player. It requests playback tokens the way the official mobile client does, runs a lightweight local HLS proxy to filter mid-roll ads, and adds OAuth login, an interactive terminal browser, and optional OS keyring token storage.

---

## ✨ Key Features

| | |
| :--- | :--- |
| 🚫 **Ad-Free Live Streaming** | Fetches stream HLS master playlists using Android ExoPlayer client signatures (`Twitch/14.9.1`) and filters mid-roll ads through a local proxy (on by default). |
| 🖥️ **Source / 1440p60 Streams** | Picks up streams that offer 1440p60 or other high-quality source renditions when a browser session token is provided. See [Higher Quality Streams](#-higher-quality-streams-source--1440p60). |
| 🎚️ **Switchable Tracks** | The player receives every video rendition at or below your chosen quality plus the audio-only track, so you can switch live in mpv. |
| 🎨 **Rich Terminal UI & Fallback** | Renders polished tables, panels and spinners using `rich` if installed, with a clean ANSI fallback for lightweight environments. |
| 🔍 **Discovery** | Followed live streams, category/game browsing, channel search, and VOD browsing — interactive and paginated. |
| ▶️ **Multiple Media Players** | Supports `mpv` (default), `vlc`, `flatpak-vlc`, `ffplay`, or a custom player command via `--custom-player`. |
| 🔐 **Flexible Authentication** | Twitch OAuth login with QR code output, file-based token storage, or OS keyring integration. |
| ⚙️ **Playback Tuning** | Flags for `--audio-only`, `--low-latency`, `--cache`, and quality selection (`source`, `1440p60`, `720p60`, `audio`, …). |

### 🔍 Discovery at a Glance
- **Followed Live Streams** — interactive paginated directory of followed channels currently live
- **Category / Game Browsing** — browse live streams by game or category query
- **Channel Search & VOD Browsing** — search channels and inspect past VODs, with a live fallback when a channel is offline

---

## 📦 Installation & Dependencies

### Prerequisites

- **Python 3.8+**
- **A media player** — `mpv` recommended, or `vlc` / `ffplay`

### Required Python Package

```bash
pip install requests
```

### Optional Dependencies

```bash
# Rich terminal UI formatting
pip install rich

# Terminal QR code generation for seamless phone OAuth login
pip install qrcode

# System keyring storage for OAuth tokens (KWallet, Secret Service, Keychain)
pip install keyring
```

The ad-filtering proxy uses only the Python standard library — there is nothing extra to install for it.

---

## 🚀 Quick Start

**1. Make it executable**

```bash
chmod +x proxy-twitch-cli.py
```

**2. Authenticate with Twitch**

```bash
./proxy-twitch-cli.py --login
```
> Follow the terminal prompt, scan the QR code or open the URL, authorize, and paste the resulting redirect URL back into the CLI.

**3. Play a live channel**

```bash
./proxy-twitch-cli.py emiru
```

**4. Launch the interactive menu**

```bash
./proxy-twitch-cli.py --interactive
```

---

## 🖥️ Higher Quality Streams (Source / 1440p60)

Some channels stream above 1080p60 (for example a 1440p60 source). Twitch only offers those renditions to a logged-in **web** session, so without one you will only see up to 720p60 even though the stream has more. The login created by `--login` is *not* accepted for playback tokens (Twitch answers `401 Unauthorized`), so these streams need the browser session token as well.

**1. Copy your browser's `auth-token` cookie**

In your browser, while logged in to twitch.tv: open DevTools → *Application* (Chrome) or *Storage* (Firefox) → *Cookies* → `https://www.twitch.tv` → copy the value of the cookie named `auth-token`.

**2. Export it**

```bash
export TWITCH_WEB_AUTH_TOKEN='paste-the-value-here'
```

Add that line to your shell profile (e.g. `~/.bashrc`) to keep it across sessions.

**3. Check what the stream offers**

```bash
./proxy-twitch-cli.py CHANNEL --list-qualities
```

For each token flavor (`android/mobile`, `web/frontpage`, `web/embed`, `ios/ios`, `web/site`) this prints every rendition (VIDEO id, name, resolution, FPS, bitrate, codecs), which token mode produced it (`web-login`, `login`, or `anonymous`), whether `TWITCH_WEB_AUTH_TOKEN` is set, and the reason any token attempt failed. It exits without starting the player.

**4. Play**

```bash
./proxy-twitch-cli.py CHANNEL              # best available (source)
./proxy-twitch-cli.py CHANNEL -q 1440p60   # a specific rendition
./proxy-twitch-cli.py CHANNEL -q 720p60    # lower, if your machine struggles
```

### How it behaves

- **Token order:** `TWITCH_WEB_AUTH_TOKEN` → stored OAuth login → anonymous. If a mode fails, the next is tried, so a missing or expired token falls back to the lower-quality listing rather than failing.
- **Best rendition wins:** all token flavors are queried at once and the one that best matches your `--quality` (highest resolution/framerate for `source`/`best`) is used. If the quality you ask for isn't offered, you get a warning and the best available.
- **Track switching:** the player receives your chosen rendition plus every rendition below it and the audio-only track. In mpv, press `_` to cycle video tracks and `#` to cycle audio tracks. Renditions above your choice are hidden, so `-q 720p60` will not offer 1440p.
- **Codecs:** requests include `supported_codecs=av1,h265,h264`, so HEVC/AV1 renditions are listed when a stream offers them. Make sure your player and hardware can decode them; if playback stutters, choose a lower quality.
- **Ads at high quality:** the ad-filtering proxy only swaps to another token flavor if it offers the *same* quality. Ad-free flavors often lack 1440p60, in which case a one-time warning is shown and the ad break plays through rather than dropping your quality. A lower `--quality` usually gives the filter more to work with.
- **Direct launch:** playback starts immediately; no track table is printed. Use `--list-qualities` when you want the listing.

> ⚠️ The `auth-token` cookie is a full login to your Twitch account. Keep it out of config files, scripts, logs and issue reports. Logging out of twitch.tv in your browser invalidates it; copy a fresh one if 1440p disappears from `--list-qualities`.

---

## 🛡️ How Ad Blocking Works

With ad blocking on (the default), the player is pointed at a small HTTP server on `127.0.0.1` instead of Twitch directly:

1. The proxy fetches the master playlist and serves the player your chosen rendition, plus lower renditions and audio-only.
2. Every media playlist the player requests is scanned for stitched-ad markers.
3. If ads are found, the proxy cycles through playback-token flavors (`android`, `web`, `ios`, …) and uses one only if it offers the **same** quality at no less than 70% of the bitrate.
4. If no clean flavor matches, the ads pass through unchanged rather than lowering your quality.

Use `--no-adblock` to connect to Twitch directly, or set `"adblock": false` in the config file.

---

## 🧭 Usage & Command Reference

```text
proxy-twitch-cli.py [CHANNEL_OR_URL] [options]
```

### Playback

| Flag / Option | Description |
| :--- | :--- |
| `CHANNEL` | Channel login name, or a twitch.tv channel, VOD, or clip URL. |
| `-p, --player PLAYER` | Media player (`mpv`, `vlc`, `flatpak-vlc`, `ffplay`). Default: `mpv`. |
| `--custom-player CMD` | Custom player command. Use `{url}` as the URL placeholder (e.g. `vlc {url}`). |
| `-q, --quality QUALITY` | Rendition to start on: `source` / `max` / `best`, `audio`, or a resolution such as `1440p60`, `1080p60`, `720p`. If the stream doesn't offer it, you get a warning and the best available. |
| `-a, --audio-only` | Play the audio track without rendering video. |
| `-l, --low-latency` | Tune player flags for low buffering (`--profile=low-latency` for mpv). |
| `--cache` | Enable extra player buffering. |
| `--adblock` / `--no-adblock` | Toggle the local ad-filtering proxy. On by default. |

### Authentication

| Flag / Option | Description |
| :--- | :--- |
| `--login` | Start the interactive OAuth login before playing. |
| `--logout` | Clear the stored OAuth token and exit. |
| `--token TOKEN` | Use an explicit OAuth token (defaults to `$TWITCH_TOKEN` or the stored token). |
| `--keyring` | Store the token in the system keyring instead of a file. |

### Browsing & Discovery

| Flag / Option | Description |
| :--- | :--- |
| `-f, --followed` | Browse live channels you follow. |
| `-s, --game GAME` | Browse live streams for a game/category. |
| `--find QUERY` | Search channels. |
| `--vods CHANNEL` | Browse and play a channel's VODs. |
| `-i, --interactive` | Open the interactive menu (also opens when no channel is given). |
| `--list-qualities` | Print the renditions each token flavor offers for `CHANNEL`, which token mode was used, and why any attempt failed, then exit. |

### Misc

| Flag / Option | Description |
| :--- | :--- |
| `--list-players` | Show supported players and whether they're installed. |
| `--config PATH` | Use a specific config file. |
| `--no-rich` | Disable Rich output and use plain ANSI. |
| `--debug` | Verbose debug logging. |
| `--log-file PATH` | Write logs to a file. |
| `--version` | Show the version and exit. |

---

## ⚙️ Configuration

Settings are read from `~/.config/twitch-cli/config.json` (or the path given by `--config` or `$TWITCH_CLI_CONFIG`). The file is optional; create it by hand with any of the keys below. Command-line flags take precedence over the file.

### Sample Configuration

```json
{
  "player": "mpv",
  "custom_player": null,
  "audio_only": false,
  "low_latency": true,
  "cache": false,
  "quality": "source",
  "use_keyring": false,
  "page_size": 20,
  "no_rich": false,
  "debug": false,
  "log_file": null,
  "adblock": true
}
```

### Environment Variables

| Variable | Description |
| :--- | :--- |
| `TWITCH_TOKEN` | Override the Twitch OAuth access token. |
| `TWITCH_WEB_AUTH_TOKEN` | Your twitch.tv browser `auth-token` cookie; unlocks source / 1440p60 renditions. See [Higher Quality Streams](#-higher-quality-streams-source--1440p60). |
| `TWITCH_CLI_CONFIG` | Custom path for the configuration file. |
| `NO_COLOR` | Standard flag to disable terminal color formatting. |

### Token Storage

The OAuth token is stored in `~/.config/twitch-cli/token` (mode `600`), or in the system keyring when `--keyring` / `"use_keyring": true` is set and the `keyring` package is installed.

---

## 💡 Usage Examples

```bash
# Play a live channel using low latency settings in mpv
./proxy-twitch-cli.py xqc --low-latency

# Watch a stream in audio-only mode
./proxy-twitch-cli.py emiru --audio-only

# Play a specific VOD by URL
./proxy-twitch-cli.py https://www.twitch.tv/videos/1234567890

# Play a clip
./proxy-twitch-cli.py https://clips.twitch.tv/SampleClipSlug

# Browse live streams in the "Just Chatting" category
./proxy-twitch-cli.py --game "Just Chatting"

# Browse live channels you follow
./proxy-twitch-cli.py --followed

# Use VLC via Flatpak for playback
./proxy-twitch-cli.py shroud -p flatpak-vlc

# Disable the ad-filtering proxy and connect directly
./proxy-twitch-cli.py xqc --no-adblock

# See every rendition a channel offers (needs TWITCH_WEB_AUTH_TOKEN for source/1440p60)
./proxy-twitch-cli.py CHANNEL --list-qualities

# Play a specific rendition
./proxy-twitch-cli.py CHANNEL -q 1440p60
```

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.

<div align="center">

Made with ❤️ for the terminal

</div>
