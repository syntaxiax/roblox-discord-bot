import discord
import aiohttp
import asyncio
import os
from discord import ui
import re
from discord.ext import commands, tasks
from discord import app_commands
from aiohttp import web

# Discord bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ============================================
# CONFIGURATION - SET THESE VALUES
# ============================================
NSFW_VERIFY_CHANNEL_ID = 1480620694051225640             # Set this to your channel ID (e.g., 1234567890)
NSFW_VERIFY_ROLE_ID = 1480625267784290546                # Set this to your role ID (e.g., 1234567890)

ROBLOX_GROUP_ID = 34590562
REQUIRED_ROLE_ID = 1259103468707250213
ROBLOX_COOKIE = os.getenv('ROBLOX_COOKIE')

# Health check flag
bot_ready = False

# ============================================
# KOYEB HEALTH CHECK SERVER
# ============================================

async def health_check_handler(request):
    """Health check endpoint for Koyeb"""
    if bot_ready:
        return web.json_response({
            "status": "healthy",
            "bot": bot.user.name if bot.user else "connecting"
        }, status=200)
    else:
        return web.json_response({
            "status": "starting"
        }, status=503)

async def start_health_server():
    """Start the health check HTTP server"""
    app = web.Application()
    app.router.add_get('/health', health_check_handler)
    app.router.add_get('/', health_check_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv('PORT', 8000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    print(f"✅ Health check server running on port {port}")
    return runner

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

# ============================================
# SLASH COMMANDS
# ============================================

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

# NSFW Verification Command
@bot.tree.command(name="nsfw-verify", description="Submit an image for NSFW verification")
@app_commands.describe(image="The image to submit for verification")
async def nsfw_verify(interaction: discord.Interaction, image: discord.Attachment):
    """Submit an image for NSFW verification"""
    
    if NSFW_VERIFY_CHANNEL_ID == 0:
        await interaction.response.send_message(
            "❌ NSFW verification channel is not configured!",
            ephemeral=True
        )
        print(f"❌ NSFW_VERIFY_CHANNEL_ID not set (still 0)")
        return
    
    if NSFW_VERIFY_ROLE_ID == 0:
        await interaction.response.send_message(
            "❌ NSFW verification role is not configured!",
            ephemeral=True
        )
        print(f"❌ NSFW_VERIFY_ROLE_ID not set (still 0)")
        return
    
    # Verify it's an image
    if not image.content_type or not image.content_type.startswith('image/'):
        await interaction.response.send_message(
            "❌ Please attach an image file!",
            ephemeral=True
        )
        return
    
    await interaction.response.defer(ephemeral=True)
    
    print(f"📸 NSFW verification submitted by {interaction.user} ({interaction.user.id})")
    
    try:
        # Get the verification channel
        verify_channel = bot.get_channel(NSFW_VERIFY_CHANNEL_ID)
        
        if not verify_channel:
            await interaction.followup.send(
                "❌ Verification channel not found!",
                ephemeral=True
            )
            print(f"❌ Channel {NSFW_VERIFY_CHANNEL_ID} not found")
            return
        
        # Get the role to ping
        guild = verify_channel.guild
        verify_role = guild.get_role(NSFW_VERIFY_ROLE_ID)
        
        if not verify_role:
            await interaction.followup.send(
                "❌ Verification role not found!",
                ephemeral=True
            )
            print(f"❌ Role {NSFW_VERIFY_ROLE_ID} not found")
            return
        
        # Create the embed
        embed = discord.Embed(
            title=f"NSFW verification submit for {interaction.user.name}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="User ID", value=f"`{interaction.user.id}`", inline=True)
        embed.add_field(name="User Mention", value=interaction.user.mention, inline=True)
        embed.add_field(name="Image Name", value=image.filename, inline=False)
        embed.set_footer(text="Image attached below")
        
        # Download and send the image with the embed
        image_data = await image.read()
        
        # Create a file object to send
        file = discord.File(
            fp=__import__('io').BytesIO(image_data),
            filename=image.filename
        )
        
        # Send to verification channel with role mention
        mention_text = f"{verify_role.mention} New verification submission!"
        msg = await verify_channel.send(mention_text, embed=embed, file=file)
        
        # Send confirmation to user
        await interaction.followup.send(
            f"✅ Image submitted for verification!\n"
            ephemeral=True
        )
        
        print(f"✅ NSFW verification submitted - Message ID: {msg.id}")
        print(f"✅ Pinged role: {verify_role.name} (ID: {NSFW_VERIFY_ROLE_ID})")
        
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ I don't have permission to send messages in the verification channel!",
            ephemeral=True
        )
        print(f"❌ Missing permissions for channel {NSFW_VERIFY_CHANNEL_ID}")
    except Exception as e:
        await interaction.followup.send(
            f"❌ Error submitting verification: {str(e)}",
            ephemeral=True
        )
        print(f"❌ Error in nsfw_verify: {e}")
        import traceback
        traceback.print_exc()

# Error handlers for slash commands
@kickrole.error
async def permission_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You need Administrator permission to use this command!", ephemeral=True)

# ============================================
# BOT EVENTS
# ============================================

@bot.event
async def on_ready():
    global bot_ready
    
    print('\n' + '='*50)
    print(f'✅ {bot.user} is now running!')
    print(f'📊 Bot is in {len(bot.guilds)} guilds')
    print('='*50 + '\n')
    
    bot_ready = True
    
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
    
    print("\n📋 Configuration:")
    print(f"   NSFW Verification Channel: {NSFW_VERIFY_CHANNEL_ID}")
    print(f"   NSFW Verification Role: {NSFW_VERIFY_ROLE_ID}")
    print(f"   Roblox Group ID: {ROBLOX_GROUP_ID}")
    print("\n💡 Available Commands:")
    print("   - /nsfw-verify: Submit image for verification")
    print("   - /requestaccess: Request to join Roblox group")
    print("   - /kickrole: Bulk kick members from a role\n")

async def main():
    """Start both the Discord bot and health check server"""
    
    # Start the health check server
    health_runner = await start_health_server()
    
    # Start the Discord bot
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("❌ ERROR: DISCORD_TOKEN not found in environment variables!")
        return
    
    try:
        await bot.start(token)
    except Exception as e:
        print(f"❌ Bot error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await health_runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())

