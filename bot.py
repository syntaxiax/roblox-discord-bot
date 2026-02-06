import discord
import aiohttp
import asyncio
import os
from discord.ext import commands, tasks
from discord import app_commands

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# CONFIGURATION - Change these values
CHANNEL_ID = None  # Will be set by /create command
GAME_IDS = [
    123456789,  # Replace with actual Roblox game universe IDs
    987654321,
    111222333,
]

# Store the message ID and current game so we can edit it
status_message = None
current_game_id = None

async def check_game_available(session, universe_id):
    """
    Comprehensive check if a Roblox game is available and joinable.
    Returns: (is_available, game_data, reason)
    """
    try:
        # Step 1: Check if game exists via Games API
        games_url = f"https://games.roblox.com/v1/games?universeIds={universe_id}"
        async with session.get(games_url) as response:
            if response.status != 200:
                return False, None, "API Error"
            
            data = await response.json()
            if not data.get('data') or len(data['data']) == 0:
                return False, None, "Game Not Found"
            
            game_data = data['data'][0]
            
            # Step 2: Check if game is playable
            if not game_data.get('isPlayable', False):
                return False, game_data, "Not Playable"
            
            # Step 3: Get the root place ID to check game status
            root_place_id = game_data.get('rootPlaceId')
            if not root_place_id:
                return False, game_data, "No Root Place"
            
            # Step 4: Check game details via the place API
            details_url = f"https://games.roblox.com/v1/games/multiget-place-details?placeIds={root_place_id}"
            async with session.get(details_url) as details_response:
                if details_response.status == 200:
                    details_data = await details_response.json()
                    if details_data and len(details_data) > 0:
                        place_details = details_data[0]
                        
                        # Check if place is banned or under review
                        if place_details.get('isBanned', False):
                            return False, game_data, "Banned"
                        
                        if place_details.get('isUnderReview', False):
                            return False, game_data, "Under Review"
            
            # Step 5: Check if we can get game instances (means it's actually running)
            instances_url = f"https://games.roblox.com/v1/games/{root_place_id}/servers/Public?limit=10"
            async with session.get(instances_url) as instances_response:
                if instances_response.status == 200:
                    instances_data = await instances_response.json()
                    # If game has active servers, it's definitely available
                    if instances_data.get('data') and len(instances_data['data']) > 0:
                        return True, game_data, "Available"
            
            # If all checks pass but no servers, still consider it available
            return True, game_data, "Available"
            
    except Exception as e:
        print(f"Error checking game {universe_id}: {e}")
        return False, None, f"Error: {str(e)}"

async def find_available_game(game_ids):
    """Find the first available game from the list"""
    print(f"🔍 Searching through {len(game_ids)} games...")
    async with aiohttp.ClientSession() as session:
        for game_id in game_ids:
            is_available, game_data, reason = await check_game_available(session, game_id)
            print(f"   Game {game_id}: {reason}")
            
            if is_available and game_data:
                print(f"✅ Found available game: {game_data['name']}")
                return game_id, game_data
            
            await asyncio.sleep(0.5)  # Rate limiting
    
    print("❌ No available games found")
    return None, None

# ============================================
# SLASH COMMANDS - DEFINED BEFORE on_ready
# ============================================

