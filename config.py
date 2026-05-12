import os
from dotenv import load_dotenv
load_dotenv()

# Telegram API Credentials
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Database Config
MONGO_URI = os.getenv("MONGO_URI", "")
DB_NAME = os.getenv("DB_NAME", "spotigram_db")

# Optional: Logging Channel ID
LOG_CHANNEL = int(os.getenv("LOG_CHANNEL", "0"))

# Bot Username for UI branding
BOT_USERNAME = os.getenv("BOT_USERNAME", "SpotigramV2_bot")

# Admin Configuration
admin_env = os.getenv("ADMIN_IDS", "")
# Convert the comma-separated string into a list of integers
ADMIN_IDS = [int(x.strip()) for x in admin_env.split(",")] if admin_env else []