<h1 align="center"><a href="https://github.com/topics/twitch">Twitch CLI Player<br><img height="150" alt="Twitch" src="https://raw.githubusercontent.com/github/explore/refs/heads/main/topics/twitch/twitch.png"></a></h1>
# Twitch CLI Player

A command-line Twitch client for ad-free streaming using Android platform impersonation. Play live streams and VODs directly from your terminal with your choice of media player.

## Key Features

- **Ad-free playback** - Uses Android mobile platform impersonation to bypass ads. You may get one 15s ad once then no more ads after that. 
- **Multiple player support** - Works with mpv, VLC, Flatpak VLC and ffplay
- **Live streams & VODs** - Supports both live channels and video-on-demand
- **OAuth authentication** - Optional login for extended features
- **Followed Channels**: List and play live streams from your followed channels.
- **Category Search**: Search for and play live streams by game/category.
- **Stream info display** - Shows stream title, channel, and game category
- **Colored terminal output** - Beautiful ANSI-colored banners and help text

## Tech Stack

- **Language**: Python 3.7+
- **HTTP Client**: requests
- **Media Players**: mpv (recommended), VLC, Flatpak VLC, ffplay
- **Authentication**: OAuth 2.0 (Implicit Grant)
- **API**: Twitch GraphQL & Helix API
- **Networking**: `requests`
- **Optional**: `qrcode` (for QR login generation)

## Prerequisites

Before installing, ensure you have:

