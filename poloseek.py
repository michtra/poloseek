# POLOSEEK
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import asyncio
from typing import Optional

from config import TOKEN, OWNER_ID, CHANNEL_ID, DEFAULT_OWNER_ID, CDT
from utils import ensure_cdt_timezone
from database import (
    init_database, get_current_owner, transfer_pass_with_lock, 
    get_reservation_status, get_user_active_reservations, 
    mark_reservation_inactive, is_reservation_ready_to_start,
    get_user_memo, cleanup_old_reservations
)
from commands import setup_commands
from enums import ReservationStatus
from scraper import Scraper

class PoloSeek(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        super().__init__(command_prefix='!', intents=intents)
        self.last_check_time = None  # track last check to prevent duplicate processing
        
    async def setup_hook(self):
        """Initialize database and sync commands"""
        init_database()
        setup_commands(self)
        await self.tree.sync()
        print(f"Synced slash commands for {self.user}")
        
        # background task to check for expired reservations
        self.check_expired_reservations.start()
        
        # background task to cleanup old reservations (daily)
        self.cleanup_old_reservations.start()
        
        # update bot status
        await self.update_status()
    
    async def on_ready(self):
        """Called when bot is ready"""
        print(f'{self.user} has connected to Discord.')
        await self.update_status()
    
    async def update_status(self):
        """Update bot status to show current pass owner"""
        try:
            # make sure the bot is ready before trying to update status
            if not self.is_ready():
                return
                
            current_owner = get_current_owner()
            if current_owner:
                user = self.get_user(current_owner['current_owner_id'])
                username = user.display_name if user else f"User {current_owner['current_owner_id']}"
                
                # convert timestamp to CDT
                last_updated = ensure_cdt_timezone(datetime.fromisoformat(current_owner['last_updated']))
                time_str = last_updated.strftime("%m/%d %I:%M %p CDT")
                
                activity = discord.Activity(
                    type=discord.ActivityType.watching,
                    name=f"Updated to {username} at {time_str}"
                )
                await self.change_presence(activity=activity)
        except Exception as e:
            print(f"Error updating status: {e}")
    
    @tasks.loop(seconds=1)
    async def check_expired_reservations(self):
        """Check for expired reservations and handle queue transfers"""
        try:
            # make sure the bot is ready before checking reservations
            if not self.is_ready():
                return
            
            now = datetime.now(CDT)
            
            # prevent duplicate processing within same second
            if self.last_check_time and self.last_check_time.second == now.second:
                return
            self.last_check_time = now
            
            # get all reservation status in one efficient query
            status = get_reservation_status(now)
            if not status:
                return
            
            current_owner_id = status['current_owner_id']
            expired_reservations = status['expired_reservations']
            next_approved = status['next_approved']
            
            # handle expired reservations
            transfer_occurred = await self.handle_expired_reservations(
                expired_reservations, current_owner_id, next_approved, now
            )
            
            # then handle scheduled starts (only if no expiration transfer occurred)
            if not transfer_occurred and next_approved:
                await self.handle_scheduled_starts(next_approved, current_owner_id, now)
                
        except Exception as e:
            print(f"Error checking expired reservations: {e}")
    
    @tasks.loop(hours=24)
    async def cleanup_old_reservations(self):
        """Clean up old reservations daily"""
        try:
            # clean up reservations older than 7 days
            cutoff_date = datetime.now(CDT) - timedelta(days=7)
            cleanup_old_reservations(cutoff_date)
            print(f"Cleaned up old reservations before {cutoff_date}")
        except Exception as e:
            print(f"Error cleaning up old reservations: {e}")
    
    async def handle_expired_reservations(self, expired_reservations, current_owner_id, next_approved, now):
        """Handle expired reservations and return True if transfer occurred"""
        for reservation in expired_reservations:
            # mark reservation as inactive
            mark_reservation_inactive(reservation['user_id'], reservation['start_time'])
            
            # check if this was the current pass owner
            if current_owner_id == reservation['user_id']:
                if next_approved:
                    # check if next approved reservation should start now or is already active
                    start_time = ensure_cdt_timezone(datetime.fromisoformat(next_approved['start_time']))
                    if start_time <= now:
                        # transfer to the next approved user with transport scraper update
                        success = await self.transfer_with_transport(
                            current_owner_id, 
                            next_approved['user_id']
                        )
                        if success:
                            await self.update_status()
                            await self.notify_transfer(
                                reservation['user_id'], 
                                next_approved['user_id'],
                                next_approved,
                                "expired"
                            )
                            return True
                
                # no approved reservations ready, return to default owner
                success = await self.transfer_with_transport(current_owner_id, DEFAULT_OWNER_ID)
                if success:
                    await self.update_status()
                    await self.notify_return_to_default(reservation['user_id'])
                    return True
        
        return False
    
    async def handle_scheduled_starts(self, next_scheduled, current_owner_id, now):
        """Handle scheduled reservation starts"""
        # only process if reservation should start and isn't already active
        if (is_reservation_ready_to_start(next_scheduled, now) and 
            current_owner_id != next_scheduled['user_id']):
            
            # check if current owner's reservation has ended or is default owner
            should_transfer = False
            
            if current_owner_id == DEFAULT_OWNER_ID:
                should_transfer = True
            else:
                # check if current owner has an expired reservation
                current_reservations = get_user_active_reservations(current_owner_id, now)
                if not current_reservations:
                    should_transfer = True
            
            if should_transfer:
                # transfer to scheduled approved reservation with transport scraper update
                success = await self.transfer_with_transport(
                    current_owner_id, 
                    next_scheduled['user_id']
                )
                if success:
                    await self.update_status()
                    await self.notify_scheduled_start(next_scheduled)
    
    async def transfer_with_transport(self, from_user_id: int, to_user_id: int) -> bool:
        """Transfer parking pass with transport scraper update"""
        try:
            # get target user memo for transport update
            target_memo = get_user_memo(to_user_id)
            if not target_memo:
                print(f"No vehicle memo found for user {to_user_id}, skipping transport update")
                # still do database transfer for default owner
                if to_user_id == DEFAULT_OWNER_ID:
                    return transfer_pass_with_lock(from_user_id, to_user_id)
                return False
            
            # create transport instance for automatic transfers
            # Note: we can't use interaction.followup here, so we'll use print for notifications
            transport = Scraper(notification_callback=self.log_transport_message)
            
            # update transport scraper first
            await transport.update_parking_pass(target_memo)
            
            # update database after successful transport update
            return transfer_pass_with_lock(from_user_id, to_user_id)
            
        except Exception as e:
            print(f"Error transferring pass with transport: {e}")
            # fallback to database-only transfer for critical cases
            if to_user_id == DEFAULT_OWNER_ID:
                return transfer_pass_with_lock(from_user_id, to_user_id)
            return False
    
    async def log_transport_message(self, message: str):
        """Log transport messages to console since we don't have interaction context"""
        print(f"Transport: {message}")
    
    async def notify_transfer(self, from_user_id, to_user_id, reservation, reason):
        """Send notification about parking pass transfer"""
        channel = self.get_channel(CHANNEL_ID)
        if not channel:
            return
        
        from_user = self.get_user(from_user_id)
        to_user = self.get_user(to_user_id)
        
        from_username = from_user.display_name if from_user else f"User {from_user_id}"
        to_username = to_user.display_name if to_user else f"User {to_user_id}"
        
        start_time = ensure_cdt_timezone(datetime.fromisoformat(reservation['start_time']))
        end_time = ensure_cdt_timezone(datetime.fromisoformat(reservation['end_time']))
        
        if reason == "expired":
            embed = discord.Embed(
                title="Parking Pass Transferred",
                description=f"{from_username}'s reservation expired.\nPass transferred to {to_username} for approved reservation.\n\n**New Reservation:** {start_time.strftime('%m/%d %I:%M %p')} - {end_time.strftime('%m/%d %I:%M %p')}",
                color=discord.Color.blue()
            )
        else:
            embed = discord.Embed(
                title="Parking Pass Transferred",
                description=f"Pass transferred to {to_username}.\n\n**Reservation:** {start_time.strftime('%m/%d %I:%M %p')} - {end_time.strftime('%m/%d %I:%M %p')}",
                color=discord.Color.blue()
            )
        
        await channel.send(embed=embed)
        await channel.send(f"<@{to_user_id}>, your scheduled reservation is now active!")
    
    async def notify_return_to_default(self, from_user_id):
        """Send notification about return to default owner"""
        channel = self.get_channel(CHANNEL_ID)
        if not channel:
            return
        
        from_user = self.get_user(from_user_id)
        from_username = from_user.display_name if from_user else f"User {from_user_id}"
        
        embed = discord.Embed(
            title="Parking Pass Returned",
            description=f"{from_username}'s reservation has expired. Pass returned to default owner.",
            color=discord.Color.orange()
        )
        await channel.send(embed=embed)
    
    async def notify_scheduled_start(self, reservation):
        """Send notification about scheduled reservation starting"""
        channel = self.get_channel(CHANNEL_ID)
        if not channel:
            return
        
        new_user = self.get_user(reservation['user_id'])
        new_username = new_user.display_name if new_user else f"User {reservation['user_id']}"
        
        start_time = ensure_cdt_timezone(datetime.fromisoformat(reservation['start_time']))
        end_time = ensure_cdt_timezone(datetime.fromisoformat(reservation['end_time']))
        
        embed = discord.Embed(
            title="Scheduled Reservation Started",
            description=f"Pass transferred to {new_username} for scheduled approved reservation.\n\n**Reservation:** {start_time.strftime('%m/%d %I:%M %p')} - {end_time.strftime('%m/%d %I:%M %p')}",
            color=discord.Color.green()
        )
        await channel.send(embed=embed)
        await channel.send(f"<@{reservation['user_id']}>, your scheduled reservation is now active!")

    async def get_user_display_name(self, user_id: int) -> str:
        """Helper method to get user display name with fallback"""
        try:
            user = self.get_user(user_id)
            if user:
                return user.display_name
            else:
                # try to fetch user if not in cache
                user = await self.fetch_user(user_id)
                return user.display_name if user else f"User {user_id}"
        except:
            return f"User {user_id}"

bot = PoloSeek()

if __name__ == "__main__":
    bot.run(TOKEN)
