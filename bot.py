import discord
import aiohttp
import asyncio
import os
from discord.ext import commands

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# List of Roblox game IDs to check
GAME_IDS = [
    123456789,  # Replace with actual game IDs
    987654321,
    111222333,
]

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

@bot.command(name='checkgame')
async def check_game(ctx):
    """Check for an available game and update the message"""
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

@bot.event
async def on_ready():
    print(f'{bot.user} is now running!')
    print(f'Bot is in {len(bot.guilds)} guilds')

# Get token from environment variable
TOKEN = os.getenv('DISCORD_TOKEN')
if TOKEN:
    bot.run(TOKEN)
else:
    print("ERROR: DISCORD_TOKEN not found in environment variables!")