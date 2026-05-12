"""
Spotigram - Telegram Audio Bridge Controller
Author: Ankit Roy
Description: High-speed asynchronous bot to fetch and deliver Spotify audio.
"""
import os
import re
import time
import asyncio
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
import config
from database import db
from core.scraper import get_track, get_playlist_or_album

# Spotify Link Detector
SPOTIFY_REGEX = re.compile(r"https?://open\.spotify\.com/(track|playlist|album)/[A-Za-z0-9]+")

# Initialize Pyrogram Client
app = Client(
    "spotigram_session",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
)

# --- Helper Functions ---

def get_file_size_mb(file_path: str) -> float:
    """Calculates file size in Megabytes."""
    if file_path and os.path.exists(file_path):
        size_bytes = os.path.getsize(file_path)
        return round(size_bytes / (1024 * 1024), 2)
    return 0.0

async def upload_progress(current: int, total: int, status_msg: Message, start_time: float):
    """Optimized progress bar that updates every 2 seconds to avoid Telegram limits."""
    elapsed = time.time() - start_time
    if int(elapsed) % 2 == 0:
        percentage = current * 100 / total
        filled_blocks = int(percentage / 10)
        bar = "█" * filled_blocks + "▒" * (10 - filled_blocks)
        try:
            await status_msg.edit_text(
                f"§ **Spotigram is working...**\n"
                f"→ Uploading to Telegram\n"
                f"※ `⟦{bar}⟧ {percentage:.1f}%`"
            )
        except Exception:
            pass 

