import discord
import aiohttp
import asyncio
import os
from discord import ui
import re
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

ROBLOX_GROUP_ID = 34590562
REQUIRED_ROLE_ID = 1259103468707250213
ROBLOX_COOKIE = os.getenv('ROBLOX_COOKIE')

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

# Function to get Roblox user ID from username
async def get_roblox_user_id(session, username):
    """Get Roblox user ID from username"""
    try:
        url = "https://users.roblox.com/v1/usernames/users"
        payload = {
            "usernames": [username],
            "excludeBannedUsers": False
        }
        
        async with session.post(url, json=payload) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('data') and len(data['data']) > 0:
                    return data['data'][0].get('id')
    except Exception as e:
        print(f"Error getting user ID for {username}: {e}")
    
    return None

# Function to get CSRF token
async def get_csrf_token(session):
    """Get CSRF token from Roblox"""
    try:
        headers = {
            'Cookie': f'.ROBLOSECURITY={ROBLOX_COOKIE}'
        }
        
        # Make a POST request to any endpoint to get CSRF token
        async with session.post(
            f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/users",
            headers=headers
        ) as response:
            return response.headers.get('x-csrf-token')
    except Exception as e:
        print(f"Error getting CSRF token: {e}")
    
    return None

# Function to get all members of a specific role
async def get_role_members(session, role_id, cursor=None):
    """Get members of a specific role in the group"""
    try:
        url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/roles/{role_id}/users"
        params = {}
        if cursor:
            params['cursor'] = cursor
        
        headers = {
            'Cookie': f'.ROBLOSECURITY={ROBLOX_COOKIE}'
        }
        
        async with session.get(url, headers=headers, params=params) as response:
            if response.status == 200:
                return await response.json()
            else:
                print(f"Failed to get role members: {response.status}")
                return None
    except Exception as e:
        print(f"Error getting role members: {e}")
        return None

# Function to get all group roles
async def get_group_roles(session):
    """Get all roles in the group"""
    try:
        url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/roles"
        headers = {
            'Cookie': f'.ROBLOSECURITY={ROBLOX_COOKIE}'
        }
        
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('roles', [])
            else:
                print(f"Failed to get group roles: {response.status}")
                return []
    except Exception as e:
        print(f"Error getting group roles: {e}")
        return []

# Function to kick a user from the group
async def kick_user_from_group(session, user_id, csrf_token):
    """Kick a specific user from the group"""
    try:
        url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/users/{user_id}"
        headers = {
            'Cookie': f'.ROBLOSECURITY={ROBLOX_COOKIE}',
            'x-csrf-token': csrf_token
        }
        
        async with session.delete(url, headers=headers) as response:
            if response.status == 200:
                return True, "Success"
            else:
                text = await response.text()
                return False, f"Status {response.status}: {text}"
    except Exception as e:
        return False, f"Error: {str(e)}"

# Function to get group join requests
async def get_group_join_requests(session):
    """Get all pending join requests for the group"""
    try:
        url = f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/join-requests"
        headers = {
            'Cookie': f'.ROBLOSECURITY={ROBLOX_COOKIE}'
        }
        
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('data', [])
            else:
                print(f"Failed to get join requests: {response.status}")
                text = await response.text()
                print(f"Response: {text}")
    except Exception as e:
        print(f"Error getting join requests: {e}")
        import traceback
        traceback.print_exc()
    
    return []

