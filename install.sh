#!/bin/bash
# Twitch CLI Installer

echo "Twitch CLI Installer"
echo "===================="
echo ""

# Check Python version
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    exit 1
fi

echo "✓ Python 3 found"

# Check for pip
if ! command -v pip3 &> /dev/null && ! command -v pip &> /dev/null; then
    echo "Error: pip is required but not installed."
    exit 1
fi

echo "✓ pip found"

# Install requests
echo "Installing Python dependencies..."
pip3 install requests --user
echo "✓ Dependencies installed"

# Check for media players
echo ""
echo "Checking for media players..."

players_found=0

if command -v mpv &> /dev/null; then
    echo "  ✓ mpv found (recommended)"
    players_found=1
fi

if command -v vlc &> /dev/null; then
    echo "  ✓ vlc found"
    players_found=1
fi

if command -v ffplay &> /dev/null; then
    echo "  ✓ ffplay found"
    players_found=1
fi

if [ $players_found -eq 0 ]; then
    echo ""
    echo "Warning: No media players found!"
    echo "Please install one of the following:"
    echo "  - mpv (recommended): sudo apt install mpv"
    echo "  - vlc: sudo apt install vlc"
    echo "  - ffplay: sudo apt install ffmpeg"
    echo ""
fi

# Make scripts executable
chmod +x twitch_cli.py twitch

echo ""
echo "Installation complete!"
echo ""
echo "Usage:"
echo "  python3 twitch_cli.py <channel>     # Play a channel"
echo "  python3 twitch_cli.py --help        # Show help"
echo ""
echo "Examples:"
echo "  python3 twitch_cli.py emiru"
echo "  python3 twitch_cli.py https://twitch.tv/xqc"
echo "  python3 twitch_cli.py emiru -p vlc"
echo ""
