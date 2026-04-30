# Quick Start Guide

Get streaming in 30 seconds.

## Installation

### Step 1: Install Dependencies

```bash
# Python dependencies
pip install requests

# Media player (choose one)
sudo apt install mpv      # Linux (recommended)
brew install mpv          # macOS
choco install mpv         # Windows
```

### Step 2: Run

```bash
python twitch_cli.py emiru
```

Done. That's it.

---

## Basic Usage

| Command | What it does |
|---------|--------------|
| `python twitch_cli.py hasanabi` | Play hasanabi's stream |
| `python twitch_cli.py xqc` | Play xQc's stream |
| `python twitch_cli.py --help` | Show all options |
| `python twitch_cli.py emiru -p vlc` | Use VLC instead of mpv |
| `python twitch_cli.py emiru -p flatpak-vlc` | Use Flatpak VLC |

### From URL

```bash
python twitch_cli.py https://www.twitch.tv/shroud
python twitch_cli.py https://www.twitch.tv/videos/1234567890  # VOD
```

---

## How It Works

```
1. You type: python twitch_cli.py willneff
2. App fetches stream URL from Twitch (Android mobile params)
3. Twitch returns ad-free HLS stream URL
4. mpv plays the stream
5. No ads. Ever.
```

### Why No Ads?

The tool impersonates an Android mobile client:
- `platform: "android"`
- `playerBackend: "mediaplayer"`
- `playerType: "mobile"`

Twitch serves ad-free streams to mobile clients. Your media player just plays the raw HLS URL.

---

## Common Issues

**"Module not found: requests"**
```bash
pip install requests
```

**"Player 'mpv' not found"**
```bash
sudo apt install mpv   # Linux
brew install mpv       # macOS
```

**"Channel not live"**
- Channel is offline
- Try a different channel

**"403 Forbidden"**
- Check channel name spelling
- Try full URL: `python twitch_cli.py https://twitch.tv/channelname`

---

## Tips

- **Best quality**: Don't specify quality - defaults to source
- **Lower bandwidth**: Player can switch video/audio quality during playback via its own controls
- **Fullscreen**: Press `f` in mpv/vlc

---

## Next Steps

- See `README.md` for full documentation
- Run `python twitch_cli.py --help` for all options
- Use `--login` for OAuth authentication (private streams)
