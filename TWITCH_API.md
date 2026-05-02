# Twitch Helix API Integration

## Overview

S0undTV integrates with Twitch Helix API to retrieve user data including followed channels, stream information, and chat functionality. This document describes the API endpoints, authentication flow, and implementation details based on the official S0undTV Android client.

## Authentication

### OAuth 2.0 Flow

**Authorization URL:**
```
https://id.twitch.tv/oauth2/authorize?client_id=l2wx7tow5m77hvmg883p3a985618os&redirect_uri=http://localhost&response_type=token&scope=chat:read+chat:edit+user:read:follows
```

**Required Scopes:**
- `chat:read` - Read chat messages and room state
- `chat:edit` - Send chat messages
- `user:read:follows` - Read user's followed channels

**Credentials:**
- **Client-ID:** `l2wx7tow5m77hvmg883p3a985618os`
- **Redirect URI:** `http://localhost`
- **Response Type:** `token` (implicit grant)

### Token Storage

Tokens must be stored securely using system keychain:
- **Electron:** Use `keytar` package
- **Android:** System credential storage

---

## API Endpoints

### 1. Get Followed Channels

Retrieves the list of channels the authenticated user follows.

**Endpoint:**
```http
GET https://api.twitch.tv/helix/channels/followed
```

**Parameters:**
| Parameter | Type   | Required | Description                |
|-----------|--------|----------|----------------------------|
| user_id   | string | Yes      | User's Twitch ID           |
| first     | int    | Optional | Max results (default: 100) |

**Headers:**
```http
Client-ID: l2wx7tow5m77hvmg883p3a985618os
Authorization: Bearer {oauth_token}
```

**Request Example:**
```bash
curl -X GET 'https://api.twitch.tv/helix/channels/followed?user_id=123456&first=100' \
  -H 'Client-ID: l2wx7tow5m77hvmg883p3a985618os' \
  -H 'Authorization: Bearer eyJ0eXAiOiJKV1QiLCJalg...'
```

**Response:**
```json
{
  "total": 42,
  "data": [
    {
      "broadcaster_id": "123456",
      "broadcaster_login": "shroud",
      "broadcaster_name": "shroud",
      "followed_at": "2024-01-15T10:30:00Z"
    }
  ],
  "pagination": {
    "cursor": "eyJbIjoiMSIsImIiOiIxIn0"
  }
}
```

---

### 2. Get User Info

Retrieves information about one or more specified Twitch users.

**Endpoint:**
```http
GET https://api.twitch.tv/helix/users
```

**Parameters:**
| Parameter | Type   | Required | Description           |
|-----------|--------|----------|-----------------------|
| id        | string | Optional | User ID (can specify multiple) |
| login     | string | Optional | User login name       |

**Request Example:**
```bash
curl -X GET 'https://api.twitch.tv/helix/users?login=shroud' \
  -H 'Client-ID: l2wx7tow5m77hvmg883p3a985618os' \
  -H 'Authorization: Bearer eyJ0eXAiOiJKV1QiLCJalg...'
```

**Response:**
```json
{
  "data": [{
    "id": "123456",
    "login": "shroud",
    "display_name": "shroud",
    "type": "",
    "broadcaster_type": "partner",
    "description": "Professional streamer",
    "profile_image_url": "https://...",
    "offline_image_url": "",
    "view_count": 567890,
    "created_at": "2011-06-03T19:12:02.373654Z"
  }]
}
```

---

### 3. Get Stream (HLS URL)

Retrieves live stream information including HLS playback URLs.

**Endpoint:**
```http
GET https://api.twitch.tv/helix/streams
```

**Parameters:**
| Parameter   | Type   | Required | Description                    |
|-------------|--------|----------|--------------------------------|
| user_id     | string | Optional | Filter by user ID              |
| user_login  | string | Optional | Filter by user login           |
| game_id     | string | Optional | Filter by game/category ID     |
| type        | string | Optional | Filter by stream type (live)   |

**Request Example:**
```bash
curl -X GET 'https://api.twitch.tv/helix/streams?user_login=shroud' \
  -H 'Client-ID: l2wx7tow5m77hvmg883p3a985618os' \
  -H 'Authorization: Bearer eyJ0eXAiOiJKV1QiLCJalg...'
```

