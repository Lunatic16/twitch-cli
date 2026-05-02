#!/usr/bin/env python3
"""
Twitch CLI Player - Play Twitch streams without ads
Uses OAuth authentication and platform impersonation (S0undTV technique)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    print("\033[31mError: requests library required. Install with: pip install requests\033[0m")
    sys.exit(1)

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

# Twitch credentials
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

AVAILABLE_PLAYERS = {
    "mpv": "MPV - Lightweight media player (recommended)",
    "vlc": "VLC - Cross-platform media player",
    "flatpak-vlc": "VLC via Flatpak (org.videolan.VLC)",
    "ffplay": "FFplay - Simple FFplay-based player",
}


# ANSI colors
class C:
    R = "\033[0m"
    B = "\033[1m"
    D = "\033[2m"
    PURPLE = "\033[38;5;91m"
    PINK = "\033[38;5;207m"
    ORANGE = "\033[38;5;214m"
    GREEN = "\033[38;5;84m"
    YELLOW = "\033[38;5;220m"
    BLUE = "\033[38;5;75m"
    WHITE = "\033[38;5;255m"
    GRAY = "\033[38;5;245m"
    BG_PURPLE = "\033[48;5;63m"


def c(t, col): return f"{col}{t}{C.R}"


def print_banner():
    print()
    print(f"  {c('╭────────────────────────────────────────────────╮', C.PURPLE)}")
    print(f"  {c('│', C.PURPLE)} {c('Twitch CLI Player', C.B)} {c('—', C.D)} {c('Ad-free streaming', C.GREEN)}    {c('│', C.PURPLE)}")
    print(f"  {c('╰────────────────────────────────────────────────╯', C.PURPLE)}")
    print()


class TokenStorage:
    def __init__(self):
        self.token_file = os.path.join(os.path.dirname(__file__), ".twitch_token")

    def get_token(self):
        if os.path.exists(self.token_file):
            with open(self.token_file, "r") as f:
                return f.read().strip()
        return None

    def save_token(self, token):
        with open(self.token_file, "w") as f:
            f.write(token)

    def delete_token(self):
        if os.path.exists(self.token_file):
            os.remove(self.token_file)


def generate_qr_code(url):
    if not HAS_QRCODE:
        return None
    try:
        qr = qrcode.QRCode(version=1, box_size=1, border=1)
        qr.add_data(url)
        qr.make()
        return qr.print_ascii(tty=False)
    except:
        return None


def get_oauth_token_interactive():
    print(f"\n  {c('╭────────────────────────────────────────────╮', C.PINK)}")
    print(f"  {c('│', C.PINK)} {c('Twitch OAuth Login', C.B)} {c('│', C.PINK)}")
    print(f"  {c('╰────────────────────────────────────────────╯', C.PINK)}")

    auth_url = (
        f"https://id.twitch.tv/oauth2/authorize"
        f"?client_id={OAUTH_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=token"
        f"&scope={OAUTH_SCOPES.replace(' ', '+')}"
    )

    print(f"\n  {c('Scan QR code with phone:', C.B)}")
    print(f"  {c(auth_url, C.GRAY)}\n")

    qr_ascii = generate_qr_code(auth_url)
    if qr_ascii:
        print(qr_ascii)

    print(f"\n  {c('After logging in, paste redirect URL:', C.B)}")
    redirect_url = input("  > ").strip()

    # The token is typically in the URL fragment (after #)
    match = re.search(r'access_token=([^&]+)', redirect_url)
    if match:
        token = match.group(1)
        print(f"\n  {c('✓', C.GREEN)} Got access token: {c(token[:20] + '...', C.GREEN)}")
        return token

    print(f"  {c('✗', C.YELLOW)} Error: Could not extract token")
    return None


class TwitchPlayer:
    def __init__(self, token=None):
        self.token_storage = TokenStorage()
        self.token = token or self.token_storage.get_token()
        self.session = requests.Session()
        self.session.headers.update(GQL_HEADERS)

    def ensure_auth(self):
        if not self.token:
            print(f"  {c('No OAuth token found.', C.YELLOW)}")
            self.token = get_oauth_token_interactive()
            if self.token:
                self.token_storage.save_token(self.token)
                self.session.headers["Authorization"] = f"OAuth {self.token}"
                return True
        return True

    def get_stream_info(self, channel_name):
        gql_session = requests.Session()
        gql_session.headers.update(GQL_HEADERS)
        gql_session.headers["Referer"] = "https://www.twitch.tv/"

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

        response = gql_session.post(GQL_URL, json={
            "query": query,
            "variables": {"channelName": channel_name}
        })

        if response.status_code != 200:
            return None

        result = response.json()
        if "data" in result and result["data"]["user"]:
            user = result["data"]["user"]
            stream = user.get("stream")
            if stream:
                return {
                    "channel": user["login"],
                    "display_name": user["displayName"],
                    "title": stream.get("title", "Live"),
                    "game": stream.get("game", {}).get("name") if stream.get("game") else None,
                }
        return None

    def get_stream_playback_token(self, channel_name):
        gql_session = requests.Session()
        gql_session.headers.update(GQL_HEADERS)
        gql_session.headers["Referer"] = "https://www.twitch.tv/"

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
                "playerType": "mobile"
            }
        }

        response = gql_session.post(GQL_URL, json={"query": query, "variables": variables})

        if response.status_code != 200:
            print(f"  {c('✗', C.YELLOW)} Error fetching token: {response.status_code}")
            return None, None

        result = response.json()
        if "data" in result and result["data"]["streamPlaybackAccessToken"]:
            token_data = result["data"]["streamPlaybackAccessToken"]
            return token_data["value"], token_data["signature"]

        return None, None

    def get_stream_url(self, channel_name):
        token, signature = self.get_stream_playback_token(channel_name)

        if not token or not signature:
            return None

        import urllib.parse
        encoded_token = urllib.parse.quote(token, safe='')
        encoded_sig = urllib.parse.quote(signature, safe='')

        return (
            f"https://usher.ttvnw.net/api/channel/hls/{channel_name}.m3u8"
            f"?token={encoded_token}"
            f"&sig={encoded_sig}"
            f"&player=twitchweb"
            f"&allow_audio_only=true"
            f"&allow_source=true"
            f"&playlist_include_framerate=true"
            f"&type=any"
        )

    def get_vod_playback_token(self, vod_id):
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
                "playerType": "mobile"
            }
        }

        response = self.session.post(GQL_URL, json={"query": query, "variables": variables})

        if response.status_code != 200:
            print(f"  {c('✗', C.YELLOW)} Error fetching VOD token: {response.status_code}")
            return None, None

        result = response.json()
        if "data" in result and result["data"]["videoPlaybackAccessToken"]:
            token_data = result["data"]["videoPlaybackAccessToken"]
            return token_data["value"], token_data["signature"]

        return None, None

    def get_vod_info(self, vod_id):
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
        response = self.session.post(GQL_URL, json={
            "query": query,
            "variables": {"id": vod_id}
        })
        if response.status_code != 200:
            return None
        result = response.json()
        if "data" in result and result["data"]["video"]:
            video = result["data"]["video"]
            return {
                "id": video["id"],
                "title": video.get("title", "VOD"),
                "channel": video["owner"]["login"] if video.get("owner") else "Unknown",
                "display_name": video["owner"]["displayName"] if video.get("owner") else "Unknown",
                "duration": video.get("duration", ""),
                "view_count": video.get("viewCount", 0),
            }
        return None

    def get_vod_url(self, vod_id):
        token, signature = self.get_vod_playback_token(vod_id)

        if not token or not signature:
            return None

        import urllib.parse
        encoded_token = urllib.parse.quote(token, safe='')
        encoded_sig = urllib.parse.quote(signature, safe='')

        return (
            f"https://usher.ttvnw.net/vod/{vod_id}.m3u8"
            f"?player=twitchweb"
            f"&token={encoded_token}"
            f"&sig={encoded_sig}"
            f"&allow_audio_only=true"
            f"&allow_source=true"
            f"&playlist_include_framerate=true"
            f"&type=any"
        )

    def get_user_id(self):
        """Get user ID from OAuth token"""
        if not self.token:
            return None
        response = self.session.get("https://api.twitch.tv/helix/users", headers={
            "Authorization": f"Bearer {self.token}",
            "Client-ID": OAUTH_CLIENT_ID
        })
        if response.status_code == 200:
            data = response.json()
            if data.get("data") and len(data["data"]) > 0:
                return data["data"][0]["id"]
        else:
            print(f" {c('✗', C.YELLOW)} Error getting user ID: {response.status_code} - {response.text}")
        return None

    def search_game(self, query):
        """Search for a game by name"""
        response = self.session.get(
            "https://api.twitch.tv/helix/search/categories",
            params={"query": query, "first": 1},
            headers={
                "Authorization": f"Bearer {self.token}",
                "Client-ID": OAUTH_CLIENT_ID
            }
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("data") and len(data["data"]) > 0:
                return data["data"][0]
        return None

    def get_followed_live_streams(self, user_id, first=20):
        """Get live streams from channels the user follows"""
        response = self.session.get(
            "https://api.twitch.tv/helix/streams/followed",
            params={"user_id": user_id, "first": first},
            headers={
                "Authorization": f"Bearer {self.token}",
                "Client-ID": OAUTH_CLIENT_ID
            }
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("data", [])
        else:
            print(f"  {c('✗', C.YELLOW)} Error fetching followed streams: {response.status_code} - {response.text}")
        return []

    def get_streams_by_game(self, game_id, first=10):
        """Get live streams for a specific game"""
        response = self.session.get(
            "https://api.twitch.tv/helix/streams",
            params={"game_id": game_id, "first": first, "type": "live"},
            headers={
                "Authorization": f"Bearer {self.token}",
                "Client-ID": OAUTH_CLIENT_ID
            }
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("data", [])
        return []


def parse_twitch_url(url):
    parsed = urlparse(url)
    if "twitch.tv" not in parsed.netloc:
        return None, None

    path_parts = parsed.path.strip("/").split("/")
    if path_parts[0] == "videos" and len(path_parts) >= 2:
        return "vod", path_parts[1]
    if path_parts[0] and path_parts[0] != "videos":
        return "channel", path_parts[0]
    return None, None


def get_player_args(player_name, stream_url, stream_title=None, custom_cmd=None):
    if custom_cmd:
        return custom_cmd.replace("{url}", stream_url), True

    if player_name == "mpv":
        args = [
            "mpv", "--vo=gpu", "--hwdec=auto", "--cache=yes",
            "--user-agent=Twitch/14.9.1 (Linux; U; Android 13; en) ExoPlayer",
            "--referrer=https://www.twitch.tv/",
        ]
        if stream_title:
            args.append(f"--force-media-title={stream_title}")
        args.append(stream_url)
        return args, False

    elif player_name == "vlc":
        args = [
            "vlc", "--intf=rc",
            "--http-user-agent=Twitch/14.9.1 (Linux; U; Android 13; en) ExoPlayer",
        ]
        if stream_title:
            args.extend(["--meta-title", stream_title])
        args.append(stream_url)
        return args, False

    elif player_name == "flatpak-vlc":
        args = [
            "flatpak", "run", "org.videolan.VLC", "--intf=rc",
            "--http-user-agent=Twitch/14.9.1 (Linux; U; Android 13; en) ExoPlayer",
        ]
        if stream_title:
            args.extend(["--meta-title", stream_title])
        args.append(stream_url)
        return args, False

    elif player_name == "ffplay":
        # ffplay needs headers passed as single string with \r\n separator
        headers = "User-Agent: Twitch/14.9.1 (Linux; U; Android 13; en) ExoPlayer\r\nReferer: https://www.twitch.tv/\r\n"
        args = [
            "ffplay", "-autoexit",
            "-headers", headers,
        ]
        if stream_title:
            args.extend(["-window_title", stream_title])
        args.append(stream_url)
        return args, False

    else:
        cmd = f"mpv --vo=gpu --hwdec=auto --cache=yes --user-agent='Twitch/14.9.1 (Linux; U; Android 13; en) ExoPlayer' {stream_url}"
        return cmd, True


def list_players():
    print(f"\n  {c('Available media players:', C.B)}")
    print(f"  {c('┌─────────┬─────────────────────────────────────────┐', C.GRAY)}")
    print(f"  {c('│', C.GRAY)} {c('Player', C.B)} {c('│', C.GRAY)} {c('Description', C.B)}")
    print(f"  {c('├─────────┼─────────────────────────────────────────┤', C.GRAY)}")
    for name, desc in AVAILABLE_PLAYERS.items():
        marker = f"{c('✓', C.GREEN)}" if name == "mpv" else " "
        print(f"  {c('│', C.GRAY)} {marker} {c(name, C.BLUE)} {c('│', C.GRAY)} {desc}")
    print(f"  {c('└─────────┴─────────────────────────────────────────┘', C.GRAY)}")
    print(f"\n  {c('Use', C.D)} -p {c('or', C.D)} --player {c('to select (default: mpv)', C.D)}")

def list_followed_streams(player="mpv", custom_player=None, token=None):
    """List and play live streams from followed channels"""
    twitch = TwitchPlayer(token=token)

    if not twitch.ensure_auth():
        return False

    user_id = twitch.get_user_id()
    if not user_id:
        print(f" {c('✗', C.YELLOW)} Could not get user ID from token")
        return False

    streams = twitch.get_followed_live_streams(user_id)

    if not streams:
        print(f"\n {c('No followed channels currently live', C.GRAY)}")
        return True

    print(f"\n {c('Live from your follows:', C.B)}")
    for i, stream in enumerate(streams, 1):
        channel = stream.get("user_name", "Unknown")
        game = stream.get("game_name", "N/A")
        viewers = f"{stream.get('viewer_count', 0):,}"
        print(f" {c(f'{i}.', C.GRAY)} {c(channel, C.BLUE)} - {game} ({viewers} viewers)")

    print(f"\n {c('Select channel to play', C.B)} (or 'q' to quit):")

    choice = input(f" {c('>', C.GREEN)} ").strip()

    if choice.lower() == 'q' or not choice.isdigit():
        return True

    idx = int(choice) - 1
    if idx < 0 or idx >= len(streams):
        print(f" {c('✗', C.YELLOW)} Invalid selection")
        return False

    channel_name = streams[idx].get("user_login")
    return play_stream(channel_name, player=player, custom_player=custom_player, token=token)

def search_streams(game_query, player="mpv", custom_player=None, token=None):
    """List and play live streams for a specific game"""
    twitch = TwitchPlayer(token=token)

    if not twitch.ensure_auth():
        return False

    game = twitch.search_game(game_query)
    if not game:
        print(f" {c('✗', C.YELLOW)} Game not found: {game_query}")
        return False

    game_name = game.get("name")
    print(f"\n {c(f'Searching for live streams in: {game_name}', C.B)}")
#    print(f"\n {c(f\"Searching for live streams in: {game.get('name')}\", C.B)}")

    streams = twitch.get_streams_by_game(game.get("id"))
    if not streams:
        print(f" {c('✗', C.YELLOW)} No live streams for {game.get('name')}")
        return True

    for i, stream in enumerate(streams, 1):
        channel = stream.get("user_name", "Unknown")
        viewers = f"{stream.get('viewer_count', 0):,}"
        print(f" {c(f'{i}.', C.GRAY)} {c(channel, C.BLUE)} ({viewers} viewers)")

    print(f"\n {c('Select channel to play', C.B)} (or 'q' to quit):")
    choice = input(f" {c('>', C.GREEN)} ").strip()

    if choice.lower() == 'q' or not choice.isdigit():
        return True

    idx = int(choice) - 1
    if idx < 0 or idx >= len(streams):
        print(f" {c('✗', C.YELLOW)} Invalid selection")
        return False

    channel_name = streams[idx].get("user_login")
    return play_stream(channel_name, player=player, custom_player=custom_player, token=token)



def play_stream(channel_input, player="mpv", custom_player=None, token=None, force_login=False):
    twitch = TwitchPlayer(token=token)

    if force_login:
        print(f"  {c('Authenticating...', C.BLUE)}")
        if not twitch.ensure_auth():
            return False

    if not channel_input:
        return True

    stream_title = None

    try:
        if channel_input.startswith("http"):
            url_type, identifier = parse_twitch_url(channel_input)
            if url_type is None:
                print(f"  {c('✗', C.YELLOW)} Invalid Twitch URL: {channel_input}")
                return False
            if url_type == "vod":
                vod_info = twitch.get_vod_info(identifier)
                if vod_info:
                    stream_title = f"{vod_info['title']} - {vod_info['display_name']}"
                    print(f"\n {c('VOD:', C.D)} {c(stream_title, C.WHITE)}")
                    print(f" {c('Duration:', C.D)} {c(vod_info.get('duration', 'N/A'), C.GRAY)}")
                    print(f" {c('Views:', C.D)} {c(str(vod_info.get('view_count', 'N/A')), C.GRAY)}")
                stream_url = twitch.get_vod_url(identifier)
            else:
                channel_name = identifier
                print(f"  Fetching stream for {c(channel_name, C.BLUE)}...")
                stream_info = twitch.get_stream_info(channel_name)
                if stream_info:
                    stream_title = f"{stream_info['title']} - {stream_info['channel']}"
                    if stream_info.get('game'):
                        stream_title += f" | {stream_info['game']}"
                stream_url = twitch.get_stream_url(channel_name)
        else:
            channel_name = channel_input.lstrip("@")
            print(f"  Fetching stream for {c(channel_name, C.BLUE)}...")
            stream_info = twitch.get_stream_info(channel_name)
            if stream_info:
                stream_title = f"{stream_info['title']} - {stream_info['channel']}"
                if stream_info.get('game'):
                    stream_title += f" | {stream_info['game']}"
            stream_url = twitch.get_stream_url(channel_name)
    except Exception as e:
        print(f"  {c('✗', C.YELLOW)} Error: {e}")
        return False

    if not stream_url:
        print(f"  {c('✗', C.YELLOW)} Could not fetch stream URL")
        return False

    if stream_title:
        print(f"\n  {c('Stream:', C.D)} {c(stream_title, C.WHITE)}")
    print(f"  {c('Player:', C.D)} {c(player, C.BLUE)}")
    print(f"\n  {c('Starting playback...', C.GREEN)}\n")

    player_cmd, use_shell = get_player_args(player, stream_url, stream_title, custom_player)

    try:
        if use_shell:
            subprocess.run(player_cmd, shell=True)
        else:
            subprocess.run(player_cmd)
        return True
    except FileNotFoundError:
        print(f"  {c('✗', C.YELLOW)} Player '{player}' not found")
        return False
    except Exception as e:
        print(f"  {c('✗', C.YELLOW)} Error: {e}")
        return False


def print_help():
    """Print colored help message"""
    print()
    print(f"  {c('╭────────────────────────────────────────────────╮', C.PURPLE)}")
    print(f"  {c('│', C.PURPLE)} {c('Twitch CLI Player', C.B)} {c('—', C.D)} {c('Ad-free streaming', C.GREEN)} {c('│', C.PURPLE)}")
    print(f"  {c('╰────────────────────────────────────────────────╯', C.PURPLE)}")
    print()
    print(f"  {c('Play Twitch streams', C.WHITE)} without ads using Android platform impersonation.")
    print()
    print(f"  {c('Usage:', C.B)}")
    print(f"    {c('twitch_cli.py', C.BLUE)} [{c('CHANNEL', C.GRAY)}] [{c('-p', C.GRAY)} {c('player', C.GRAY)}] [{c('--login', C.GRAY)}] [{c('--logout', C.GRAY)}]")
    print()
    print(f"  {c('Arguments:', C.B)}")
    print(f"    {c('CHANNEL', C.BLUE)}         Channel name or Twitch URL")
    print()
    print(f"  {c('Options:', C.B)}")
    print(f"    {c('-p, --player', C.BLUE)}    Player: mpv (default), vlc, flatpak-vlc, ffplay")
    print(f"    {c('--list-players', C.BLUE)}  List available players")
    print(f"    {c('--login', C.BLUE)}         Force OAuth re-login")
    print(f"    {c('--logout', C.BLUE)}        Clear stored token")
    print(f"    {c('--followed', C.BLUE)}      List and play live followed channels")
    print(f"    {c('--search', C.BLUE)}        Search and play live streams for a game")
    print(f"    {c('--custom-player', C.BLUE)} Custom player command ({{url}} placeholder)")
    print(f"    {c('--token', C.BLUE)}         Use provided OAuth token")
    print()
    print(f"  {c('Examples:', C.B)}")
    print(f"    {c('twitch_cli.py willneff', C.BLUE)}        {c('# Play willneff stream', C.D)}")
    print(f"    {c('twitch_cli.py emiru -p vlc', C.BLUE)}    {c('# Use VLC player', C.D)}")
    print(f"    {c('twitch_cli.py --login', C.BLUE)}         {c('# OAuth login', C.D)}")
    print(f"    {c('twitch_cli.py --logout', C.BLUE)}        {c('# Clear token', C.D)}")
    print()


def create_parser():
    """Create argument parser (minimal, for --help fallback)"""
    parser = argparse.ArgumentParser(
        prog="twitch_cli.py",
        description="Play Twitch streams without ads",
        add_help=False,
    )
    parser.add_argument("channel", nargs="?", metavar="CHANNEL")
    parser.add_argument("-p", "--player", default="mpv")
    parser.add_argument("--list-players", action="store_true")
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--followed", action="store_true", help="List and play live followed channels")
    parser.add_argument("--search", metavar="GAME", help="Search and play live streams for a game")
    parser.add_argument("--logout", action="store_true")
    parser.add_argument("--custom-player")
    parser.add_argument("--token")
    parser.add_argument("-h", "--help", action="store_true")
    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()

    if args.list_players:
        print_banner()
        list_players()
        return

    if args.logout:
        TokenStorage().delete_token()
        print(f"  {c('✓', C.GREEN)} Logged out. Token cleared.")
        return

    if args.followed:
        print_banner()
        list_followed_streams(
            player=args.player,
            custom_player=args.custom_player,
            token=args.token,
        )
        return

    if args.search:
        print_banner()
        search_streams(
            args.search,
            player=args.player,
            custom_player=args.custom_player,
            token=args.token,
        )
        return

    if args.help or (not args.channel and not args.login):
        print_help()
        return

    success = play_stream(
        args.channel,
        player=args.player,
        custom_player=args.custom_player,
        token=args.token,
        force_login=args.login,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
