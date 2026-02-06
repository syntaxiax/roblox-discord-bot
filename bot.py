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

# CONFIGURATION - Now accepts Place IDs!
CHANNEL_ID = None  # Will be set by /create command
GAME_IDS = [
    18687417158,  # You can use Place IDs directly from URLs!
    # Add more Place IDs here
]

# Cache to store Place ID -> Universe ID mappings
place_to_universe_cache = {}

# Store the message ID and current game so we can edit it
status_message = None
current_game_id = None

async def get_universe_id_from_place(session, place_id):
    """Convert a Place ID to Universe ID"""
    # Check cache first
    if place_id in place_to_universe_cache:
        return place_to_universe_cache[place_id]
    
    try:
        url = f"https://apis.roblox.com/universes/v1/places/{place_id}/universe"
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                universe_id = data.get('universeId')
                if universe_id:
                    place_to_universe_cache[place_id] = universe_id
                    return universe_id
    except Exception as e:
        print(f"Error converting Place ID {place_id} to Universe ID: {e}")
    
    return None

async def check_game_available(session, game_id):
    """
    Comprehensive check if a Roblox game is available and joinable.
    Accepts either Place ID or Universe ID.
    Returns: (is_available, game_data, reason, place_id)
    """
    try:
        print(f"\n🔍 Checking game ID: {game_id}")
        
        # First, try to get universe ID (in case game_id is a place ID)
        universe_id = await get_universe_id_from_place(session, game_id)
        
        # If conversion failed, assume it's already a universe ID
        if universe_id is None:
            print(f"   → Using {game_id} as Universe ID directly")
            universe_id = game_id
            place_id = None
        else:
            print(f"   → Converted Place ID {game_id} to Universe ID {universe_id}")
            place_id = game_id
        
        # Step 1: Check if game exists via Games API
        games_url = f"https://games.roblox.com/v1/games?universeIds={universe_id}"
        print(f"   → Fetching game data from API...")
        async with session.get(games_url) as response:
            if response.status != 200:
                print(f"   ❌ API Error: Status {response.status}")
                return False, None, "API Error", None
            
            data = await response.json()
            
            if not data.get('data') or len(data['data']) == 0:
                print(f"   ❌ Game not found in API response")
                return False, None, "Game Not Found", None
            
            game_data = data['data'][0]
            print(f"   → Game found: {game_data.get('name')}")
            print(f"   → Playing: {game_data.get('playing', 0)}")
            print(f"   → rootPlaceId: {game_data.get('rootPlaceId')}")
            
            # Get the root place ID
            root_place_id = game_data.get('rootPlaceId')
            if not root_place_id:
                print(f"   ❌ No root place ID found")
                return False, game_data, "No Root Place", None
            
            # Step 2: Check game details via the place API - ONLY check for bans/review
            details_url = f"https://games.roblox.com/v1/games/multiget-place-details?placeIds={root_place_id}"
            print(f"   → Checking if game is banned or under review...")
            async with session.get(details_url) as details_response:
                if details_response.status == 200:
                    details_data = await details_response.json()
                    
                    if details_data and len(details_data) > 0:
                        place_details = details_data[0]
                        
                        # Check if place is banned or under review
                        is_banned = place_details.get('isBanned', False)
                        is_under_review = place_details.get('isUnderReview', False)
                        
                        print(f"   → isBanned: {is_banned}")
                        print(f"   → isUnderReview: {is_under_review}")
                        
                        if is_banned:
                            print(f"   ❌ Place is BANNED")
                            return False, game_data, "Banned", root_place_id
                        
                        if is_under_review:
                            print(f"   ❌ Place is UNDER REVIEW")
                            return False, game_data, "Under Review", root_place_id
                else:
                    print(f"   ⚠️ Could not fetch place details (status {details_response.status})")
                    # If we can't check ban status, assume it's okay
            
            # If we got here: game exists, not banned, not under review
            # That's all we need - it's available!
            playing_count = game_data.get('playing', 0)
            print(f"   ✅ Game is AVAILABLE ({playing_count} players)")
            return True, game_data, "Available", root_place_id
            
    except Exception as e:
        print(f"   ❌ Exception checking game {game_id}: {e}")
        import traceback
        traceback.print_exc()
        return False, None, f"Error: {str(e)}", None

