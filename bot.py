import discord
import aiohttp
import asyncio
import os
from discord.ext import commands, tasks

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

# Store the message ID so we can edit it
status_message = None

async def check_game_status(session, game_id):
    """Check if a Roblox game is available/not banned"""
    try:
        url = f"https://games.roblox.com/v1/games?universeIds={game_id}"
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('data') and len(data['data']) > 0:
                    return True, data['data'][0]
            return False, None
    except Exception as e:
        print(f"Error checking game {game_id}: {e}")
        return False, None

async def find_available_game(game_ids):
    """Find the first available game from the list"""
    async with aiohttp.ClientSession() as session:
        for game_id in game_ids:
            is_available, game_data = await check_game_status(session, game_id)
            if is_available:
                return game_id, game_data
            await asyncio.sleep(0.5)
    return None, None

@tasks.loop(minutes=5)  # Check every 5 minutes
async def auto_check_games():
    """Automatically check games and update the channel message"""
    global status_message
    
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"Channel {CHANNEL_ID} not found!")
        return
    
    game_id, game_data = await find_available_game(GAME_IDS)
    
    if game_id and game_data:
        embed = discord.Embed(
            title="🎮 Current Available Game",
            description=f"**{game_data['name']}**",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Game ID", value=game_id, inline=True)
        embed.add_field(name="Creator", value=game_data.get('creator', {}).get('name', 'Unknown'), inline=True)
        embed.add_field(name="Play Now", value=f"[Click Here](https://www.roblox.com/games/{game_id})", inline=False)
        embed.set_footer(text="Last updated")
        
        if status_message:
            try:
                await status_message.edit(embed=embed)
            except discord.NotFound:
                status_message = await channel.send(embed=embed)
        else:
            status_message = await channel.send(embed=embed)
    else:
        embed = discord.Embed(
            title="⏳ No Available Games",
            description="All games in the list are currently unavailable.",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Last checked")
        
        if status_message:
            try:
                await status_message.edit(embed=embed)
            except discord.NotFound:
                status_message = await channel.send(embed=embed)
        else:
            status_message = await channel.send(embed=embed)

@bot.event
async def on_ready():
    print(f'{bot.user} is now running!')
    print(f'Bot is in {len(bot.guilds)} guilds')
    
    # Start the auto-check loop
    if not auto_check_games.is_running():
        auto_check_games.start()
    
    # Do an immediate check on startup
    await auto_check_games()

@bot.command(name='checkgame')
async def check_game(ctx):
    """Manually check for an available game"""
    message = await ctx.send("🔍 Checking for available games...")
    
    game_id, game_data = await find_available_game(GAME_IDS)
    
    if game_id and game_data:
        embed = discord.Embed(
            title="✅ Available Game Found!",
            description=f"**{game_data['name']}**",
            color=discord.Color.green()
        )
        embed.add_field(name="Game ID", value=game_id, inline=True)
        embed.add_field(name="Creator", value=game_data.get('creator', {}).get('name', 'Unknown'), inline=True)
        embed.add_field(name="Link", value=f"https://www.roblox.com/games/{game_id}", inline=False)
        
        await message.edit(content=None, embed=embed)
    else:
        await message.edit(content="❌ No available games found in the list.")

@bot.command(name='setchannel')
@commands.has_permissions(administrator=True)
async def set_channel(ctx):
    """Set the current channel for auto-updates"""
    global CHANNEL_ID
    CHANNEL_ID = ctx.channel.id
    await ctx.send(f"✅ Auto-update channel set to {ctx.channel.mention}")

# Get token from environment variable
TOKEN = os.getenv('DISCORD_TOKEN')
if TOKEN:
    bot.run(TOKEN)
else:
    print("ERROR: DISCORD_TOKEN not found in environment variables!")
