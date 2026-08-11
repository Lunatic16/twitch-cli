<div align="center">

# 🎮 Twitch CLI Player

**An enhanced, single-file command-line interface for Twitch streaming and content discovery — ad-free, fast, and fully scriptable.**

[![Version](https://img.shields.io/badge/version-3.0.0-purple.svg)](https://github.com/Lunatic16)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](#-license)
[![Python](https://img.shields.io/badge/python-3.8+-brightgreen.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey.svg)](#)

</div>

---

Built for **ad-free stream playback** by impersonating official mobile client requests, with complete OAuth integration, key-value configuration, an interactive TUI browser, and OS keyring token storage support.

## 📖 Table of Contents

- [Key Features](#-key-features)
- [Installation & Dependencies](#-installation--dependencies)
- [Quick Start](#-quick-start)
- [Usage & Command Reference](#-usage--command-reference)
- [Configuration](#-configuration)
- [Usage Examples](#-usage-examples)
- [License](#-license)

---

## ✨ Key Features

| | |
| :--- | :--- |
| 🚫 **Ad-Free Live Streaming** | Fetches stream HLS master playlists using Android ExoPlayer client signatures (`Twitch/14.9.1`). |
| 🎨 **Rich Terminal UI & Fallback** | Automatically renders polished TUI tables, panels, and spinners using `rich` if installed, with a clean ANSI fallback for lightweight environments. |
| 🔍 **Full Discovery Capabilities** | Followed live streams, category/game search, channel search, and VOD browsing — all interactive and paginated. |
| ▶️ **Multiple Media Players** | Supports `mpv` (default), `vlc`, `flatpak-vlc`, `ffplay`, or a custom player command via `--custom-player`. |
| 🔐 **Flexible Authentication** | Twitch OAuth device flow with QR code output, file-based token storage, or OS keyring backend integration. |
| ⚙️ **Playback Tuning** | Dedicated flags for `--audio-only`, `--low-latency`, `--cache`, and quality bitrate hints. |

### 🔍 Discovery at a Glance
- **Followed Live Streams** — interactive paginated directory of followed channels currently live
- **Category / Game Search** — browse live streams by game or category query
- **Channel Search & VOD Browsing** — search channels and inspect historical VOD archives or live fallback options

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
# Rich Terminal UI formatting
pip install rich

# Terminal QR Code generation for seamless phone OAuth login
pip install qrcode

# System keyring storage for OAuth tokens (KWallet, Secret Service, Keychain)
pip install keyring
```

---

## 🚀 Quick Start

**1. Make the script executable**

```bash
chmod +x twitch_cli.py
```

**2. Authenticate with Twitch**

```bash
./twitch_cli.py --login
```
> Follow the terminal prompt, scan the QR code or click the URL, authorize, and paste the resulting redirect URL back into the CLI.

**3. Play a live channel**

```bash
./twitch_cli.py emiru
```

**4. Launch the interactive menu**

```bash
./twitch_cli.py --interactive
```

---

## 🧭 Usage & Command Reference

```text
twitch_cli.py [CHANNEL_OR_URL] [options]
```

### Core Options

| Flag / Option | Description |
| :--- | :--- |
| `CHANNEL` | Target channel login name, channel URL, VOD URL, or clip URL. |
| `-p, --player PLAYER` | Select media player (`mpv`, `vlc`, `flatpak-vlc`, `ffplay`). Default: `mpv`. |
| `--custom-player CMD` | Custom command invocation. Use `{url}` placeholder (e.g. `vlc {url}`). |
| `--token TOKEN` | Pass an explicit Twitch OAuth token. |
| `--login` | Launch OAuth interactive login flow. |
| `--logout` | Purge stored OAuth tokens from disk and system keyring. |
| `--config PATH` | Load custom JSON configuration path. |
| `--write-default-config` | Generate default configuration file at `~/.config/twitch-cli/config.json`. |

### Content Discovery & Browsing

| Flag / Option | Description |
| :--- | :--- |
| `--followed` | Open interactive directory of followed live channels. |
| `--search GAME` | Search live streams in a category/game. |
| `--find CHANNEL` | Search for channels matching a search query. |
| `--vods CHANNEL` | List and play recent VODs from a specified channel. |
| `--interactive` | Launch full interactive TUI selection menu. |
| `--list-players` | Display availability and status of installed media players. |

### Playback Parameters

| Flag / Option | Description |
| :--- | :--- |
| `--audio-only` | Play stream audio track without rendering video. |
| `--low-latency` | Tune player flags for ultra-low buffering (`--profile=low-latency` for mpv). |
| `--cache` | Enable player stream caching. |
| `--quality QUALITY` | Quality hint (`max`, `min`, `source`, or resolution like `720p`, `1080p`). |

### Advanced & Utility Flags

| Flag / Option | Description |
| :--- | :--- |
| `--keyring` | Force use of system keyring service for token storage. |
| `--no-keyring` | Force file-based token storage (`~/.config/twitch-cli/token`). |
| `--no-rich` | Force disable Rich UI formatting and use plain ANSI output. |
| `--debug` | Enable verbose debug logging. |
| `--log-file FILE` | Append log entries to a designated file. |
| `--limit N` | Set page size for list menus (default: `20`). |
| `--completion SHELL` | Output shell completion scripts (`bash`, `zsh`, `fish`). |
| `--self-test` | Execute built-in diagnostic and URL parser unit tests. |

---

## ⚙️ Configuration

Settings can be saved to `~/.config/twitch-cli/config.json` manually or generated via `--write-default-config`.

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
  "log_file": null
}
```

### Environment Variables

| Variable | Description |
| :--- | :--- |
| `TWITCH_TOKEN` | Direct override for Twitch OAuth access token. |
| `TWITCH_CLI_CONFIG` | Custom file path for configuration file. |
| `TWITCH_CLI_KEYRING` | Set to `1`, `true`, or `on` to force system keyring usage. |
| `NO_COLOR` | Standard flag to disable terminal color formatting. |

---

## 💡 Usage Examples

```bash
# Play a live channel using low latency settings in mpv
./twitch_cli.py xqc --low-latency

# Watch a stream in audio-only mode
./twitch_cli.py emiru --audio-only

# Play a specific VOD by URL
./twitch_cli.py https://www.twitch.tv/videos/1234567890

# Play a clip
./twitch_cli.py https://clips.twitch.tv/SampleClipSlug

# Search and browse streams in the "Just Chatting" category
./twitch_cli.py --search "Just Chatting"

# Use VLC via Flatpak for playback
./twitch_cli.py shroud -p flatpak-vlc

# Generate Zsh completion script
./twitch_cli.py --completion zsh > ~/.zsh/completion/_twitch_cli.py
```

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.

<div align="center">

Made with ❤️ for the terminal

</div>