**Response:**
```json
{
  "data": [{
    "id": "409823982",
    "user_id": "123456",
    "user_login": "shroud",
    "user_name": "shroud",
    "game_id": "516575",
    "game_name": "VALORANT",
    "type": "live",
    "title": "Ranked grind continues",
    "viewer_count": 45000,
    "started_at": "2024-01-15T14:00:00Z",
    "language": "en",
    "thumbnail_url": "https://...",
    "tag_ids": []
  }]
}
```

---

### 4. Get Stream Categories (Search)

Search for game categories.

**Endpoint:**
```http
GET https://api.twitch.tv/helix/search/categories
```

**Parameters:**
| Parameter | Type   | Required | Description         |
|-----------|--------|----------|---------------------|
| query     | string | Yes      | Search query        |
| first     | int    | Optional | Max results (max: 5)|

**Request Example:**
```bash
curl -X GET 'https://api.twitch.tv/helix/search/categories?query=valorant&first=5' \
  -H 'Client-ID: l2wx7tow5m77hvmg883p3a985618os' \
  -H 'Authorization: Bearer eyJ0eXAiOiJKV1QiLCJalg...'
```

---

### 5. Get Stream Categories (Search Channels)

Search for live channels.

**Endpoint:**
```http
GET https://api.twitch.tv/helix/search/channels
```

**Parameters:**
| Parameter  | Type   | Required | Description              |
|------------|--------|----------|--------------------------|
| query      | string | Yes      | Search query             |
| live_only  | bool   | Optional | Filter to live channels  |
| first      | int    | Optional | Max results (max: 5)     |

---

### 6. Followed Live Streams

Get **live** streams from followed channels. This endpoint only returns channels that are currently broadcasting.

**Endpoint:**
```http
GET https://api.twitch.tv/helix/streams/followed
```

**Parameters:**
| Parameter | Type   | Required | Description      |
|-----------|--------|----------|------------------|
| user_id   | string | Yes      | User's Twitch ID |

**Headers:** Same as above (Client-ID + Authorization)

**Request Example:**
```bash
curl -X GET 'https://api.twitch.tv/helix/streams/followed?user_id=123456' \
  -H 'Client-ID: l2wx7tow5m77hvmg883p3a985618os' \
  -H 'Authorization: Bearer eyJ0eXAiOiJKV1QiLCJalg...'
```

**Response:**
```json
{
  "data": [
    {
      "id": "409823982",
      "user_id": "654321",
      "user_login": "xqc",
      "user_name": "xQc",
      "game_id": "516575",
      "game_name": "VALORANT",
      "type": "live",
      "title": "RANK 1 GRIND",
      "viewer_count": 67000,
      "started_at": "2024-01-15T12:00:00Z",
      "language": "en",
      "thumbnail_url": "https://...",
      "tag_ids": []
    }
  ],
  "pagination": {
    "cursor": "eyJbIjoiMSIsImIiOiIxIn0"
  }
}
```

**Note:** This is different from `channels/followed` which returns ALL followed channels (live or offline). Use `streams/followed` when you only want currently-live content.

---

## Error Codes

| Code | Description | Action |
|------|-------------|--------|
| 400  | Bad Request | Check parameters |
| 401  | Unauthorized | Token expired, re-authenticate |
| 403  | Forbidden   | Invalid scope or client ID |
| 404  | Not Found   | Resource doesn't exist |
| 429  | Too Many Requests | Rate limited, wait and retry |
| 500  | Internal Server Error | Twitch server issue |

**Error Response Format:**
```json
{
  "error": "Unauthorized",
  "status": 401,
  "message": "Invalid OAuth token"
}
```

---

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| General Helix | 800 requests per minute |
| Followed Channels | Included in general limit |
| Search | Included in general limit |

**Headers to monitor:**
- `Ratelimit-HelixLimiter-Limit`: Max requests
- `Ratelimit-HelixLimiter-Remaining`: Remaining requests
- `Ratelimit-HelixLimiter-Reset`: Seconds until reset

---

## Implementation (Electron)

### twitch-api.js

