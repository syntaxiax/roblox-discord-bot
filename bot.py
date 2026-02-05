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
CHANNEL_ID = 1259103469441388552  # Replace with your channel ID
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
            # (might just be empty at the moment)
            return True, game_data, "Available"
            
    except Exception as e:
        print(f"Error checking game {universe_id}: {e}")
        return False, None, f"Error: {str(e)}"

async def find_available_game(game_ids):
    """Find the first available game from the list"""
    async with aiohttp.ClientSession() as session:
        for game_id in game_ids:
            is_available, game_data, reason = await check_game_available(session, game_id)
            print(f"Game {game_id}: {reason}")
            
            if is_available and game_data:
                return game_id, game_data
            
            await asyncio.sleep(0.5)  # Rate limiting
    
    return None, None

@tasks.loop(minutes=2)  # Check every 2 minutes
async def auto_check_games():
    """Automatically check games and update the channel message"""
    global status_message, current_game_id
    
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"Channel {CHANNEL_ID} not found!")
        return
    
    game_id, game_data = await find_available_game(GAME_IDS)
    
    # Only update message if the game changed or if no message exists
    if game_id and game_data:
        # Check if this is a different game than what we're currently showing
        if current_game_id != game_id:
            current_game_id = game_id
            
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
                embed.add_field(
                    name="Description", 
                    value=game_data['description'][:100] + "..." if len(game_data.get('description', '')) > 100 else game_data.get('description', ''),
                    inline=False
                )
            
            embed.set_footer(text="✅ Game switched • Last checked")
            
            if status_message:
                try:
                    await status_message.edit(embed=embed)
                    print(f"✅ Updated to new game: {game_data['name']}")
                except discord.NotFound:
                    status_message = await channel.send(embed=embed)
            else:
                status_message = await channel.send(embed=embed)
        else:
            # Same game still available, just update timestamp
            print(f"ℹ️ Same game still available: {game_data['name']}")
    else:
        # No available games found
        if current_game_id is not None:  # Only update if we had a game before
            current_game_id = None
            
            embed = discord.Embed(
                title="⏳ No Available Games",
                description="All games in the list are currently unavailable, banned, or under review.",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="Checking for available games...")
            
            if status_message:
                try:
                    await status_message.edit(embed=embed)
                    print("❌ No games available")
                except discord.NotFound:
                    status_message = await channel.send(embed=embed)
            else:
                status_message = await channel.send(embed=embed)

@bot.event
async def on_ready():
    print(f'✅ {bot.user} is now running!')
    print(f'📊 Bot is in {len(bot.guilds)} guilds')
    print(f'🎯 Monitoring channel ID: {CHANNEL_ID}')
    print(f'🎮 Watching {len(GAME_IDS)} games')
    
    # Sync slash commands
try:
    # Clear old commands first
    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()
    
    synced = await bot.tree.sync()
    print(f"✅ Synced {len(synced)} slash command(s)")
except Exception as e:
    print(f"❌ Failed to sync commands: {e}")
    
    # Start the auto-check loop
    if not auto_check_games.is_running():
        auto_check_games.start()
    
    # Do an immediate check on startup
    await auto_check_games()

# SLASH COMMANDS

@bot.tree.command(name="checkgame", description="Manually check for available games right now")
async def checkgame(interaction: discord.Interaction):
    await interaction.response.send_message("🔍 Checking games now...", ephemeral=True)
    await auto_check_games()

@bot.tree.command(name="forcenext", description="Force switch to the next available game (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def forcenext(interaction: discord.Interaction):
    global current_game_id
    current_game_id = None  # Reset current game
    await interaction.response.send_message("🔄 Forcing check for next game...", ephemeral=True)
    await auto_check_games()

@bot.tree.command(name="addgame", description="Add a game to the monitoring list (Admin only)")
@app_commands.describe(universe_id="The Roblox Universe ID of the game to add")
@app_commands.checks.has_permissions(administrator=True)
async def addgame(interaction: discord.Interaction, universe_id: int):
    if universe_id not in GAME_IDS:
        GAME_IDS.append(universe_id)
        await interaction.response.send_message(f"✅ Added game `{universe_id}` to the monitoring list!", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ Game `{universe_id}` is already in the list!", ephemeral=True)

@bot.tree.command(name="removegame", description="Remove a game from the monitoring list (Admin only)")
@app_commands.describe(universe_id="The Roblox Universe ID of the game to remove")
@app_commands.checks.has_permissions(administrator=True)
async def removegame(interaction: discord.Interaction, universe_id: int):
    if universe_id in GAME_IDS:
        GAME_IDS.remove(universe_id)
        await interaction.response.send_message(f"✅ Removed game `{universe_id}` from the monitoring list!", ephemeral=True)
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
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ No games in the monitoring list!", ephemeral=True)

# Error handlers for slash commands
@forcenext.error
@addgame.error
@removegame.error
async def permission_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You need Administrator permission to use this command!", ephemeral=True)

# Get token from environment variable
TOKEN = os.getenv('DISCORD_TOKEN')
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ ERROR: DISCORD_TOKEN not found in environment variables!")

