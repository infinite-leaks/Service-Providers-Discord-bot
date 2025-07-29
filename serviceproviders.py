import discord
from discord.ext import commands, tasks
import requests
import asyncio
import os
import json
import aiohttp
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List
import sqlite3

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', '0'))

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not found in .env file!")
    exit(1)

if not OWNER_ID:
    print("ERROR: OWNER_ID not found in .env file!")
    exit(1)

SERVICES = {
    "vercel": "https://vercel.statuspage.io/api/v2",
    "cloudflare": "https://www.cloudflarestatus.com/api/v2", 
    "netlify": "https://www.netlifystatus.com/api/v2"
}

# Database setup - only store essential data
def init_db():
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    
    # Table for webhook configurations - minimal columns
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS webhooks (
            guild_id INTEGER,
            channel_id INTEGER,
            webhook_url TEXT,
            service TEXT,
            ping_role_id INTEGER,
            enabled INTEGER DEFAULT 1,
            last_incident_id TEXT,
            PRIMARY KEY (guild_id, service)
        )
    ''')
    
    conn.commit()
    conn.close()

class StatusBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='!', intents=intents)
        
        self.session = None
        init_db()
        
    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        # Start the auto-posting task
        self.auto_post_status.start()
        
        # Sync commands
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(f"Failed to sync commands: {e}")

    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()

    @tasks.loop(minutes=5)  # Check every 5 minutes
    async def auto_post_status(self):
        await self.check_and_post_incidents()

    @auto_post_status.before_loop
    async def before_auto_post(self):
        await self.wait_until_ready()

    async def get_service_data(self, service_name: str) -> Dict:
        """Fetch service status data"""
        url = SERVICES.get(service_name)
        if not url:
            return None
            
        try:
            async with self.session.get(f"{url}/status.json") as resp:
                status = await resp.json()
            async with self.session.get(f"{url}/incidents.json") as resp:
                incidents_data = await resp.json()
            async with self.session.get(f"{url}/components.json") as resp:
                components_data = await resp.json()
                
            return {
                'status': status,
                'incidents': incidents_data.get('incidents', []),
                'components': components_data.get('components', [])
            }
        except Exception as e:
            print(f"Error fetching {service_name} data: {e}")
            return None

    def create_status_embed(self, service_name: str, data: Dict) -> discord.Embed:
        """Create a Discord embed for service status"""
        status = data['status']['status']
        description = status['description']
        indicator = status['indicator']
        
        # Color based on status
        color = 0x00ff00 if indicator == "none" else 0xffff00 if indicator == "minor" else 0xff0000
        
        embed = discord.Embed(
            title=f"{service_name.capitalize()} Status",
            description=f"**Overall Status:** {description}",
            color=color,
            timestamp=datetime.now(timezone.utc)  # UTC timezone aware
        )
        
        # Add incidents
        incidents = data['incidents'][:3]  # Show max 3 incidents
        if incidents:
            incident_text = ""
            for incident in incidents:
                name = incident.get('name', 'Unnamed incident')
                status = incident.get('status', 'unknown')
                update = incident.get('incident_updates', [{}])[0].get('body', '')
                
                incident_text += f"**{name}** ({status})\n"
                if update:
                    # Truncate long updates
                    if len(update) > 200:
                        update = update[:200] + "..."
                    incident_text += f"{update}\n\n"
            
            embed.add_field(name="Recent Incidents", value=incident_text, inline=False)
        else:
            embed.add_field(name="Incidents", value="No current incidents", inline=False)
        
        # Add component status
        components = data['components']
        bad_components = [c for c in components if c.get('status') != 'operational']
        
        if bad_components:
            comp_text = ""
            for comp in bad_components[:5]:  # Show max 5 components
                comp_text += f"• {comp['name']}: {comp['status']}\n"
            embed.add_field(name="Affected Components", value=comp_text, inline=False)
        else:
            embed.add_field(name="Components", value="All systems operational", inline=False)
        
        embed.set_footer(text="Last updated")
        return embed

    async def check_and_post_incidents(self):
        """Check for new incidents and post them via webhooks"""
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM webhooks WHERE enabled = 1')
        webhook_configs = cursor.fetchall()
        
        for config in webhook_configs:
            guild_id, channel_id, webhook_url, service, ping_role_id, enabled, last_incident_id = config
            
            data = await self.get_service_data(service)
            if not data or not data['incidents']:
                continue
                
            latest_incident = data['incidents'][0]
            latest_incident_id = latest_incident.get('id')
            
            # Check if this is a new incident
            if latest_incident_id != last_incident_id:
                embed = self.create_status_embed(service, data)
                
                # Prepare webhook payload
                webhook_data = {"embeds": [embed.to_dict()]}
                
                # Add ping if role is set
                if ping_role_id:
                    webhook_data["content"] = f"<@&{ping_role_id}> {service.capitalize()} status update!"
                
                # Send webhook
                try:
                    async with self.session.post(webhook_url, json=webhook_data) as resp:
                        if resp.status == 204:
                            # Update last incident ID
                            cursor.execute(
                                'UPDATE webhooks SET last_incident_id = ? WHERE guild_id = ? AND service = ?',
                                (latest_incident_id, guild_id, service)
                            )
                            conn.commit()
                except Exception as e:
                    print(f"Error sending webhook for {service} in guild {guild_id}: {e}")
        
        conn.close()

bot = StatusBot()

# Owner-only check decorator
def is_owner():
    def predicate(interaction: discord.Interaction) -> bool:
        return interaction.user.id == OWNER_ID
    return discord.app_commands.check(predicate)

@bot.tree.command(name="sendmessage", description="[OWNER ONLY] Send a message to a channel")
@discord.app_commands.describe(
    channel="Channel to send message to",
    message="Message content to send",
    count="Number of times to send the message (default: 1, max: 50)",
    delay="Delay between messages in seconds (default: 1, 0 for ultra-fast)"
)
@is_owner()
async def send_message(interaction: discord.Interaction, channel: discord.TextChannel, message: str, count: int = 1, delay: float = 1.0):
    # Validation
    if count < 1 or count > 50:
        await interaction.response.send_message("❌ Count must be between 1 and 50.", ephemeral=True)
        return
    
    if delay < 0:
        await interaction.response.send_message("❌ Delay cannot be negative.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    sent_count = 0
    failed_count = 0
    
    try:
        for i in range(count):
            try:
                await channel.send(message)
                sent_count += 1
                
                # Add delay between messages (unless ultra-fast mode)
                if delay > 0 and i < count - 1:
                    await asyncio.sleep(delay)
                    
            except discord.Forbidden:
                failed_count += 1
                break  # No point trying more if we don't have permission
            except discord.HTTPException as e:
                if e.status == 429:  # Rate limited
                    await asyncio.sleep(1)  # Wait a bit and continue
                    failed_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1
        
        # Send results
        result_msg = f"✅ Sent {sent_count}/{count} messages to {channel.mention}"
        if failed_count > 0:
            result_msg += f"\n❌ Failed: {failed_count} messages"
        if delay == 0 and count > 1:
            result_msg += "\n⚡ Ultra-fast mode used"
            
        await interaction.followup.send(result_msg)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}")

@bot.tree.command(name="sendembed", description="[OWNER ONLY] Send an embed to a channel")
@discord.app_commands.describe(
    channel="Channel to send embed to",
    title="Embed title",
    description="Embed description",
    color="Hex color (e.g., 0x00ff00 for green, 0xff0000 for red)",
    count="Number of times to send the embed (default: 1, max: 50)",
    delay="Delay between embeds in seconds (default: 1, 0 for ultra-fast)"
)
@is_owner()
async def send_embed(interaction: discord.Interaction, channel: discord.TextChannel, title: str, description: str, color: Optional[str] = None, count: int = 1, delay: float = 1.0):
    # Validation
    if count < 1 or count > 50:
        await interaction.response.send_message("❌ Count must be between 1 and 50.", ephemeral=True)
        return
    
    if delay < 0:
        await interaction.response.send_message("❌ Delay cannot be negative.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Parse color
        embed_color = 0x0099ff  # Default blue
        if color:
            if color.startswith('0x'):
                embed_color = int(color, 16)
            elif color.startswith('#'):
                embed_color = int(color[1:], 16)
            else:
                embed_color = int(color, 16)
        
        sent_count = 0
        failed_count = 0
        
        for i in range(count):
            try:
                embed = discord.Embed(
                    title=title,
                    description=description,
                    color=embed_color,
                    timestamp=datetime.now(timezone.utc)
                )
                embed.set_footer(text=f"Sent via Status Bot {f'({i+1}/{count})' if count > 1 else ''}")
                
                await channel.send(embed=embed)
                sent_count += 1
                
                # Add delay between messages (unless ultra-fast mode)
                if delay > 0 and i < count - 1:
                    await asyncio.sleep(delay)
                    
            except discord.Forbidden:
                failed_count += 1
                break  # No point trying more if we don't have permission
            except discord.HTTPException as e:
                if e.status == 429:  # Rate limited
                    await asyncio.sleep(1)  # Wait a bit and continue
                    failed_count += 1
                else:
                    failed_count += 1
            except Exception:
                failed_count += 1
        
        # Send results
        result_msg = f"✅ Sent {sent_count}/{count} embeds to {channel.mention}"
        if failed_count > 0:
            result_msg += f"\n❌ Failed: {failed_count} embeds"
        if delay == 0 and count > 1:
            result_msg += "\n⚡ Ultra-fast mode used"
            
        await interaction.followup.send(result_msg)
        
    except ValueError:
        await interaction.followup.send("❌ Invalid color format. Use hex format like 0x00ff00 or #00ff00")
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {str(e)}")

@bot.tree.command(name="broadcast", description="[OWNER ONLY] Send a message to all servers")
@discord.app_commands.describe(
    message="Message to broadcast",
    embed_format="Send as embed instead of plain message",
    count="Number of times to send to each server (default: 1, max: 10)",
    delay="Delay between messages in seconds (default: 2, 0 for ultra-fast)"
)
@is_owner()
async def broadcast(interaction: discord.Interaction, message: str, embed_format: bool = False, count: int = 1, delay: float = 2.0):
    # Validation
    if count < 1 or count > 10:
        await interaction.response.send_message("❌ Count must be between 1 and 10 for broadcasts.", ephemeral=True)
        return
    
    if delay < 0:
        await interaction.response.send_message("❌ Delay cannot be negative.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    total_sent = 0
    total_failed = 0
    servers_reached = 0
    
    for guild in bot.guilds:
        # Find a suitable channel (general, first text channel, or system channel)
        target_channel = None
        
        # Try system channel first
        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            target_channel = guild.system_channel
        else:
            # Find first channel we can send messages to
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    target_channel = channel
                    break
        
        if target_channel:
            sent_to_guild = 0
            failed_to_guild = 0
            
            for i in range(count):
                try:
                    if embed_format:
                        embed = discord.Embed(
                            title="📢 Broadcast Message",
                            description=message,
                            color=0x0099ff,
                            timestamp=datetime.now(timezone.utc)
                        )
                        embed.set_footer(text=f"Status Bot Broadcast {f'({i+1}/{count})' if count > 1 else ''}")
                        await target_channel.send(embed=embed)
                    else:
                        await target_channel.send(message)
                    
                    sent_to_guild += 1
                    total_sent += 1
                    
                    # Add delay between messages (unless ultra-fast mode)
                    if delay > 0 and i < count - 1:
                        await asyncio.sleep(delay)
                        
                except discord.HTTPException as e:
                    if e.status == 429:  # Rate limited
                        await asyncio.sleep(2)  # Wait longer for broadcasts
                        failed_to_guild += 1
                        total_failed += 1
                    else:
                        failed_to_guild += 1
                        total_failed += 1
                except Exception:
                    failed_to_guild += 1
                    total_failed += 1
            
            if sent_to_guild > 0:
                servers_reached += 1
                
            # Small delay between servers to avoid overwhelming Discord
            if delay > 0:
                await asyncio.sleep(0.5)
                
        else:
            total_failed += count
    
    result_msg = f"✅ Broadcast complete!\n"
    result_msg += f"📊 **Statistics:**\n"
    result_msg += f"• Servers reached: {servers_reached}/{len(bot.guilds)}\n"
    result_msg += f"• Messages sent: {total_sent}\n"
    result_msg += f"• Failed sends: {total_failed}"
    
    if delay == 0 and count > 1:
        result_msg += "\n⚡ Ultra-fast mode used"
    
    await interaction.followup.send(result_msg)

@bot.tree.command(name="multisend", description="[OWNER ONLY] Send message to multiple servers by ID")
@discord.app_commands.describe(
    server_ids="Comma-separated server IDs (e.g., 123456789,987654321)",
    message="Message to send",
    embed_format="Send as embed instead of plain message",
    count="Number of times to send to each server (default: 1, max: 20)",
    delay="Delay between messages in seconds (default: 1, 0 for ultra-fast)"
)
@is_owner()
async def multi_send(interaction: discord.Interaction, server_ids: str, message: str, embed_format: bool = False, count: int = 1, delay: float = 1.0):
    # Validation
    if count < 1 or count > 20:
        await interaction.response.send_message("❌ Count must be between 1 and 20.", ephemeral=True)
        return
    
    if delay < 0:
        await interaction.response.send_message("❌ Delay cannot be negative.", ephemeral=True)
        return
    
    # Parse server IDs
    try:
        guild_ids = [int(id_str.strip()) for id_str in server_ids.split(',')]
    except ValueError:
        await interaction.response.send_message("❌ Invalid server ID format. Use comma-separated numbers.", ephemeral=True)
        return
    
    if len(guild_ids) > 20:
        await interaction.response.send_message("❌ Maximum 20 servers allowed per command.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    results = {}
    total_sent = 0
    total_failed = 0
    
    for guild_id in guild_ids:
        guild = bot.get_guild(guild_id)
        if not guild:
            results[guild_id] = "❌ Server not found or bot not in server"
            total_failed += count
            continue
        
        # Find suitable channel
        target_channel = None
        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            target_channel = guild.system_channel
        else:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    target_channel = channel
                    break
        
        if not target_channel:
            results[guild_id] = f"❌ No accessible channel in {guild.name}"
            total_failed += count
            continue
        
        # Send messages
        sent_to_guild = 0
        failed_to_guild = 0
        
        for i in range(count):
            try:
                if embed_format:
                    embed = discord.Embed(
                        title="📨 Multi-Server Message",
                        description=message,
                        color=0x00ff99,
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.set_footer(text=f"Sent to {guild.name} {f'({i+1}/{count})' if count > 1 else ''}")
                    await target_channel.send(embed=embed)
                else:
                    await target_channel.send(message)
                
                sent_to_guild += 1
                total_sent += 1
                
                # Add delay between messages
                if delay > 0 and i < count - 1:
                    await asyncio.sleep(delay)
                    
            except discord.HTTPException as e:
                if e.status == 429:  # Rate limited
                    await asyncio.sleep(1)
                failed_to_guild += 1
                total_failed += 1
            except Exception:
                failed_to_guild += 1
                total_failed += 1
        
        if sent_to_guild == count:
            results[guild_id] = f"✅ {guild.name}: {sent_to_guild}/{count} sent"
        else:
            results[guild_id] = f"⚠️ {guild.name}: {sent_to_guild}/{count} sent, {failed_to_guild} failed"
        
        # Small delay between servers
        if delay > 0 and len(guild_ids) > 1:
            await asyncio.sleep(0.3)
    
    # Format results
    result_msg = f"📊 **Multi-Server Send Results:**\n"
    result_msg += f"Total sent: {total_sent} | Total failed: {total_failed}\n\n"
    
    for guild_id, result in results.items():
        result_msg += f"`{guild_id}` - {result}\n"
    
    if delay == 0 and count > 1:
        result_msg += "\n⚡ Ultra-fast mode used"
    
    # Split message if too long
    if len(result_msg) > 2000:
        parts = [result_msg[i:i+1900] for i in range(0, len(result_msg), 1900)]
        await interaction.followup.send(parts[0])
        for part in parts[1:]:
            await interaction.followup.send(part)
    else:
        await interaction.followup.send(result_msg)
@is_owner()
async def bot_stats(interaction: discord.Interaction):
    # Get webhook count
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM webhooks WHERE enabled = 1')
    active_webhooks = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(DISTINCT guild_id) FROM webhooks')
    guilds_with_webhooks = cursor.fetchone()[0]
    conn.close()
    
    embed = discord.Embed(
        title="🤖 Bot Statistics",
        color=0x0099ff,
        timestamp=datetime.now(timezone.utc)
    )
    
    embed.add_field(name="Servers", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="Active Webhooks", value=str(active_webhooks), inline=True)
    embed.add_field(name="Servers with Webhooks", value=str(guilds_with_webhooks), inline=True)
    embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)}ms", inline=True)
    
    # Uptime calculation
    uptime = datetime.now(timezone.utc) - bot.start_time if hasattr(bot, 'start_time') else timedelta(0)
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    embed.add_field(name="Uptime", value=f"{days}d {hours}h {minutes}m", inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="checkstatus", description="Check the current status of a service")
@discord.app_commands.describe(service="The service to check status for")
@discord.app_commands.choices(service=[
    discord.app_commands.Choice(name="Vercel", value="vercel"),
    discord.app_commands.Choice(name="Cloudflare", value="cloudflare"),
    discord.app_commands.Choice(name="Netlify", value="netlify")
])
async def check_status(interaction: discord.Interaction, service: str):
    await interaction.response.defer()
    
    data = await bot.get_service_data(service)
    if not data:
        await interaction.followup.send(f"❌ Failed to fetch {service} status data.")
        return
    
    embed = bot.create_status_embed(service, data)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="setupwebhook", description="Setup auto-posting for service status updates")
@discord.app_commands.describe(
    channel="Channel to post updates in",
    service="Service to monitor", 
    ping_role="Role to ping when posting updates (optional)"
)
@discord.app_commands.choices(service=[
    discord.app_commands.Choice(name="Vercel", value="vercel"),
    discord.app_commands.Choice(name="Cloudflare", value="cloudflare"), 
    discord.app_commands.Choice(name="Netlify", value="netlify")
])
async def setup_webhook(interaction: discord.Interaction, channel: discord.TextChannel, service: str, ping_role: Optional[discord.Role] = None):
    # Check permissions
    if not interaction.user.guild_permissions.manage_webhooks:
        await interaction.response.send_message("❌ You need 'Manage Webhooks' permission to use this command.", ephemeral=True)
        return
    
    await interaction.response.defer()
    
    try:
        # Create webhook
        webhook = await channel.create_webhook(name=f"{service.capitalize()} Status Bot")
        
        # Store in database
        conn = sqlite3.connect('bot_data.db')
        cursor = conn.cursor()
        
        ping_role_id = ping_role.id if ping_role else None
        
        cursor.execute('''
            INSERT OR REPLACE INTO webhooks 
            (guild_id, channel_id, webhook_url, service, ping_role_id, enabled, last_incident_id)
            VALUES (?, ?, ?, ?, ?, 1, NULL)
        ''', (interaction.guild.id, channel.id, webhook.url, service, ping_role_id))
        
        conn.commit()
        conn.close()
        
        embed = discord.Embed(
            title="✅ Webhook Setup Complete",
            description=f"Auto-posting enabled for **{service.capitalize()}** in {channel.mention}",
            color=0x00ff00
        )
        
        if ping_role:
            embed.add_field(name="Ping Role", value=ping_role.mention, inline=True)
        
        embed.add_field(name="Check Interval", value="Every 5 minutes", inline=True)
        
        await interaction.followup.send(embed=embed)
        
    except discord.Forbidden:
        await interaction.followup.send("❌ I don't have permission to create webhooks in that channel.")
    except Exception as e:
        await interaction.followup.send(f"❌ Error setting up webhook: {str(e)}")

@bot.tree.command(name="removewebhook", description="Remove auto-posting for a service")
@discord.app_commands.describe(service="Service to stop monitoring")
@discord.app_commands.choices(service=[
    discord.app_commands.Choice(name="Vercel", value="vercel"),
    discord.app_commands.Choice(name="Cloudflare", value="cloudflare"),
    discord.app_commands.Choice(name="Netlify", value="netlify")
])
async def remove_webhook(interaction: discord.Interaction, service: str):
    if not interaction.user.guild_permissions.manage_webhooks:
        await interaction.response.send_message("❌ You need 'Manage Webhooks' permission to use this command.", ephemeral=True)
        return
    
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM webhooks WHERE guild_id = ? AND service = ?', (interaction.guild.id, service))
    
    if cursor.rowcount > 0:
        conn.commit()
        await interaction.response.send_message(f"✅ Removed auto-posting for {service.capitalize()}")
    else:
        await interaction.response.send_message(f"❌ No webhook found for {service.capitalize()}")
    
    conn.close()

@bot.tree.command(name="listwebhooks", description="List all active webhooks in this server")
async def list_webhooks(interaction: discord.Interaction):
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT service, channel_id, ping_role_id, enabled FROM webhooks WHERE guild_id = ?', (interaction.guild.id,))
    webhooks = cursor.fetchall()
    
    if not webhooks:
        await interaction.response.send_message("No webhooks configured for this server.")
        conn.close()
        return
    
    embed = discord.Embed(title="Active Webhooks", color=0x0099ff)
    
    for service, channel_id, ping_role_id, enabled in webhooks:
        channel = bot.get_channel(channel_id)
        channel_name = channel.mention if channel else "Unknown Channel"
        
        role_name = "None"
        if ping_role_id:
            role = interaction.guild.get_role(ping_role_id)
            role_name = role.mention if role else "Deleted Role"
        
        status = "✅ Enabled" if enabled else "❌ Disabled"
        
        embed.add_field(
            name=f"{service.capitalize()}",
            value=f"Channel: {channel_name}\nPing Role: {role_name}\nStatus: {status}",
            inline=True
        )
    
    conn.close()
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="togglewebhook", description="Enable or disable a webhook")
@discord.app_commands.describe(service="Service webhook to toggle")
@discord.app_commands.choices(service=[
    discord.app_commands.Choice(name="Vercel", value="vercel"),
    discord.app_commands.Choice(name="Cloudflare", value="cloudflare"),
    discord.app_commands.Choice(name="Netlify", value="netlify")
])
async def toggle_webhook(interaction: discord.Interaction, service: str):
    if not interaction.user.guild_permissions.manage_webhooks:
        await interaction.response.send_message("❌ You need 'Manage Webhooks' permission to use this command.", ephemeral=True)
        return
    
    conn = sqlite3.connect('bot_data.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT enabled FROM webhooks WHERE guild_id = ? AND service = ?', (interaction.guild.id, service))
    result = cursor.fetchone()
    
    if not result:
        await interaction.response.send_message(f"❌ No webhook found for {service.capitalize()}")
        conn.close()
        return
    
    new_status = not result[0]
    cursor.execute('UPDATE webhooks SET enabled = ? WHERE guild_id = ? AND service = ?', (new_status, interaction.guild.id, service))
    conn.commit()
    
    status_text = "enabled" if new_status else "disabled"
    await interaction.response.send_message(f"✅ {service.capitalize()} webhook has been {status_text}")
    
    conn.close()

@bot.event
async def on_ready():
    bot.start_time = datetime.now(timezone.utc)  # Track start time for uptime
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is in {len(bot.guilds)} guilds')
    print(f'Owner ID: {OWNER_ID}')

# Error handler for owner-only commands
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.CheckFailure):
        owner_commands = ['sendmessage', 'sendembed', 'broadcast', 'botstats', 'multisend', 'spamchannel']
        if interaction.command.name in owner_commands:
            await interaction.response.send_message("❌ This command is restricted to the bot owner only.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
    else:
        print(f"Command error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An error occurred while executing the command.", ephemeral=True)

if __name__ == "__main__":
    bot.run(BOT_TOKEN)