- **Python 3.7+** - Download from [python.org](https://python.org)
- **pip** - Python package manager (usually bundled with Python)
- **A media player** - One of the following:
  - `mpv` (recommended) - [mpv.io](https://mpv.io)
  - `vlc` - [videolan.org](https://videolan.org)
  - `ffplay` - Part of [ffmpeg](https://ffmpeg.org)
  - `flatpak-vlc` - [flatpak-vlc](https://flathub.org/en/apps/org.videolan.VLC)

## Installation

### Quick Install (30 seconds)

```bash
# Clone or download the repository
cd twitch-cli

# Install Python dependencies
pip install requests qrcode

# Run the installer (optional, makes scripts executable)
chmod +x install.sh twitch_cli.py twitch
./install.sh
```

### Install Media Player

**Linux (Ubuntu/Debian):**
```bash
sudo apt install mpv      # Recommended
sudo apt install vlc      # Alternative
sudo apt install ffmpeg   # For ffplay
```
**Linux (Fedora):**
```bash
sudo dnf install mpv      # Recommended
sudo dnf install vlc      # Alternative
sudo dnf install ffmpeg   # For ffplay
```
**Linux (Flatpak):**
```bash
flatpak install flathub org.videolan.VLC 
```

**macOS (Homebrew):**
```bash
brew install mpv
brew install vlc
brew install ffmpeg
```

**Windows (Chocolatey):**
```bash
choco install mpv
choco install vlc
choco install ffmpeg
```

## Usage

### Basic Commands

```bash
# Play a channel by name
python twitch_cli.py STREAMER

# Login to access your followed channels
python twitch_cli.py --login

# Play from URL
python twitch_cli.py https://www.twitch.tv/emiru

# Search live streams by game
python twitch_cli.py --search "GAME"

# List followed live streams
python twitch_cli.py --followed

# Use specific player
python twitch_cli.py STREAMER -p vlc

# Play VOD by ID
python twitch_cli.py https://www.twitch.tv/videos/1234567890

# Show help with colors
python twitch_cli.py --help
```

### Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `CHANNEL` | Channel name or Twitch URL | Required |
| `-p, --player PLAYER` | Media player (mpv, vlc, ffplay, flatpak-vlc) | mpv |
| `--list-players` | Show available players | - |
| `--login` | Force OAuth re-login | - |
| `--logout` | Clear stored token | - |
| `--followed` | List and play live followed channels | - |
| `--search "GAME"` | Search and play live streams for a game | - |
| `--custom-player CMD` | Custom player command with `{url}` placeholder | - |
| `--token TOKEN` | Use provided OAuth token | - |

### Examples

```bash
# Play xQc's stream with default mpv player
python twitch_cli.py xqc

# Play Emiru with VLC
python twitch_cli.py nmplol -p vlc

# Play with custom mpv settings (fullscreen, no border)
python twitch_cli.py shroud --custom-player "mpv --fullscreen --no-border {url}"

# Force OAuth login (for private streams)
python twitch_cli.py --login

# Clear saved OAuth token
python twitch_cli.py --logout

# List all available player options
python twitch_cli.py --list-players
```

## Architecture

### How It Works

```
User Input (channel name or URL)
       ↓
Parse URL → Extract channel/VOD ID
       ↓
Twitch GraphQL API (Android mobile params)
       ↓
Fetch stream playback token + signature
       ↓
Generate HLS URL with auth params
       ↓
Launch media player with stream URL
       ↓
Ad-free playback in mpv/vlc/ffplay
```

### Platform Impersonation

The tool mimics an Android mobile client when requesting stream URLs:

```python
params = {
    "platform": "android",
    "playerBackend": "mediaplayer",
    "playerType": "mobile"
}
```

This causes Twitch to serve:
- Ad-free stream URLs (no mid-roll ads)
- Mobile-optimized bitrates
- No ad SDK required on client side

### Key Components

**`twitch_cli.py`** - Main script (~750 lines)
- `TwitchPlayer` class - Handles API communication
- `get_stream_info()` - Fetches stream title, game, channel info
- `get_stream_playback_token()` - Gets authenticated playback token
- `get_stream_url()` / `get_vod_url()` - Generates final HLS URL
- `get_player_args()` - Configures media player command

**Authentication Flow:**
1. Check for stored OAuth token (`.twitch_token`)
2. If missing, generate QR code for S0undTV OAuth
3. User scans QR with phone, pastes redirect URL
4. Token extracted and saved locally
5. Token used for subsequent API requests

**Player Configuration:**

| Player | Command Flags | Title Support |
|--------|---------------|---------------|
| mpv | `--vo=gpu --hwdec=auto --cache=yes` | `--force-media-title` |
| vlc | `--intf=rc` | `--meta-title` |
| ffplay | `-autoexit -headers` | `-window_title` |

MPV configuration with ~/.config/mpv/mpv.conf
```
# Start with a manageable default size
autofit=70%
# Ensure the window is always created
force-window=yes
# Set volume to 70% on startup
volume=70
```

### Directory Structure

```
twitch-cli/
├── twitch_cli.py      # Main CLI script (746 lines)
├── twitch             # Wrapper script for direct execution
├── install.sh         # Installer with dependency checks
├── README.md          # This documentation
├── QUICKSTART.md      # Quick start guide
├── TWITCH_API.md      # Twitch Helix API Integration
└── .twitch_token      # Stored OAuth token (after login)
```

## Stream Info Display

When playing a stream, the CLI displays:

```
╭────────────────────────────────────────────────╮
│ Twitch CLI Player — Ad-free streaming          │
╰────────────────────────────────────────────────╯

Fetching stream for willneff...

Stream: MOBIES - willneff | Just Chatting
Player: mpv

Starting playback...
```

The stream info includes:
- **Title** - Current stream title from Twitch
- **Channel** - Streamer's username
- **Game** - Category/game being played

## OAuth Authentication

### When OAuth is Required

- Private/subscriber-only streams
- Age-restricted content
- Higher API rate limits
- Chat integration (future feature)

### How to Login

```bash
# Force login
python twitch_cli.py --login

# Interactive flow:
# 1. QR code displayed in terminal
# 2. Scan with phone
# 3. Paste redirect URL
# 4. Token saved to .twitch_token
```

### Token Storage

- **Location**: `.twitch_token` in the script directory
- **Format**: Plain text OAuth token
- **Security**: Local file, user permissions apply

```bash
# View stored token
cat .twitch_token

# Delete token (logout)
python twitch_cli.py --logout
rm .twitch_token
```

## Troubleshooting

### Common Errors

**`ModuleNotFoundError: No module named 'requests'`**
```bash
pip install requests
```

**`Player 'mpv' not found`**
```bash
# Install mpv
sudo apt install mpv      # Ubuntu/Debian
sudo dnf install mpv      # Fedora
brew install mpv          # macOS
choco install mpv         # Windows
```

**`Channel not found` or `404 Not Found`**
- Channel is offline (not live)
- Check spelling of channel name
- Try full URL: `python twitch_cli.py https://twitch.tv/channelname`

**`HTTP 403 Forbidden`**
- OAuth token expired - run `--logout` then `--login`
- Channel has subscriber-only mode
- Geographic restrictions apply

**Stream buffering or stuttering**
- Lower quality: Player can switch video/audio quality during playback via its own controls
- Check network connection
- Try different player: `-p vlc`

**Colors not displaying correctly**
- Ensure terminal supports ANSI escape codes
- Try a modern terminal emulator (alacritty, kitty, iTerm2)
- Windows: Use Windows Terminal or WSL

## Comparison with Alternatives

| Feature | Twitch CLI | Twitch Desktop | Twitch Web |
|---------|------------|----------------|------------|
| Ad-free | ✅ Yes | ❌ No | ❌ No |
| Resource usage | ~50MB | ~500MB+ | ~300MB+ |
| Player choice | Any | Built-in only | Built-in only |
| Customization | Full | Limited | None |
| Offline viewing | Manual | No | No |

## Legal Notice

This tool is for **personal use only**. Key points:

1. **Respect streamers** - Consider subscribing if you enjoy their content
2. **No redistribution** - Do not redistribute stream content
3. **Terms of Service** - Use may violate Twitch ToS; use at your own risk
4. **Educational purpose** - Provided as a learning tool for API integration

## Acknowledgments

- Technique inspired by **[S0undTV](https://github.com/S0und/S0undTV)** Android client
- Uses **Twitch GraphQL & Helix API** for stream metadata
- OAuth flow based on Twitch's official documentation
