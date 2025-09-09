"""Slash commands for PoloSeek"""
import discord
from discord.ext import commands
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from config import OWNER_ID, DEFAULT_OWNER_ID, CDT
from utils import ensure_cdt_timezone, parse_datetime_input
from database import (
    get_current_owner, update_parking_pass_owner, transfer_pass_with_lock,
    check_reservation_conflicts, create_reservation, get_reservations,
    get_user_next_unapproved_reservation, approve_reservation_by_details,
    get_user_memo, get_user_most_recent_approved_reservation, mark_reservation_inactive
)
from scraper import Scraper

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
        """Refresh parking pass data from transport scraper"""
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
            
            # create transport automation with notification callback
            transport = Scraper(notification_callback=interaction.followup)
            
            # get current user from transport scraper
            current_user_memo = await transport.refresh_current_user()
            
            # find user ID by memo
            current_owner = get_current_owner()
            if current_owner:
                current_memo = get_user_memo(current_owner['current_owner_id'])
                if current_memo != current_user_memo:
                    await interaction.followup.send(f"Memo mismatch detected - database shows '{current_memo}' but transport shows '{current_user_memo}'")
            
            await bot.update_status()
            
            embed = discord.Embed(
                title="Refresh Complete",
                description=f"Current parking pass owner memo: {current_user_memo}",
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
    async def request_command(interaction: discord.Interaction, start_time: str, end_time: str, user: Optional[discord.Member] = None):
        """Request a parking pass reservation"""
        try:
            # determine who the reservation is for
            if user is not None:
                # only bot owner can request on behalf of others
                if interaction.user.id != OWNER_ID:
                    embed = discord.Embed(
                        title="Access Denied",
                        description="Only the bot owner can request reservations on behalf of other users.",
                        color=discord.Color.red()
                    )
                    await interaction.response.send_message(embed=embed, ephemeral=True)
                    return
                target_user = user
                is_owner_request = True
            else:
                target_user = interaction.user
                is_owner_request = False
            
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
                    description=f"The requested time conflicts with existing approved reservations:\n\n" + "\n".join(conflict_list),
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            
            # create reservation
            create_reservation(target_user.id, start_dt, end_dt)

            # auto-approve if request is made by the owner
            if interaction.user.id == OWNER_ID:
                approve_reservation_by_details(target_user.id, start_dt.isoformat())
                approval_status = "**Status:** ✅ AUTOMATICALLY APPROVED"
            else:
                approval_status = "**Status:** 🟡 PENDING APPROVAL"
            
            # create description based on who made the request
            if is_owner_request:
                description = f"**Requested by:** <@{interaction.user.id}> for <@{target_user.id}>\n**Start:** {start_dt.strftime('%B %d, %Y at %I:%M %p CDT')}\n**End:** {end_dt.strftime('%B %d, %Y at %I:%M %p CDT')}\n{approval_status}"
                mention_message = f"<@{target_user.id}>, a parking pass reservation has been created for you!"
            else:
                description = f"**Requested by:** <@{target_user.id}>\n**Start:** {start_dt.strftime('%B %d, %Y at %I:%M %p CDT')}\n**End:** {end_dt.strftime('%B %d, %Y at %I:%M %p CDT')}\n{approval_status}"
                mention_message = f"<@{OWNER_ID}>, you have a new parking pass request!"
            
            embed = discord.Embed(
                title="Reservation Created",
                description=description,
                color=discord.Color.blue()
            )
            
            await interaction.response.send_message(content=mention_message, embed=embed)
            
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
        """Display all reservations with status"""
        try:
            reservations = get_reservations()
            
            if not reservations:
                embed = discord.Embed(
                    title="Parking Pass Reservations",
                    description="No reservations found.",
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
                
                # determine status (no expired ones since those are filtered out as inactive)
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
                # Note: no else clause for EXPIRED since those reservations are filtered out
                
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
            await interaction.response.defer()
            
            # get target user memo
            target_memo = get_user_memo(user.id)
            if not target_memo:
                embed = discord.Embed(
                    title="Error",
                    description=f"No vehicle memo found for {user.display_name}. User must have a registered vehicle.",
                    color=discord.Color.red()
                )
                await interaction.followup.send(embed=embed)
                return
            
            # update transport scraper first
            transport = Scraper(notification_callback=interaction.followup)
            await transport.update_parking_pass(target_memo)
            
            # update database after successful transport update
            current_owner = get_current_owner()
            if current_owner and transfer_pass_with_lock(current_owner['current_owner_id'], user.id):
                # update bot status
                await bot.update_status()
                
                embed = discord.Embed(
                    title="Parking Pass Transferred",
                    description=f"Parking pass has been given to {user.display_name}\n**Vehicle:** {target_memo}",
                    color=discord.Color.green()
                )
                
                ping_message = f"<@{user.id}>, you have been given the parking pass!"
                await interaction.followup.send(content=ping_message, embed=embed)
                
            else:
                embed = discord.Embed(
                    title="Error",
                    description="Transport updated but database sync failed. Please check status.",
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=embed)
            
        except Exception as e:
            embed = discord.Embed(
                title="Error",
                description=f"Failed to transfer parking pass: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)

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
            await interaction.response.defer()
            
            # get the next unapproved reservation for this user
            next_reservation = get_user_next_unapproved_reservation(user.id)
            
            if not next_reservation:
                embed = discord.Embed(
                    title="No Reservation Found",
                    description=f"{user.display_name} has no pending reservations to approve.",
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=embed)
                return
            
            # approve the reservation in database
            approve_reservation_by_details(user.id, next_reservation['start_time'])
            
            # check if we should transfer immediately
            now = datetime.now(CDT)
            start_time = ensure_cdt_timezone(datetime.fromisoformat(next_reservation['start_time']))
            
            current_owner = get_current_owner()
            
            # transfer immediately if reservation should start now or already started
            should_transfer_now = (start_time <= now and 
                                 current_owner and 
                                 current_owner['current_owner_id'] == DEFAULT_OWNER_ID)
            
            transfer_msg = ""
            
            if should_transfer_now:
                # get target user memo for transport update
                target_memo = get_user_memo(user.id)
                if target_memo:
                    try:
                        # update transport
                        transport = Scraper(notification_callback=interaction.followup)
                        await transport.update_parking_pass(target_memo)
                        
                        # update database
                        if transfer_pass_with_lock(current_owner['current_owner_id'], user.id):
                            await bot.update_status()
                            transfer_msg = "\n\n**Pass transferred immediately** (no conflicts detected)"
                        else:
                            transfer_msg = "\n\n**Transport updated but database sync failed**"
                    except Exception as e:
                        transfer_msg = f"\n\n**Immediate transfer failed:** {str(e)}"
                        await interaction.followup.send(f"transport update failed: {str(e)}")
                else:
                    transfer_msg = "\n\n**No vehicle memo found for immediate transfer**"
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
                description=f"**Approved for:** {user.display_name}{memo_text}\n**Start:** {start.strftime('%B %d, %Y at %I:%M %p CDT')}\n**End:** {end.strftime('%B %d, %Y at %I:%M %p CDT')}{transfer_msg}",
                color=discord.Color.green()
            )
            
            ping_message = f"<@{user.id}>, your reservation has been approved!"
            await interaction.followup.send(content=ping_message, embed=embed)
            
        except Exception as e:
            embed = discord.Embed(
                title="Error",
                description=f"Failed to approve reservation: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
    
    @bot.tree.command(name="revoke", description="Revoke the most recent approved reservation for a user (Owner only)")
    async def revoke_command(interaction: discord.Interaction, user: discord.Member):
        """Revoke the most recent approved reservation for a specific user"""
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
            
            # get the most recent approved reservation for this user
            most_recent = get_user_most_recent_approved_reservation(user.id)
            
            if not most_recent:
                embed = discord.Embed(
                    title="No Reservation Found",
                    description=f"{user.display_name} has no approved reservations to revoke.",
                    color=discord.Color.orange()
                )
                await interaction.followup.send(embed=embed)
                return
            
            # check if this reservation is currently active
            now = datetime.now(CDT)
            start_time = ensure_cdt_timezone(datetime.fromisoformat(most_recent['start_time']))
            end_time = ensure_cdt_timezone(datetime.fromisoformat(most_recent['end_time']))
            current_owner = get_current_owner()
            
            is_currently_active = (start_time <= now <= end_time and 
                                current_owner and 
                                current_owner['current_owner_id'] == user.id)
            
            # mark the reservation as inactive
            mark_reservation_inactive(user.id, most_recent['start_time'])
            
            transfer_msg = ""
            
            # if this was the active reservation, transfer pass back to default owner
            if is_currently_active:
                try:
                    # attempt to transfer back to default owner with transport update
                    success = await bot.transfer_with_transport(user.id, DEFAULT_OWNER_ID)
                    if success:
                        await bot.update_status()
                        transfer_msg = "\n\n**Pass returned to default owner** (active reservation revoked)"
                    else:
                        transfer_msg = "\n\n**Transfer failed** - manual intervention may be required"
                except Exception as e:
                    transfer_msg = f"\n\n**Transfer failed:** {str(e)}"
                    await interaction.followup.send(f"Transport transfer failed: {str(e)}")
            
            # get user memo if available
            memo = get_user_memo(user.id)
            memo_text = f"\n**Vehicle:** {memo}" if memo else ""
            
            embed = discord.Embed(
                title="Reservation Revoked",
                description=f"**Revoked for:** {user.display_name}{memo_text}\n**Start:** {start_time.strftime('%B %d, %Y at %I:%M %p CDT')}\n**End:** {end_time.strftime('%B %d, %Y at %I:%M %p CDT')}\n**Status:** {'Was Active' if is_currently_active else 'Was Scheduled'}{transfer_msg}",
                color=discord.Color.red()
            )
            
            ping_message = f"<@{user.id}>, your approved reservation has been revoked by the owner."
            await interaction.followup.send(content=ping_message, embed=embed)
            
        except Exception as e:
            embed = discord.Embed(
                title="Error",
                description=f"Failed to revoke reservation: {str(e)}",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
