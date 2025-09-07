"""Slash commands for PoloSeek"""
import discord
from discord.ext import commands
from datetime import datetime
from typing import TYPE_CHECKING

from config import OWNER_ID, DEFAULT_OWNER_ID, CDT
from utils import ensure_cdt_timezone, parse_datetime_input
from database import (
    get_current_owner, update_parking_pass_owner, transfer_pass_with_lock,
    check_reservation_conflicts, create_reservation, get_active_reservations,
    get_user_next_unapproved_reservation, approve_reservation_by_details,
    get_user_memo
)

if TYPE_CHECKING:
    from poloseek import PoloSeek

def setup_commands(bot: 'PoloSeek'):
    """Setup all slash commands"""
    
    @bot.tree.command(name="status", description="Show current parking pass owner")
    async def status_command(interaction: discord.Interaction):
        """Display current parking pass status"""
        try:
            current_owner = get_current_owner()
            if not current_owner:
                embed = discord.Embed(
                    title="Error",
                    description="No parking pass data found.",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed)
                return
            
            username = await bot.get_user_display_name(current_owner['current_owner_id'])
            user_mention = f"<@{current_owner['current_owner_id']}>"
            
            # get user memo if available
            memo = get_user_memo(current_owner['current_owner_id'])
            memo_text = f"\n**Vehicle:** {memo}" if memo else ""
            
            # format timestamp
            last_updated = ensure_cdt_timezone(datetime.fromisoformat(current_owner['last_updated']))
            
            embed = discord.Embed(
                title="Poloseek Status",
                description=f"**Current Owner:** {user_mention}{memo_text}\n**Last Updated:** {last_updated.strftime('%B %d, %Y at %I:%M %p CDT')}",
                color=discord.Color.green()
            )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = discord.Embed(
                title="Error",
                description=f"Failed to retrieve status: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="refresh", description="Refresh parking pass data (Owner only)")
    async def refresh_command(interaction: discord.Interaction):
        """Refresh parking pass data - placeholder for web scraping"""
        if interaction.user.id != OWNER_ID:
            embed = discord.Embed(
                title="Access Denied",
                description="This command is restricted to the bot owner.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            await interaction.response.defer()
            
            current_owner = get_current_owner()
            if current_owner:
                update_parking_pass_owner(current_owner['current_owner_id'])
            
            await bot.update_status()
            
            embed = discord.Embed(
                title="Refresh Complete",
                description="Parking pass data has been updated successfully.\n*Note: Web scraping is currently a placeholder.*",
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = discord.Embed(
                title="Error",
                description=f"Failed to refresh data: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)

    @bot.tree.command(name="request", description="Request a parking pass reservation")
    async def request_command(interaction: discord.Interaction, start_time: str, end_time: str):
        """Request a parking pass reservation"""
        try:
            # parse time inputs
            now = datetime.now(CDT)
            start_dt = parse_datetime_input(start_time, now)
            end_dt = parse_datetime_input(end_time, now)
            
            # validate times
            if start_dt <= now:
                embed = discord.Embed(
                    title="Invalid Time",
                    description="Start time must be in the future.",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            if end_dt <= start_dt:
                embed = discord.Embed(
                    title="Invalid Time",
                    description="End time must be after start time.",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # check for conflicts (only with approved reservations)
            conflicts = check_reservation_conflicts(start_dt, end_dt)
            if conflicts:
                conflict_list = []
                for conflict in conflicts:
                    username = await bot.get_user_display_name(conflict['user_id'])
                    start = ensure_cdt_timezone(datetime.fromisoformat(conflict['start_time']))
                    end = ensure_cdt_timezone(datetime.fromisoformat(conflict['end_time']))
                    conflict_list.append(f"• {username}: {start.strftime('%m/%d %I:%M %p')} - {end.strftime('%m/%d %I:%M %p')}")
                
                embed = discord.Embed(
                    title="Time Conflict",
                    description=f"Your requested time conflicts with existing approved reservations:\n\n" + "\n".join(conflict_list),
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # create reservation
            create_reservation(interaction.user.id, start_dt, end_dt)
            
            # get current owner for notification
            current_owner = get_current_owner()
            
            embed = discord.Embed(
                title="Reservation Created",
                description=f"**Requested by:** <@{interaction.user.id}>\n**Start:** {start_dt.strftime('%B %d, %Y at %I:%M %p CDT')}\n**End:** {end_dt.strftime('%B %d, %Y at %I:%M %p CDT')}",
                color=discord.Color.blue()
            )
            
            # send the embed first
            await interaction.response.send_message(embed=embed)
            
            # send a separate message with the mention
            mention_message = f"<@{OWNER_ID}>, you have a new parking pass request!"
            await interaction.followup.send(mention_message)
            
        except ValueError as e:
            embed = discord.Embed(
                title="Invalid Time Format",
                description=f"Could not parse time input: {str(e)}\n\nSupported formats:\n• `YYYY-MM-DD HH:MM`\n• `MM/DD/YYYY HH:MM`\n• `MM/DD HH:MM`\n• `HH:MM` or `H:MM AM/PM`",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception as e:
            embed = discord.Embed(
                title="Error",
                description=f"Failed to create reservation: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="reservations", description="Show all active parking pass reservations")
    async def reservations_command(interaction: discord.Interaction):
        """Display all active reservations with approval status"""
        try:
            reservations = get_active_reservations()
            
            if not reservations:
                embed = discord.Embed(
                    title="Parking Pass Reservations",
                    description="No active reservations found.",
                    color=discord.Color.blue()
                )
                await interaction.response.send_message(embed=embed)
                return
            
            reservation_list = []
            now = datetime.now(CDT)
            current_owner = get_current_owner()
            current_owner_id = current_owner['current_owner_id'] if current_owner else None
            
            for reservation in reservations:
                username = await bot.get_user_display_name(reservation['user_id'])
                
                start = ensure_cdt_timezone(datetime.fromisoformat(reservation['start_time']))
                end = ensure_cdt_timezone(datetime.fromisoformat(reservation['end_time']))
                
                # determine status
                if start <= now <= end:
                    if reservation['user_id'] == current_owner_id:
                        status = "🟢 ACTIVE"
                    else:
                        status = "📅 SCHEDULED"
                elif start > now:
                    if reservation['approved']:
                        status = "✅ APPROVED"
                    else:
                        status = "🟡 PENDING"
                else:
                    status = "🔴 EXPIRED"
                
                reservation_list.append(
                    f"**{username}** {status}\n"
                    f"{start.strftime('%m/%d %I:%M %p')} - {end.strftime('%m/%d %I:%M %p')}"
                )
            
            embed = discord.Embed(
                title="Parking Pass Reservations",
                description="\n\n".join(reservation_list),
                color=discord.Color.blue()
            )
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = discord.Embed(
                title="Error",
                description=f"Failed to retrieve reservations: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="give", description="Give parking pass to a user (Owner only)")
    async def give_command(interaction: discord.Interaction, user: discord.Member):
        """Give parking pass to specified user"""
        if interaction.user.id != OWNER_ID:
            embed = discord.Embed(
                title="Access Denied",
                description="This command is restricted to the bot owner.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            # update parking pass owner with locking
            current_owner = get_current_owner()
            if current_owner and transfer_pass_with_lock(current_owner['current_owner_id'], user.id):
                # update bot status
                await bot.update_status()
                
                # get user memo if available
                memo = get_user_memo(user.id)
                memo_text = f"\n**Vehicle:** {memo}" if memo else ""
                
                embed = discord.Embed(
                    title="Parking Pass Transferred",
                    description=f"Parking pass has been given to <@{user.id}>{memo_text}",
                    color=discord.Color.green()
                )
                
                await interaction.response.send_message(embed=embed)
            else:
                embed = discord.Embed(
                    title="Error",
                    description="Failed to transfer parking pass. Please try again.",
                    color=discord.Color.red()
                )
                await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            embed = discord.Embed(
                title="Error",
                description=f"Failed to transfer parking pass: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="approve", description="Approve the next reservation for a specific user (Owner only)")
    async def approve_command(interaction: discord.Interaction, user: discord.Member):
        """Approve the next pending reservation for a specific user"""
        if interaction.user.id != OWNER_ID:
            embed = discord.Embed(
                title="Access Denied",
                description="This command is restricted to the bot owner.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        try:
            # get the next unapproved reservation for this user
            next_reservation = get_user_next_unapproved_reservation(user.id)
            
            if not next_reservation:
                embed = discord.Embed(
                    title="No Reservation Found",
                    description=f"<@{user.id}> has no pending reservations to approve.",
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            approve_reservation_by_details(user.id, next_reservation['start_time'])
            
            # check if we should transfer immediately
            now = datetime.now(CDT)
            start_time = ensure_cdt_timezone(datetime.fromisoformat(next_reservation['start_time']))
            
            current_owner = get_current_owner()
            
            # transfer immediately if:
            # 1. The reservation should start now or already started, AND
            # 2. Current owner is the default owner (no active reservation)
            should_transfer_now = (start_time <= now and 
                                 current_owner and 
                                 current_owner['current_owner_id'] == DEFAULT_OWNER_ID)
            
            if should_transfer_now:
                if transfer_pass_with_lock(current_owner['current_owner_id'], user.id):
                    await bot.update_status()
                    transfer_msg = "\n\n**Pass transferred immediately** (no conflicts detected)"
                else:
                    transfer_msg = "\n\n**Pass will transfer automatically** at the scheduled time"
            else:
                transfer_msg = "\n\n**Pass will transfer automatically** at the scheduled time"
            
            # get user memo if available
            memo = get_user_memo(user.id)
            memo_text = f"\n**Vehicle:** {memo}" if memo else ""
            
            # format the reservation times
            start = ensure_cdt_timezone(datetime.fromisoformat(next_reservation['start_time']))
            end = ensure_cdt_timezone(datetime.fromisoformat(next_reservation['end_time']))
            
            embed = discord.Embed(
                title="Reservation Approved",
                description=f"**Approved for:** <@{user.id}>{memo_text}\n**Start:** {start.strftime('%B %d, %Y at %I:%M %p CDT')}\n**End:** {end.strftime('%B %d, %Y at %I:%M %p CDT')}{transfer_msg}",
                color=discord.Color.green()
            )
            
            await interaction.response.send_message(embed=embed)
            await interaction.followup.send(f"<@{user.id}>, your reservation has been approved!")
            
        except Exception as e:
            embed = discord.Embed(
                title="Error",
                description=f"Failed to approve reservation: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
