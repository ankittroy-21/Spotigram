"""
Database configuration and user tracking for Spotigram.
Uses Motor (async MongoDB driver) to securely store unique users and enforce rate limits.
"""
import time
import logging
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, DB_NAME

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SpotigramDB:
    def __init__(self):
        self.client: AsyncIOMotorClient | None = None
        self.users_collection = None

    async def connect(self):
        """Initializes the connection to MongoDB."""
        if not MONGO_URI:
            raise ValueError("CRITICAL: MONGO_URI is missing from your .env file!")
        
        self.client = AsyncIOMotorClient(MONGO_URI)
        db = self.client[DB_NAME]
        self.users_collection = db["users"]
        
        await self.users_collection.create_index("user_id", unique=True)
        logger.info(f"Database connected successfully: {DB_NAME}")

    async def disconnect(self):
        """Closes the connection safely."""
        if self.client:
            self.client.close()
            logger.info("Database connection closed.")

    async def is_new_user(self, user_id: int) -> bool:
        """Checks if a user already exists in the database."""
        if self.users_collection is None:
            return False
            
        document = await self.users_collection.find_one({"user_id": user_id}, {"_id": 1})
        return document is None

    async def register_user(self, user_id: int, first_name: str, username: str | None, dc_id: int | None):
        """Adds a new user to the database."""
        if self.users_collection is None:
            return
            
        await self.users_collection.update_one(
            {"user_id": user_id},
            {
                "$setOnInsert": {
                    "user_id": user_id,
                    "first_name": first_name,
                    "username": username,
                    "dc_id": dc_id,
                    "last_used": 0.0  # Initialize timestamp
                }
            },
            upsert=True,
        )

    async def check_rate_limit(self, user_id: int, cooldown_seconds: int = 30) -> tuple[bool, int]:
        """
        Checks if the user is allowed to download based on the cooldown.
        Returns (is_allowed, wait_time_remaining).
        """
        if self.users_collection is None:
            return True, 0

        user = await self.users_collection.find_one({"user_id": user_id}, {"last_used": 1})
        current_time = time.time()

        # If user isn't fully registered yet, let them pass but update time
        if not user or "last_used" not in user:
            await self.users_collection.update_one({"user_id": user_id}, {"$set": {"last_used": current_time}})
            return True, 0

        last_used = user.get("last_used", 0.0)
        time_passed = current_time - last_used

        if time_passed < cooldown_seconds:
            wait_time = int(cooldown_seconds - time_passed)
            return False, wait_time
        
        # If enough time has passed, update their timestamp to NOW
        await self.users_collection.update_one({"user_id": user_id}, {"$set": {"last_used": current_time}})
        return True, 0

db = SpotigramDB()