@bot.tree.command(name="create", description="Create the auto-updating game status message in this channel (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def create(interaction: discord.Interaction):
    global CHANNEL_ID, status_message, current_game_id
    
    print(f"📝 /create command called by {interaction.user} in channel {interaction.channel_id}")
    
    # Set the channel
    CHANNEL_ID = interaction.channel_id
    
    # Reset message tracking
    status_message = None
    current_game_id = None
    
    await interaction.response.send_message(
        f"✅ Bot activated in {interaction.channel.mention}!\n"
        f"🔄 Checking games now and will update every 2 minutes...",
        ephemeral=True
    )
    
    # Start the auto-check if not running
    if not auto_check_games.is_running():
        print("▶️ Starting auto_check_games task...")
        auto_check_games.start()
    else:
        print("ℹ️ auto_check_games task already running")
    
    # Do an immediate check
    print("🔍 Running immediate game check...")
    try:
        await auto_check_games()
    except Exception as e:
        print(f"❌ Error during immediate check: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"✅ Bot activated in channel {CHANNEL_ID}")

@bot.tree.command(name="destroy", description="Stop the bot and delete the status message (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def destroy(interaction: discord.Interaction):
    global CHANNEL_ID, status_message, current_game_id
    
    print(f"🗑️ /destroy command called by {interaction.user}")
    
    # Try to delete the status message
    if status_message:
        try:
            await status_message.delete()
            print("🗑️ Deleted status message")
        except discord.NotFound:
            print("⚠️ Status message already deleted")
        except Exception as e:
            print(f"❌ Error deleting message: {e}")
    
    # Stop the auto-check loop
    if auto_check_games.is_running():
        auto_check_games.stop()
        print("⏸️ Stopped auto-check loop")
    
    # Reset everything
    CHANNEL_ID = None
    status_message = None
    current_game_id = None
    
    await interaction.response.send_message(
        "✅ Bot deactivated! Status message deleted and monitoring stopped.",
        ephemeral=True
    )
    
    print("🛑 Bot deactivated")

@bot.tree.command(name="checkgame", description="Manually check for available games right now")
async def checkgame(interaction: discord.Interaction):
    if CHANNEL_ID is None:
        await interaction.response.send_message(
            "❌ Bot is not active! Use `/create` first to activate it in a channel.",
            ephemeral=True
        )
        return
    
    print(f"🔍 /checkgame command called by {interaction.user}")
    await interaction.response.send_message("🔍 Checking games now...", ephemeral=True)
    
    try:
        await auto_check_games()
    except Exception as e:
        print(f"❌ Error during manual check: {e}")
        import traceback
        traceback.print_exc()

@bot.tree.command(name="forcenext", description="Force switch to the next available game (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def forcenext(interaction: discord.Interaction):
    global current_game_id
    
    if CHANNEL_ID is None:
        await interaction.response.send_message(
            "❌ Bot is not active! Use `/create` first to activate it in a channel.",
            ephemeral=True
        )
        return
    
    print(f"🔄 /forcenext command called by {interaction.user}")
    current_game_id = None  # Reset current game
    await interaction.response.send_message("🔄 Forcing check for next game...", ephemeral=True)
    
    try:
        await auto_check_games()
    except Exception as e:
        print(f"❌ Error during force next: {e}")
        import traceback
        traceback.print_exc()

@bot.tree.command(name="addgame", description="Add a game to the monitoring list (Admin only)")
@app_commands.describe(universe_id="The Roblox Universe ID of the game to add")
@app_commands.checks.has_permissions(administrator=True)
async def addgame(interaction: discord.Interaction, universe_id: int):
    print(f"➕ /addgame {universe_id} called by {interaction.user}")
    
    if universe_id not in GAME_IDS:
        GAME_IDS.append(universe_id)
        await interaction.response.send_message(
            f"✅ Added game `{universe_id}` to the monitoring list!\n"
            f"📊 Now monitoring {len(GAME_IDS)} game(s).",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(f"⚠️ Game `{universe_id}` is already in the list!", ephemeral=True)

@bot.tree.command(name="removegame", description="Remove a game from the monitoring list (Admin only)")
@app_commands.describe(universe_id="The Roblox Universe ID of the game to remove")
@app_commands.checks.has_permissions(administrator=True)
async def removegame(interaction: discord.Interaction, universe_id: int):
    print(f"➖ /removegame {universe_id} called by {interaction.user}")
    
    if universe_id in GAME_IDS:
        GAME_IDS.remove(universe_id)
        await interaction.response.send_message(
            f"✅ Removed game `{universe_id}` from the monitoring list!\n"
            f"📊 Now monitoring {len(GAME_IDS)} game(s).",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(f"⚠️ Game `{universe_id}` is not in the list!", ephemeral=True)

@bot.tree.command(name="listgames", description="Show all games being monitored")
async def listgames(interaction: discord.Interaction):
    if GAME_IDS:
        games_list = "\n".join([f"• `{game_id}`" for game_id in GAME_IDS])
        embed = discord.Embed(
            title="🎮 Monitored Games",
            description=f"Currently monitoring **{len(GAME_IDS)}** game(s):\n\n{games_list}",
            color=discord.Color.blue()
        )
        if CHANNEL_ID:
            embed.add_field(
                name="Active Channel",
                value=f"<#{CHANNEL_ID}>",
                inline=False
            )
        else:
            embed.add_field(
                name="Status",
                value="⚠️ Bot not active. Use `/create` to activate.",
                inline=False
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ No games in the monitoring list!", ephemeral=True)

@bot.tree.command(name="status", description="Show bot status and configuration")
async def status(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Bot Status",
        color=discord.Color.blue()
    )
    
    if CHANNEL_ID:
        embed.add_field(name="Status", value="✅ Active", inline=True)
        embed.add_field(name="Channel", value=f"<#{CHANNEL_ID}>", inline=True)
    else:
        embed.add_field(name="Status", value="⚠️ Inactive", inline=True)
        embed.add_field(name="Channel", value="None", inline=True)
    
    embed.add_field(name="Monitored Games", value=len(GAME_IDS), inline=True)
    embed.add_field(name="Auto-Check", value="Running" if auto_check_games.is_running() else "Stopped", inline=True)
    
    if current_game_id:
        embed.add_field(name="Current Game", value=f"`{current_game_id}`", inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# Error handlers for slash commands
@create.error
@destroy.error
@forcenext.error
@addgame.error
@removegame.error
async def permission_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You need Administrator permission to use this command!", ephemeral=True)

# ============================================
# AUTO-CHECK TASK & BOT EVENTS
# ============================================

@tasks.loop(minutes=2)  # Check every 2 minutes
async def auto_check_games():
    """Automatically check games and update the channel message"""
    global status_message, current_game_id
    
    print(f"\n{'='*50}")
    print(f"🔄 Auto-check triggered at {discord.utils.utcnow()}")
    print(f"{'='*50}")
    
    if CHANNEL_ID is None:
        print("⚠️ No channel set, skipping check")
        return
    
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"❌ Channel {CHANNEL_ID} not found!")
        return
    
    print(f"📍 Checking games for channel: #{channel.name} ({CHANNEL_ID})")
    
    game_id, game_data = await find_available_game(GAME_IDS)
    
    # Only update message if the game changed or if no message exists
    if game_id and game_data:
        # Check if this is a different game than what we're currently showing
        if current_game_id != game_id or status_message is None:
            current_game_id = game_id
            
            print(f"📝 Creating/updating embed for: {game_data['name']}")
            
            embed = discord.Embed(
                title="🎮 Available Game",
                description=f"**{game_data['name']}**",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            
            root_place_id = game_data.get('rootPlaceId', game_id)
            embed.add_field(name="Universe ID", value=game_id, inline=True)
            embed.add_field(name="Place ID", value=root_place_id, inline=True)
            embed.add_field(name="Playing", value=f"{game_data.get('playing', 0):,}", inline=True)
            embed.add_field(
                name="▶️ Join Game", 
                value=f"[Click to Play](https://www.roblox.com/games/{root_place_id})", 
                inline=False
            )
            
            if game_data.get('description'):
                desc = game_data['description']
                if len(desc) > 200:
                    desc = desc[:197] + "..."
                embed.add_field(name="Description", value=desc, inline=False)
            
            embed.set_footer(text="🔄 Game switched • Auto-updates every 2 minutes")
            
            if status_message:
                try:
                    print(f"✏️ Editing existing message...")
                    await status_message.edit(embed=embed)
                    print(f"✅ Updated to new game: {game_data['name']}")
                except discord.NotFound:
                    print(f"⚠️ Message not found, creating new one...")
                    status_message = await channel.send(embed=embed)
                    print(f"📝 Created new status message (ID: {status_message.id})")
                except Exception as e:
                    print(f"❌ Error editing message: {e}")
                    import traceback
                    traceback.print_exc()
                    status_message = await channel.send(embed=embed)
                    print(f"📝 Created new status message (ID: {status_message.id})")
            else:
                print(f"📝 Creating new status message...")
                try:
                    status_message = await channel.send(embed=embed)
                    print(f"✅ Created new status message (ID: {status_message.id}) for: {game_data['name']}")
                except Exception as e:
                    print(f"❌ Error creating message: {e}")
                    import traceback
                    traceback.print_exc()
        else:
            # Same game still available
            print(f"ℹ️ Same game still available: {game_data['name']}")
    else:
        # No available games found
        print("❌ No available games found")
        if current_game_id is not None or status_message is None:
            current_game_id = None
            
            print("📝 Creating/updating 'no games' embed...")
            
            embed = discord.Embed(
                title="⏳ No Available Games",
                description="All games in the list are currently unavailable, banned, or under review.\n\n"
                           "The bot will automatically switch to an available game when one becomes active.",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="🔍 Checking for available games every 2 minutes...")
            
            if status_message:
                try:
                    await status_message.edit(embed=embed)
                    print("✅ Updated to 'no games' message")
                except discord.NotFound:
                    status_message = await channel.send(embed=embed)
                    print(f"📝 Created 'no games' message (ID: {status_message.id})")
                except Exception as e:
                    print(f"❌ Error editing message: {e}")
                    status_message = await channel.send(embed=embed)
                    print(f"📝 Created 'no games' message (ID: {status_message.id})")
            else:
                status_message = await channel.send(embed=embed)
                print(f"📝 Created 'no games' status message (ID: {status_message.id})")
    
    print(f"{'='*50}\n")

@bot.event
async def on_ready():
    print(f'\n{'='*50}')
    print(f'✅ {bot.user} is now running!')
    print(f'📊 Bot is in {len(bot.guilds)} guilds')
    print(f'{'='*50}\n')
    
    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash command(s):")
        for cmd in synced:
            print(f"   - /{cmd.name}")
    except Exception as e:
        print(f"❌ Failed to sync commands: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n💡 Use /create in a channel to activate the bot!")
    print("💡 Use /destroy to stop the bot and delete the message\n")

# Get token from environment variable
TOKEN = os.getenv('DISCORD_TOKEN')
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ ERROR: DISCORD_TOKEN not found in environment variables!")