```javascript
const fetch = require('node-fetch');

const CLIENT_ID = 'l2wx7tow5m77hvmg883p3a985618os';
const BASE_URL = 'https://api.twitch.tv/helix';

class TwitchAPI {
  constructor(token) {
    this.token = token;
    this.clientId = CLIENT_ID;
  }

  async getFollowedChannels(userId, first = 100) {
    const url = `${BASE_URL}/channels/followed?user_id=${userId}&first=${first}`;
    const response = await fetch(url, {
      headers: {
        'Client-ID': this.clientId,
        'Authorization': `Bearer ${this.token}`
      }
    });
    return response.json();
  }

  async getFollowedLiveStreams(userId) {
    const url = `${BASE_URL}/streams/followed?user_id=${userId}`;
    const response = await fetch(url, {
      headers: {
        'Client-ID': this.clientId,
        'Authorization': `Bearer ${this.token}`
      }
    });
    return response.json();
  }

  async getUserInfo(login) {
    const url = `${BASE_URL}/users?login=${login}`;
    const response = await fetch(url, {
      headers: {
        'Client-ID': this.clientId,
        'Authorization': `Bearer ${this.token}`
      }
    });
    return response.json();
  }

  async getStream(userLogin) {
    const url = `${BASE_URL}/streams?user_login=${userLogin}`;
    const response = await fetch(url, {
      headers: {
        'Client-ID': this.clientId,
        'Authorization': `Bearer ${this.token}`
      }
    });
    return response.json();
  }

  async getFollowedStreams(userId) {
    const url = `${BASE_URL}/streams/followed?user_id=${userId}`;
    const response = await fetch(url, {
      headers: {
        'Client-ID': this.clientId,
        'Authorization': `Bearer ${this.token}`
      }
    });
    return response.json();
  }
}

module.exports = TwitchAPI;
```

### main.js (IPC Handlers)

```javascript
const { ipcMain } = require('electron');
const keytar = require('keytar');
const TwitchAPI = require('./services/twitch-api');

const SERVICE_NAME = 's0undtv';

ipcMain.handle('get-token', async () => {
  return keytar.getPassword(SERVICE_NAME, 'token');
});

ipcMain.handle('save-token', async (event, token) => {
  return keytar.setPassword(SERVICE_NAME, 'token', token);
});

ipcMain.handle('get-followed-channels', async () => {
  const token = await keytar.getPassword(SERVICE_NAME, 'token');
  const userId = await getStoredUserId(); // From store
  const api = new TwitchAPI(token);
  return api.getFollowedChannels(userId);
});
```

### preload.js

```javascript
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electron', {
  getToken: () => ipcRenderer.invoke('get-token'),
  saveToken: (token) => ipcRenderer.invoke('save-token', token),
  getFollowedChannels: () => ipcRenderer.invoke('get-followed-channels')
});
```

### Renderer Usage

```javascript
// After login
async function loadFollowedChannels() {
  try {
    const result = await window.electron.getFollowedChannels();
    console.log('Followed channels:', result.data);
    renderChannelList(result.data);
  } catch (error) {
    console.error('Failed to load followed channels:', error);
  }
}
```

---

## References

- [Twitch Helix API Docs](https://dev.twitch.tv/docs/api)
- [OAuth Guide](https://dev.twitch.tv/docs/authentication)
- [API Reference](https://dev.twitch.tv/docs/api/reference)

---

## Appendix: Android Class Mapping

| Android Class | Purpose | Electron Equivalent |
|---------------|---------|---------------------|
| `LoginActivity` | OAuth WebView | Settings page |
| `MainFragment` | Channel list UI | React component |
| `fc/e.class` | FollowedChannels helper | twitch-api.js |
| `fc/e$a$a.class` | FollowedChannelsHelix | twitch-api.js method |
| `nc/a.class` | HTTP client | node-fetch |
| `yc/d.class` | Token storage | keytar |

---

## Appendix: Endpoint Comparison

| Endpoint | Returns | Use Case |
|----------|---------|----------|
| `channels/followed` | All followed channels (live + offline) | Building channel list, checking followed status |
| `streams/followed` | Only followed channels currently live | "Live Now" section, live notifications |
| `streams?user_id=` | Specific stream info | Getting stream details for a single channel |
| `search/categories` | Game categories | Search functionality |
| `search/channels` | Channels by query | Channel search |

**Key Difference:**
- `channels/followed` → Returns channels regardless of live status (has `followed_at` timestamp)
- `streams/followed` → Returns only currently-live channels (has `viewer_count`, `started_at`, `game_name`)
