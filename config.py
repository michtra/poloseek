"""Configuration for PoloSeek bot"""
import os
import pytz
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('DISCORD_TOKEN')
OWNER_ID = int(os.getenv('DISCORD_OWNER_ID'))
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID'))
DEFAULT_OWNER_ID = int(os.getenv('DEFAULT_OWNER_ID', OWNER_ID))

CDT = pytz.timezone('America/Chicago')
