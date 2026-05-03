# Spotigram

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Pyrogram](https://img.shields.io/badge/Framework-Pyrogram-blue.svg)
![MongoDB](https://img.shields.io/badge/Database-MongoDB-green.svg)
![License](https://img.shields.io/badge/License-MIT-purple.svg)

**Spotigram** is a high-speed, asynchronous Telegram bot that acts as a direct bridge between Spotify and Telegram. Built with a sleek, minimalist terminal-style UI, it allows users to download Spotify Tracks, Albums, and Playlists in original high-quality audio directly within Telegram.

*Created by Ankit Roy*

---

## Features

* **High-Speed MTProto Uploads:** Uses Pyrogram to upload files up to 2GB natively, bypassing standard HTTP bot API limits.
* **Parallel Playlist Processing:** Utilizes `ThreadPoolExecutor` to process and download massive playlists concurrently without freezing the bot.
* **Persistent Rate Limiting:** Integrated MongoDB database tracks users and enforces a strict 30-second cooldown shield to prevent spam and server overload.
* **Custom Terminal UI:** Features a highly stylized, dark-mode terminal aesthetic for all bot responses and live-updating progress bars.
* **Smart Metadata Extraction:** Automatically fetches high-res album art and cleans up artist tags (max 2 artists) for beautiful Telegram audio descriptions.
* **Zero-Bandwidth Logging:** Instantly clones delivered tracks to a private log channel using native Telegram message copying, saving server bandwidth.

---

## Prerequisites

Before you start, you will need:
1. **Python 3.9 or higher** installed on your machine.
2. A **Telegram Bot Token** (from [@BotFather](https://t.me/botfather)).
3. A **Telegram API ID and Hash** (from [my.telegram.org](https://my.telegram.org)).
4. A **MongoDB Cloud URI** (Free M0 Cluster from [MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register)).

---

## Installation & Setup

**1. Clone the repository**

```bash
git clone https://github.com/ankittroy-21/Spotigram.git
cd Spotigram
```
**2. Create and activate a Virtual Environment**

- **Windows:**

```bash
python -m venv venv
.\venv\Scripts\activate
```
- **Mac/Linux:**

```bash
python3 -m venv venv
source venv/bin/activate
```

**3. Install dependencies**

```bash
pip install -r requirements.txt
```
**4. Configure Environment Variables**

Rename the .env.example file to .env (or create a new .env file) and fill in your credentials:

- **To Create a .env from the .env.example:**

```bash
cp .env.example .env
```
- **Your .env file will look like this:**

```Code snippet
API_ID=12345678
API_HASH=your_api_hash_here
BOT_TOKEN=your_bot_token_here
MONGO_URI=mongodb+srv://<username>:<password>@cluster0.abcde.mongodb.net/?retryWrites=true&w=majority
DB_NAME=spotigram_db
LOG_CHANNEL=-1001234567890
BOT_USERNAME=YourSpotigramBot
```

**How to get your Environment Variables:**
- **API_ID & API_HASH:** Go to `my.telegram.org`, log in, click "API development tools", and create an app to get these numbers.

- **BOT_TOKEN:** Message `@BotFather` on Telegram, use /newbot, and copy the HTTP API Token.

- **MONGO_URI:**

Go to `MongoDB Atlas` and create a free M0 cluster.

Create a Database User and password (do not use @, :, or / in the password).


Click `"Connect"` -> `"Drivers"` -> `"Python"` and copy the connection string. Replace `<password>` with your actual password.

- **LOG_CHANNEL:** Create a private Telegram channel, add your bot as an admin, and forward a message from that channel to `@JsonDumpBot` to find the channel ID (it will start with -100).

- **BOT_USERNAME:** The exact username of your bot without the `@` symbol (used for custom branding).

## Running the Bot
Once your .env is configured, start the engine:

```bash
python main.py
```
If successful, your terminal will display:
```bash
° Spotigram is now running. Waiting for messages...
```

Go to Telegram, press `/start`, and drop a Spotify link!

## Project Architecture
```Plaintext
Spotigram/
├── core/
│   ├── __init__.py
│   └── scraper.py       # DRM bypass, data parsing, and parallel download engine
├── main.py              # Pyrogram controller, event loop, and custom UI
├── database.py          # MongoDB Motor client and rate-limiting logic
├── config.py            # Environment variable loader
├── requirements.txt     # Dependency list
└── README.md
```
## Disclaimer
This bot acts as a wrapper for **third-party web scraping APIs**. It is built strictly for **educational purposes** and **personal archiving**. Users are responsible for adhering to Spotify's Terms of Service and local copyright laws regarding the distribution of `DRM-protected content`.