def cleanup(path: str | None):
    """Deletes temporary files after uploading."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

# --- Bot Handlers ---

@app.on_message(filters.command("start") & filters.private)
async def cmd_start(client: Client, message: Message):
    """Handles the /start command and logs the user."""
    user = message.from_user
    
    if await db.is_new_user(user.id):
        await db.register_user(user.id, user.first_name, user.username, user.dc_id)

    welcome_text = (
        "↪️ **Welcome to Spotigram** \n\n"
        "I am your high-speed bridge between Spotify and Telegram. "
        "Send me any Spotify Track, Playlist, or Album link, and I'll fetch the original audio for you.\n\n"
        "**→** Just paste a link below to start."
    )
    await message.reply_text(welcome_text)

@app.on_message(filters.text & filters.private & ~filters.regex(r"^/"))
async def handle_spotify_link(client: Client, message: Message):
    """Detects Spotify links and manages the download/upload pipeline."""
    text = message.text.strip()
    
    match = SPOTIFY_REGEX.search(text)
    
    if not match:
        await message.reply_text("❌ That doesn't look like a valid Spotify link.")
        return

    # --- Rate Limit Check ---
    is_allowed, wait_time = await db.check_rate_limit(message.from_user.id, cooldown_seconds=30)
    if not is_allowed:
        await message.reply_text(
            f"⏳ **Anti-Spam Shield Active**\n"
            f"Please wait {wait_time} seconds before requesting another download."
        )
        return
    
    url = match.group(0)
    
    if "/track/" in url:
        await process_single_track(message, url)
    elif "/playlist/" in url or "/album/" in url:
        await process_playlist(message, url)
    else:
        await message.reply_text("❌ Unsupported Spotify link type.")

async def process_single_track(message: Message, url: str):
    """Handles Phase 1 (Download) and Phase 2 (Upload) for a single track."""
    status_msg = await message.reply_text(
        "🤖 **Spotigram is working...**\n"
        "📥 Fetching track from server\n"
        "⏳ `[████▒▒▒▒▒▒] Processing...`"
    )
    
    local_path = thumb_path = None
    try:
        loop = asyncio.get_running_loop()
        file_name, title, artist, local_path, thumb_path = await loop.run_in_executor(
            None, get_track, url
        )
        
        file_size = get_file_size_mb(local_path)
        caption = (
            f"👤 **Artist:** {artist}\n"
            f"💾 **Size:** {file_size} MB\n"
            f"🎵 *Downloaded via @{config.BOT_USERNAME}*"
        )
        
        start_time = time.time()
        
        # Added 'sent_msg =' so the log channel knows what to copy
        sent_msg = await message.reply_audio(
            audio=local_path,
            title=title,
            performer=artist,
            thumb=thumb_path,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            progress=upload_progress,
            progress_args=(status_msg, start_time)
        )
        await status_msg.delete()

        # Log Channel Copy
        if config.LOG_CHANNEL != 0:
            try:
                await sent_msg.copy(
                    chat_id=config.LOG_CHANNEL,
                    caption=f"📁 **Archive**\n👤 User: {message.from_user.first_name} (`{message.from_user.id}`)\n{caption}"
                )
            except Exception as e:
                print(f"❌ Failed to copy to log channel: {e}")

    except Exception as e:
        await status_msg.edit_text(f"❌ **Something went wrong:**\n`{e}`")
    finally:
        cleanup(local_path)
        cleanup(thumb_path)

async def process_playlist(message: Message, url: str):
    """Handles playlist processing asynchronously."""
    status_msg = await message.reply_text(
        "🤖 **Spotigram is working...**\n"
        "• Initializing Playlist Download\n"
        "⚠️ `⟦████▒▒▒▒▒▒⟧ Processing tracks...`"
    )
    
    completed = 0
    failed = 0
    main_loop = asyncio.get_event_loop()

    def on_track_result(index, total, file_name, title, artist, local_path, thumb_path, error):
        nonlocal completed, failed
        if error:
            failed += 1
        else:
            completed += 1
            
        asyncio.run_coroutine_threadsafe(
            upload_playlist_track(
                message, status_msg, completed, failed, total,
                file_name, title, artist, local_path, thumb_path, error
            ),
            loop=main_loop
        )

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: get_playlist_or_album(url, on_result_callback=on_track_result))
    except Exception as e:
        await status_msg.edit_text(f"‼ **Something went wrong:**\n`{e}`")

async def upload_playlist_track(message, status_msg, completed, failed, total, file_name, title, artist, local_path, thumb_path, error):
    """Helper function to upload individual tracks from a playlist."""
    if error:
        pass # We still want to update the progress bar even if it fails
    else:    
        try:
            file_size = get_file_size_mb(local_path)
            caption = (
                f"👤 **Artist:** {artist}\n"
                f"💾 **Size:** {file_size} MB\n"
                f"🎵 *Downloaded via @{config.BOT_USERNAME}*"
            )
            
            # Save the message to a variable for the log channel
            sent_msg = await message.reply_audio(
                audio=local_path,
                title=title,
                performer=artist,
                thumb=thumb_path,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Log Channel Copy for Playlists
            if config.LOG_CHANNEL != 0:
                try:
                    await sent_msg.copy(
                        chat_id=config.LOG_CHANNEL,
                        caption=f"📁 **Archive (Playlist)**\n👤 User: {message.from_user.first_name} (`{message.from_user.id}`)\n{caption}"
                    )
                except Exception as e:
                    print(f"❌ Failed to copy playlist track to log channel: {e}")
                    
        except Exception:
            pass
        finally:
            cleanup(local_path)
            cleanup(thumb_path)

    # --- Progress Bar & Auto-Delete Logic ---
    total_processed = completed + failed
    
    if total_processed == total:
        try:
            await status_msg.delete()
        except Exception:
            pass
    else:
        try:
            bar_fill = int((total_processed) / total * 10)
            bar = "█" * bar_fill + "▒" * (10 - bar_fill)
            await status_msg.edit_text(
                f"🤖 **Spotigram Playlist Progress**\n"
                f"✅ Success: {completed} | ❌ Failed: {failed} | 🎵 Total: {total}\n"
                f"⏳ `[{bar}]`"
            )
        except Exception:
            pass

# --- Admin Commands ---

@app.on_message(filters.command("stats") & filters.user(config.ADMIN_IDS))
async def cmd_stats(client: Client, message: Message):
    """Admin command to check database metrics."""
    status_msg = await message.reply_text("§ Fetching system metrics...")
    
    total_users = await db.get_total_users()
    active_24h = await db.get_active_users_24h()
    
    stats_text = (
        "🤖 **Spotigram Admin Panel** \n\n"
        f"→ **Total Users:** {total_users}\n"
        f"→ **Active (24h):** {active_24h}\n"
        "※ *System running optimally.*"
    )
    await status_msg.edit_text(stats_text)

@app.on_message(filters.command("broadcast") & filters.user(config.ADMIN_IDS))
async def cmd_broadcast(client: Client, message: Message):
    """Admin command to broadcast a message to all users."""
    # To use this, the admin must reply to the message they want to broadcast with /broadcast
    if not message.reply_to_message:
        await message.reply_text("‼ **Usage Error:** You must reply to a message with `/broadcast` to send it.")
        return

    broadcast_msg = message.reply_to_message
    status_msg = await message.reply_text("§ **Initializing Broadcast...**")

    user_ids = await db.get_all_user_ids()
    total = len(user_ids)
    successful = 0
    failed = 0

    await status_msg.edit_text(f"§ **Broadcasting to {total} users...**\n*Please do not restart the bot.*")

    for user_id in user_ids:
        try:
            await broadcast_msg.copy(chat_id=user_id)
            successful += 1
            await asyncio.sleep(0.1)  # Safe speed limit: 10 messages per second
        except FloodWait as e:
            # If Telegram says we are too fast, wait the exact amount of time it asks for
            await asyncio.sleep(e.value)
            await broadcast_msg.copy(chat_id=user_id)
            successful += 1
        except Exception:
            # This happens if a user blocked the bot or deleted their account
            failed += 1

    await status_msg.edit_text(
        f" **Broadcast Complete** \n\n"
        f"= **Successful:** {successful}\n"
        f"− **Failed/Blocked:** {failed}\n"
        f"※ **Total Reached:** {total}"
    )

# --- Entry Point ---
async def start_bot():
    await db.connect()
    await app.start()
    print(f" System Loaded - Admin IDs Recognized: {config.ADMIN_IDS}")
    print(f"° Spotigram is now running. Waiting for messages...")
    await idle()
    await app.stop()
    await db.disconnect()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_bot())