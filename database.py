import logging
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, DB_NAME

# Setup basic logging to monitor the connections
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
        
        # Create a unique index so we never accidentally save the same user twice
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
        """Adds a new user to the database using an upsert operation."""
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
                }
            },
            upsert=True,
        )

# Create a single instance to be imported by our main bot file 
db = SpotigramDB()