# Function to accept a specific join request
async def accept_join_request_by_id(session, user_id):
    """Accept a join request by user ID"""
    try:
        # First, get CSRF token
        csrf_token = None
        headers = {
            'Cookie': f'.ROBLOSECURITY={ROBLOX_COOKIE}'
        }
        
        async with session.post(f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/join-requests/users/{user_id}", headers=headers) as response:
            csrf_token = response.headers.get('x-csrf-token')
        
        if not csrf_token:
            return False, "Failed to get CSRF token"
        
        # Now accept with CSRF token
        headers['x-csrf-token'] = csrf_token
        
        async with session.post(f"https://groups.roblox.com/v1/groups/{ROBLOX_GROUP_ID}/join-requests/users/{user_id}", headers=headers) as response:
            if response.status == 200:
                return True, "Successfully accepted"
            else:
                text = await response.text()
                print(f"Failed to accept request: {response.status} - {text}")
                return False, f"API Error: {response.status}"
                
    except Exception as e:
        print(f"Error accepting join request: {e}")
        import traceback
        traceback.print_exc()
        return False, f"Error: {str(e)}"

# Main function to accept group join request
async def accept_group_join_request(username):
    """
    Try to accept a group join request for the given username.
    Returns: (success: bool, message: str, user_id: int or None)
    """
    if not ROBLOX_COOKIE:
        return False, "❌ Roblox cookie not configured!", None
    
    async with aiohttp.ClientSession() as session:
        # Step 1: Get user ID from username
        print(f"🔍 Looking up user ID for: {username}")
        user_id = await get_roblox_user_id(session, username)
        
        if not user_id:
            return False, f"❌ Could not find Roblox user: {username}", None
        
        print(f"✅ Found user ID: {user_id}")
        
        # Step 2: Get all join requests
        print(f"📋 Fetching join requests for group {ROBLOX_GROUP_ID}...")
        join_requests = await get_group_join_requests(session)
        
        if not join_requests:
            return False, "❌ No pending join requests found or failed to fetch requests", user_id
        
        print(f"📊 Found {len(join_requests)} pending request(s)")
        
        # Step 3: Check if this user has a pending request
        request_found = False
        for request in join_requests:
            if request.get('requester', {}).get('userId') == user_id:
                request_found = True
                print(f"✅ Found join request for {username} (ID: {user_id})")
                break
        
        if not request_found:
            return False, f"❌ No pending join request found for {username}. Make sure you've requested to join the group first!", user_id
        
        # Step 4: Accept the request
        print(f"⏳ Accepting join request for {username}...")
        success, message = await accept_join_request_by_id(session, user_id)
        
        if success:
            return True, f"✅ Successfully accepted {username} into the group!", user_id
        else:
            return False, f"❌ Failed to accept request: {message}", user_id

# NEW COMMAND: Kick all members of a role
@bot.tree.command(name="kickrole", description="Remove all members from a specific group role (Admin only)")
@app_commands.describe(role_name="The exact name of the role (e.g., 'Member', 'VIP')")
@app_commands.checks.has_permissions(administrator=True)
async def kickrole(interaction: discord.Interaction, role_name: str):
    """Remove all members from a specific Roblox group role"""
    
    if not ROBLOX_COOKIE:
        await interaction.response.send_message(
            "❌ Roblox cookie not configured!",
            ephemeral=True
        )
        return
    
    await interaction.response.defer(ephemeral=True)
    
    print(f"🗑️ /kickrole called by {interaction.user} - Role: {role_name}")
    
    async with aiohttp.ClientSession() as session:
        # Step 1: Get all group roles
        print(f"📋 Fetching group roles...")
        roles = await get_group_roles(session)
        
        if not roles:
            await interaction.followup.send(
                "❌ Failed to fetch group roles!",
                ephemeral=True
            )
            return
        
        # Step 2: Find the role by name
        target_role = None
        for role in roles:
            if role.get('name', '').lower() == role_name.lower():
                target_role = role
                break
        
        if not target_role:
            # Show available roles
            available_roles = "\n".join([f"• {role.get('name')} (ID: {role.get('id')})" for role in roles])
            await interaction.followup.send(
                f"❌ Role `{role_name}` not found!\n\n**Available roles:**\n{available_roles}",
                ephemeral=True
            )
            return
        
        role_id = target_role.get('id')
        print(f"✅ Found role: {target_role.get('name')} (ID: {role_id})")
        
        # Step 3: Get CSRF token
        print(f"🔑 Getting CSRF token...")
        csrf_token = await get_csrf_token(session)
        
        if not csrf_token:
            await interaction.followup.send(
                "❌ Failed to get CSRF token!",
                ephemeral=True
            )
            return
        
        # Step 4: Get all members of this role (with pagination)
        print(f"👥 Fetching members of role {role_name}...")
        all_members = []
        cursor = None
        
        while True:
            result = await get_role_members(session, role_id, cursor)
            
            if not result:
                break
            
            members = result.get('data', [])
            all_members.extend(members)
            
            cursor = result.get('nextPageCursor')
            if not cursor:
                break
            
            await asyncio.sleep(0.5)  # Rate limiting
        
        if not all_members:
            await interaction.followup.send(
                f"ℹ️ No members found in role `{role_name}`!",
                ephemeral=True
            )
            return
        
        total_members = len(all_members)
        print(f"📊 Found {total_members} member(s) in role {role_name}")
        
        # Step 5: Send confirmation
        embed = discord.Embed(
            title="⚠️ Confirm Bulk Kick",
            description=f"Are you sure you want to kick **{total_members}** member(s) from the `{role_name}` role?",
            color=discord.Color.orange()
        )
        embed.add_field(name="Group ID", value=f"`{ROBLOX_GROUP_ID}`", inline=True)
        embed.add_field(name="Role", value=f"`{role_name}`", inline=True)
        embed.add_field(name="Members to Kick", value=f"`{total_members}`", inline=True)
        embed.set_footer(text="This action cannot be undone!")
        
        await interaction.followup.send(
            embed=embed,
            ephemeral=True
        )
        
        # Ask for confirmation
        confirmation = await interaction.followup.send(
            "⚠️ Type `CONFIRM` to proceed with kicking all members:",
            ephemeral=True,
            wait=True
        )
        
        def check(m):
            return m.author == interaction.user and m.channel == interaction.channel
        
        try:
            msg = await bot.wait_for('message', timeout=30.0, check=check)
            
            if msg.content.upper() != 'CONFIRM':
                await interaction.followup.send(
                    "❌ Operation cancelled.",
                    ephemeral=True
                )
                return
            
            # Delete the confirmation message
            try:
                await msg.delete()
            except:
                pass
            
        except asyncio.TimeoutError:
            await interaction.followup.send(
                "❌ Confirmation timed out. Operation cancelled.",
                ephemeral=True
            )
            return
        
        # Step 6: Kick all members
        kicked = 0
        failed = 0
        
        status_embed = discord.Embed(
            title="🔄 Kicking Members...",
            description=f"Progress: 0/{total_members}",
            color=discord.Color.blue()
        )
        status_msg = await interaction.followup.send(embed=status_embed, ephemeral=True)
        
        for i, member in enumerate(all_members, 1):
            user_id = member.get('userId')
            username = member.get('username', 'Unknown')
            
            print(f"[{i}/{total_members}] Kicking {username} (ID: {user_id})...")
            
            success, message = await kick_user_from_group(session, user_id, csrf_token)
            
            if success:
                kicked += 1
                print(f"   ✅ Kicked {username}")
            else:
                failed += 1
                print(f"   ❌ Failed to kick {username}: {message}")
            
            # Update status every 5 members
            if i % 5 == 0 or i == total_members:
                status_embed.description = f"Progress: {i}/{total_members}\n✅ Kicked: {kicked}\n❌ Failed: {failed}"
                try:
                    await status_msg.edit(embed=status_embed)
                except:
                    pass
            
            await asyncio.sleep(0.5)  # Rate limiting
        
        # Final report
        final_embed = discord.Embed(
            title="✅ Bulk Kick Complete",
            color=discord.Color.green() if failed == 0 else discord.Color.orange()
        )
        final_embed.add_field(name="Role", value=f"`{role_name}`", inline=True)
        final_embed.add_field(name="Total Members", value=f"`{total_members}`", inline=True)
        final_embed.add_field(name="Successfully Kicked", value=f"`{kicked}`", inline=True)
        final_embed.add_field(name="Failed", value=f"`{failed}`", inline=True)
        
        await interaction.followup.send(embed=final_embed, ephemeral=True)
        print(f"✅ Bulk kick complete: {kicked} kicked, {failed} failed")

@bot.tree.command(name="requestaccess", description="Request access to the Roblox group")
@app_commands.describe(roblox_username="Your exact Roblox username")
async def requestaccess(interaction: discord.Interaction, roblox_username: str):
    await interaction.response.defer(ephemeral=True)
    
    username = roblox_username.strip()
    
    print(f"📝 Join request from {interaction.user}: {username}")
    
    # Check if user has the required role
    if REQUIRED_ROLE_ID is not None:
        required_role = interaction.guild.get_role(REQUIRED_ROLE_ID)
        
        if required_role is None:
            await interaction.followup.send(
                "❌ Configuration error: Required role not found!",
                ephemeral=True
            )
            print(f"❌ Required role {REQUIRED_ROLE_ID} not found in guild")
            return
        
        if required_role not in interaction.user.roles:
            embed = discord.Embed(
                title="❌ Access Denied",
                description=f"You need the **{required_role.name}** role to request group access!",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(
                name="Required Role",
                value=required_role.mention,
                inline=False
            )
            embed.set_footer(text="Verify first to get the required role")
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            print(f"❌ {interaction.user} denied - missing role {required_role.name}")
            return
    
    # Try to accept the join request
    success, message, user_id = await accept_group_join_request(username)
    
    if success:
        # Success embed for the interaction response
        embed = discord.Embed(
            title="✅ Request Accepted!",
            description=f"Successfully accepted **{username}** into the Roblox group!",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Roblox Username", value=username, inline=True)
        embed.add_field(name="User ID", value=str(user_id), inline=True)
        embed.add_field(name="Discord User", value=interaction.user.mention, inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        print(f"✅ Accepted {username} into group")
        
        # Send success DM to the user
        try:
            dm_embed = discord.Embed(
                title="✅ Join Request Accepted!",
                description=f"Your request to join the Roblox group has been successfully accepted!",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            dm_embed.add_field(name="Roblox Username", value=username, inline=True)
            dm_embed.add_field(name="Group ID", value=f"`{ROBLOX_GROUP_ID}`", inline=True)
            dm_embed.add_field(
                name="🎮 View Group", 
                value=f"[Click Here](https://www.roblox.com/groups/{ROBLOX_GROUP_ID})",
                inline=False
            )
            dm_embed.set_footer(text="Welcome to the group!")
            
            await interaction.user.send(embed=dm_embed)
            print(f"📨 Sent success DM to {interaction.user}")
        except discord.Forbidden:
            print(f"⚠️ Could not send DM to {interaction.user} (DMs disabled)")
        except Exception as e:
            print(f"❌ Error sending DM: {e}")
            
    else:
        # Failure embed for the interaction response
        embed = discord.Embed(
            title="❌ Request Not Found",
            description=message,
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Roblox Username", value=username, inline=True)
        embed.add_field(name="What to do", value="Make sure you've sent a join request to the group first!", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
        print(f"❌ Failed to accept {username}: {message}")
        
        # Send failure DM to the user
        try:
            dm_embed = discord.Embed(
                title="❌ Join Request Not Found",
                description="Couldn't find any requests with that username. Did you send the request?",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
            dm_embed.add_field(name="Roblox Username", value=username, inline=True)
            dm_embed.add_field(
                name="📝 Steps to Join",
                value=(
                    f"1. Go to the [Roblox Group](https://www.roblox.com/groups/{ROBLOX_GROUP_ID})\n"
                    "2. Click the **'Join Group'** button\n"
                    "3. Wait a moment, then use `/requestaccess` again with your username"
                ),
                inline=False
            )
            dm_embed.set_footer(text="Make sure to request on Roblox first!")
            
            await interaction.user.send(embed=dm_embed)
            print(f"📨 Sent failure DM to {interaction.user}")
        except discord.Forbidden:
            print(f"⚠️ Could not send DM to {interaction.user} (DMs disabled)")
        except Exception as e:
            print(f"❌ Error sending DM: {e}")

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
@kickrole.error
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
    print("💡 Use /kickrole to remove all members from a specific role!\n")

# Get token from environment variable
TOKEN = os.getenv('DISCORD_TOKEN')
if TOKEN:
    bot.run(TOKEN)
else:
    print("❌ ERROR: DISCORD_TOKEN not found in environment variables!")