async def find_available_game(game_ids):
    """Find the first available game from the list"""
    print(f"\n{'='*60}")
    print(f"🔍 Searching through {len(game_ids)} games for available one...")
    print(f"{'='*60}")
    
    async with aiohttp.ClientSession() as session:
        for i, game_id in enumerate(game_ids, 1):
            print(f"\n[{i}/{len(game_ids)}] Checking game {game_id}...")
            is_available, game_data, reason, place_id = await check_game_available(session, game_id)
            
            print(f"\n📊 Result for {game_id}:")
            print(f"   Status: {reason}")
            print(f"   Available: {is_available}")
            
            if is_available and game_data:
                print(f"\n✅ FOUND AVAILABLE GAME!")
                print(f"   Name: {game_data['name']}")
                print(f"   Place ID: {place_id or game_data.get('rootPlaceId')}")
                print(f"{'='*60}\n")
                return game_id, game_data, place_id
            
            await asyncio.sleep(0.5)  # Rate limiting
    
    print(f"\n❌ NO AVAILABLE GAMES FOUND IN LIST")
    print(f"{'='*60}\n")
    return None, None, None

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
@app_commands.describe(place_id="The Roblox Place ID from the game URL (e.g., 18687417158)")
@app_commands.checks.has_permissions(administrator=True)
async def addgame(interaction: discord.Interaction, place_id: int):
    print(f"➕ /addgame {place_id} called by {interaction.user}")
    
    if place_id not in GAME_IDS:
        GAME_IDS.append(place_id)
        await interaction.response.send_message(
            f"✅ Added game `{place_id}` to the monitoring list!\n"
            f"📊 Now monitoring {len(GAME_IDS)} game(s).",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(f"⚠️ Game `{place_id}` is already in the list!", ephemeral=True)

@bot.tree.command(name="removegame", description="Remove a game from the monitoring list (Admin only)")
@app_commands.describe(place_id="The Roblox Place ID to remove")
@app_commands.checks.has_permissions(administrator=True)
async def removegame(interaction: discord.Interaction, place_id: int):
    print(f"➖ /removegame {place_id} called by {interaction.user}")
    
    if place_id in GAME_IDS:
        GAME_IDS.remove(place_id)
        await interaction.response.send_message(
            f"✅ Removed game `{place_id}` from the monitoring list!\n"
            f"📊 Now monitoring {len(GAME_IDS)} game(s).",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(f"⚠️ Game `{place_id}` is not in the list!", ephemeral=True)

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
    
    print("\n" + "="*50)
    print(f"🔄 Auto-check triggered at {discord.utils.utcnow()}")
    print("="*50)
    
    if CHANNEL_ID is None:
        print("⚠️ No channel set, skipping check")
        return
    
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"❌ Channel {CHANNEL_ID} not found!")
        return
    
    print(f"📍 Checking games for channel: #{channel.name} ({CHANNEL_ID})")
    
    game_id, game_data, place_id = await find_available_game(GAME_IDS)
    
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
            
            # Use the place_id returned from check_game_available
            root_place_id = place_id or game_data.get('rootPlaceId', game_id)
            
            embed.add_field(name="Place ID", value=f"`{root_place_id}`", inline=True)
            embed.add_field(name="Playing", value=f"{game_data.get('playing', 0):,}", inline=True)
            embed.add_field(name="Visits", value=f"{game_data.get('visits', 0):,}", inline=True)
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
            
            embed.set_footer(text="🔄 Auto-updates every 2 minutes")
            
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
    
    print("="*50 + "\n")

@bot.event
async def on_ready():
    print('\n' + '='*50)
    print(f'✅ {bot.user} is now running!')
    print(f'📊 Bot is in {len(bot.guilds)} guilds')
    print('='*50 + '\n')
    
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
    print("💡 Use /destroy to stop the bot and delete the message")
    print("💡 Use /addgame with Place IDs from game URLs!\n")

# Get token from environment variable
TOKEN = os.getenv('DISCORD_TOKEN')
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ ERROR: DISCORD_TOKEN not found in environment variables!")
