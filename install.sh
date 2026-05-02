#!/bin/bash
# Twitch CLI Installer

set -e

echo "Twitch CLI Installer"
echo "===================="
echo ""

# Detect package manager
if command -v apt &> /dev/null; then
  PKG_MGR="apt"
  PKG_INSTALL="sudo apt install"
elif command -v dnf &> /dev/null; then
  PKG_MGR="dnf"
  PKG_INSTALL="sudo dnf install"
elif command -v brew &> /dev/null; then
  PKG_MGR="brew"
  PKG_INSTALL="brew install"
else
  PKG_MGR="unknown"
  PKG_INSTALL="install via your package manager"
fi

# Check Python version
if ! command -v python3 &> /dev/null; then
  echo "✗ Python 3 required but not found"
  exit 1
fi
echo "✓ Python 3 found"

# Check for pip
if ! command -v pip3 &> /dev/null && ! command -v pip &> /dev/null; then
  echo "✗ pip required but not found"
  exit 1
fi
echo "✓ pip found"

# Install requests
echo "Installing Python dependencies..."
pip3 install requests --user 2>/dev/null || pip install requests --user
echo "✓ Dependencies installed"

# Check for media players
echo ""
echo "Checking for media players..."

players_found=0

if command -v mpv &> /dev/null; then
  echo "  ✓ mpv (recommended)"
  players_found=1
fi

if command -v vlc &> /dev/null; then
  echo "  ✓ vlc"
  players_found=1
fi

if command -v ffplay &> /dev/null; then
  echo "  ✓ ffplay"
  players_found=1
fi

if command -v flatpak &> /dev/null && flatpak list | grep -q org.videolan.VLC; then
  echo "  ✓ flatpak-vlc"
  players_found=1
fi

if [ $players_found -eq 0 ]; then
  echo ""
  echo "Warning: No media players found!"
  echo ""
  echo "Install one of the following:"
  if [ "$PKG_MGR" = "apt" ]; then
    echo "  sudo apt install mpv        # recommended"
    echo "  sudo apt install vlc        # alternative"
    echo "  sudo apt install ffmpeg     # ffplay"
  elif [ "$PKG_MGR" = "dnf" ]; then
    echo "  sudo dnf install mpv"
    echo "  sudo dnf install vlc"
    echo "  sudo dnf install ffmpeg"
  elif [ "$PKG_MGR" = "brew" ]; then
    echo "  brew install mpv"
    echo "  brew install vlc"
    echo "  brew install ffmpeg"
  else
    echo "  mpv, vlc, or ffmpeg"
  fi
  echo ""
fi

# Make scripts executable
chmod +x twitch_cli.py twitch

echo ""
echo "Installation complete!"
echo ""
echo "Quick start:"
echo "  python3 twitch_cli.py <channel>     # Play stream"
echo "  python3 twitch_cli.py --help        # Show all options"
echo ""
echo "Examples:"
echo "  python3 twitch_cli.py emiru"
echo "  python3 twitch_cli.py https://twitch.tv/xqc"
echo "  python3 twitch_cli.py emiru -p vlc"
echo ""
