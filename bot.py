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
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# ============================================
# CONFIGURATION - SET THESE VALUES
# ============================================
NSFW_VERIFY_CHANNEL_ID = 1480620694051225640             # Set this to your channel ID (e.g., 1234567890)
NSFW_VERIFY_ROLE_ID = 1480192134085738496                # Set this to your role ID (e.g., 1234567890)

# Member Verification Settings
MEMBER_VERIFY_CHANNEL_ID = 1480637006798131330           # Channel where verification submissions are sent
PENDING_ROLE_ID = 1259103468707250207                    # Role given to new members (to be removed on verify)
VERIFIED_ROLE_ID = 1259103468707250213                   # Role given after verification (to be added)

# Check Settings - NEW
CHECK_ROLE_ID = 1482499303527419984                      # Custom role for members under check (create this first!)

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
    app.router.add_head('/health', health_check_handler)
    app.router.add_head('/', health_check_handler)  
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv('PORT', 8000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    print(f"✅ Health check server running on port {port}")
    return runner

# ============================================
# ROBLOX API FUNCTIONS
# ============================================

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
        
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
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

# Member Verification Questions
VERIFY_QUESTIONS = [
    "How old are you?",
    "Are you in any nomgames or vore community's? Provide us with their name if you do.",
    "When and how did you discover a vore fetish or like this fetish?",
    "How did you find us? We would like to know.",
    "If you have any friends to prove you're not a Vhunter, please state their name. Unless you don't have any.",
    "Do you have any vore artist you know? Provide a link to their profile, underrated or less popular artist are fine eitherway.",
    "Send us your roblox profile link.",
    "Any vore youtuber you know?"
]

def is_valid_age(answer):
    """Validate age answer - must be a number"""
    try:
        age = int(answer)
        return True, answer
    except ValueError:
        return False, None

def is_valid_link(answer):
    """Validate that answer contains a link or is a valid 'none' response"""
    answer_lower = answer.lower()
    
    # Accept "none" type responses
    skip_words = ["none", "don't have", "dont have", "don't know", "dont know", "idk", "nope", "nah", "no"]
    if any(word in answer_lower for word in skip_words):
        return True, answer
    
    # Otherwise require a link
    return ("http://" in answer_lower or "https://" in answer_lower), answer

async def collect_member_verification(member):
    """
    Collect verification answers from a member via DMs
    Returns: (answers_dict, success: bool)
    """
    try:
        # Send intro message
        intro_embed = discord.Embed(
            title="🔐 Server Verification",
            description="Welcome! Please answer the following questions to verify your membership. (If the bot DMs you a few times, we are sorry, it's still in development)",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        intro_embed.add_field(
            name="Instructions",
            value="Answer each question in order. Some questions require links.",
            inline=False
        )
        
        await member.send(embed=intro_embed)
        
        answers = {}
        question_index = 0
        
        while question_index < len(VERIFY_QUESTIONS):
            question = VERIFY_QUESTIONS[question_index]
            i = question_index + 1
            
            # Send question
            question_embed = discord.Embed(
                title=f"Question {i}/{len(VERIFY_QUESTIONS)}",
                description=question,
                color=discord.Color.blue(),
                timestamp=discord.utils.utcnow()
            )
            question_embed.set_footer(text="Reply in the chat to answer")
            
            await member.send(embed=question_embed)
            
            # Wait for answer
            def check(m):
                return m.author == member and isinstance(m.channel, discord.DMChannel)
            
            try:
                msg = await bot.wait_for('message', check=check, timeout=300)
                answer = msg.content.strip()
                
                # Validate specific questions
                if i == 1:  # Age question
                    valid, validated_answer = is_valid_age(answer)
                    if not valid:
                        error_embed = discord.Embed(
                            title="❌ Invalid Answer",
                            description="Please provide a valid number for your age.",
                            color=discord.Color.red()
                        )
                        await member.send(embed=error_embed)
                        continue
                    answers[f"question_{i}"] = validated_answer
                
                elif i in [6, 7, 8]:  # Questions requiring links
                    valid, validated_answer = is_valid_link(answer)
                    if not valid:
                        error_embed = discord.Embed(
                            title="❌ Invalid Answer",
                            description="Please provide a link (must contain http:// or https://) or reply with 'none' if you don't have one.",
                            color=discord.Color.red()
                        )
                        await member.send(embed=error_embed)
                        continue
                    answers[f"question_{i}"] = validated_answer
                
                else:
                    answers[f"question_{i}"] = answer
                
                # Show progress
                progress_embed = discord.Embed(
                    title="✅ Answer Recorded",
                    description=f"Progress: {i}/{len(VERIFY_QUESTIONS)}",
                    color=discord.Color.green()
                )
                await member.send(embed=progress_embed)
                
                question_index += 1
                
            except asyncio.TimeoutError:
                timeout_embed = discord.Embed(
                    title="⏱️ Timeout",
                    description="You took too long to answer. Verification cancelled.",
                    color=discord.Color.red()
                )
                await member.send(embed=timeout_embed)
                print(f"⏱️ Verification timeout for {member.name} on question {i}")
                return answers, False
            
            except Exception as e:
                print(f"❌ Error waiting for response from {member.name}: {e}")
                return answers, False
        
        # Success message
        success_embed = discord.Embed(
            title="✅ Verification Complete",
            description="Your answers have been submitted for review. The staff will review your responses and notify you of the decision.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        await member.send(embed=success_embed)
        
        return answers, True
        
    except discord.Forbidden:
        print(f"❌ Cannot send DM to {member} - DMs closed")
        return {}, False
    except Exception as e:
        print(f"❌ Error collecting verification from {member}: {e}")
        import traceback
        traceback.print_exc()
        return {}, False

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
# VERIFICATION BUTTONS VIEW
# ============================================

class VerificationView(discord.ui.View):
    def __init__(self, member, answers, member_username=None):
        super().__init__(timeout=None)
        self.member = member
        self.member_id = member.id
        self.member_username = member_username or member.name
        self.member_display_name = member.display_name
        self.answers = answers
        self.verified = None
    
    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.green)
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Accept member verification"""
        
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only administrators can approve verifications!",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            guild = interaction.guild
            member = guild.get_member(self.member_id)
            
            if not member:
                await interaction.followup.send(
                    f"⚠️ Member not found in guild (they may have left). Username was: `{self.member_username}`",
                    ephemeral=True
                )
                # Still update the message to show it was accepted
                original_embed = interaction.message.embeds[0]
                original_embed.color = discord.Color.green()
                original_embed.title = "✅ ACCEPTED"
                original_embed.description = f"Approved by {interaction.user.mention}\nUsername: `{self.member_username}`"
                await interaction.message.edit(embed=original_embed, view=None)
                return
            
            # Get roles
            pending_role = guild.get_role(PENDING_ROLE_ID)
            verified_role = guild.get_role(VERIFIED_ROLE_ID)
            
            if not pending_role or not verified_role:
                await interaction.followup.send(
                    "❌ Configuration error: Roles not found!",
                    ephemeral=True
                )
                print(f"❌ Pending role or verified role not found")
                return
            
            # Remove pending role, add verified role
            if pending_role in member.roles:
                await member.remove_roles(pending_role)
            await member.add_roles(verified_role)
            
            # Send member success message
            verify_embed = discord.Embed(
                title="✅ You have been verified!",
                description="Congratulations! Your verification has been approved. Welcome to the community!",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            
            try:
                await member.send(embed=verify_embed)
            except discord.Forbidden:
                print(f"⚠️ Could not send DM to {member} (DMs disabled)")
            
            # Update the embed to show it was accepted
            original_embed = interaction.message.embeds[0]
            original_embed.color = discord.Color.green()
            original_embed.title = "✅ ACCEPTED"
            original_embed.description = f"Approved by {interaction.user.mention}\nUsername: `{self.member_username}`"
            
            await interaction.message.edit(embed=original_embed, view=None)
            
            await interaction.followup.send(
                f"✅ {member.mention} has been verified!",
                ephemeral=True
            )
            
            print(f"✅ {self.member_username} approved by {interaction.user.name}")
            
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error approving verification: {str(e)}",
                ephemeral=True
            )
            print(f"❌ Error in accept button: {e}")
            import traceback
            traceback.print_exc()
    
    @discord.ui.button(label="❌ Deny", style=discord.ButtonStyle.red)
    async def deny_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Deny member verification"""
        
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only administrators can deny verifications!",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            guild = interaction.guild
            member = guild.get_member(self.member_id)
            
            if not member:
                await interaction.followup.send(
                    f"⚠️ Member not found in guild (they may have already left). Username was: `{self.member_username}`",
                    ephemeral=True
                )
                # Still update the message to show it was denied
                original_embed = interaction.message.embeds[0]
                original_embed.color = discord.Color.red()
                original_embed.title = "❌ DENIED"
                original_embed.description = f"Denied by {interaction.user.mention}\nUsername: `{self.member_username}`"
                await interaction.message.edit(embed=original_embed, view=None)
                return
            
            # Send rejection message to member
            reject_embed = discord.Embed(
                title="❌ Verification Failed",
                description="Your verification has been denied. You may try again next time.",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            
            try:
                await member.send(embed=reject_embed)
            except discord.Forbidden:
                print(f"⚠️ Could not send DM to {member} (DMs disabled)")
            
            # Kick the member
            await member.kick(reason="Verification denied")
            
            # Update the embed to show it was denied
            original_embed = interaction.message.embeds[0]
            original_embed.color = discord.Color.red()
            original_embed.title = "❌ DENIED"
            original_embed.description = f"Denied by {interaction.user.mention}\nUsername: `{self.member_username}`"
            
            await interaction.message.edit(embed=original_embed, view=None)
            
            await interaction.followup.send(
                f"❌ {member.mention} has been kicked due to failed verification!",
                ephemeral=True
            )
            
            print(f"❌ {self.member_username} rejected and kicked by {interaction.user.name}")
            
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error denying verification: {str(e)}",
                ephemeral=True
            )
            print(f"❌ Error in deny button: {e}")
            import traceback
            traceback.print_exc()

# ============================================
# CHECK CHANNEL VIEW - NEW
# ============================================

class CheckChannelView(discord.ui.View):
    """View for check channel with close button"""
    
    def __init__(self, member, channel):
        super().__init__(timeout=None)
        self.member = member
        self.member_id = member.id
        self.member_username = member.name
        self.channel = channel
    
    @discord.ui.button(label="🔒 Close Check", style=discord.ButtonStyle.red)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Close the check channel"""
        
        # Only moderators can close
        if not interaction.user.guild_permissions.moderate_members and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Only moderators can close checks!",
                ephemeral=True
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        
        try:
            guild = interaction.guild
            member = guild.get_member(self.member_id)
            
            # Get the check role
            check_role = guild.get_role(CHECK_ROLE_ID) if CHECK_ROLE_ID else None
            
            # Remove check role ONLY (don't add verified role)
            if member:
                if check_role and check_role in member.roles:
                    await member.remove_roles(check_role)
                    print(f"✅ Removed check role from {self.member_username}")
            
            # Calculate deletion time
            deletion_time = discord.utils.utcnow() + discord.utils.timedelta(seconds=30)
            
            # Send close message with timestamp
            close_embed = discord.Embed(
                title="✅ Check Closed",
                description=f"This check for {self.member_username} has been closed.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            close_embed.add_field(name="Closed By", value=interaction.user.mention, inline=True)
            close_embed.add_field(name="Member", value=self.member_username, inline=True)
            close_embed.add_field(
                name="⏰ Channel Deletion",
                value=f"Channel will be deleted at <t:{int(deletion_time.timestamp())}:T> (<t:{int(deletion_time.timestamp())}:R>)",
                inline=False
            )
            
            if member:
                close_embed.add_field(
                    name="Member Status",
                    value=f"❌ Removed: {check_role.mention if check_role else 'Check Role'}",
                    inline=False
                )
            
            await interaction.followup.send(embed=close_embed, ephemeral=True)
            close_msg = await self.channel.send(embed=close_embed)
            
            print(f"✅ Check closed for {self.member_username} by {interaction.user.name}")
            print(f"📅 Channel will be deleted at: {deletion_time}")
            
            # Schedule channel deletion after 30 seconds
            async def delete_channel_after_delay():
                print(f"⏳ Waiting 30 seconds before deleting channel: {self.channel.name}")
                await asyncio.sleep(30)  # Wait 30 seconds
                try:
                    print(f"🗑️ Attempting to delete channel: {self.channel.name} (ID: {self.channel.id})")
                    await self.channel.delete(reason=f"Check closed for {self.member_username}")
                    print(f"✅ Successfully deleted check channel: {self.channel.name}")
                except discord.NotFound:
                    print(f"⚠️ Channel already deleted: {self.channel.name}")
                except discord.Forbidden:
                    print(f"❌ Permission denied to delete channel: {self.channel.name}")
                except Exception as e:
                    print(f"❌ Error deleting channel: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Create the task
            task = asyncio.create_task(delete_channel_after_delay())
            print(f"📋 Task created for channel deletion: {task}")
            
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error closing check: {str(e)}",
                ephemeral=True
            )
            print(f"❌ Error closing check: {e}")
            import traceback
            traceback.print_exc()

# ============================================
# SLASH COMMANDS
# ============================================

async def spawn_verification_for_member(member, guild):
    """Background task to verify a single member"""
    try:
        answers, success = await collect_member_verification(member)
        
        if not success:
            print(f"❌ Verification failed for {member.name}")
            return
        
        # Get the verification channel
        verify_channel = bot.get_channel(MEMBER_VERIFY_CHANNEL_ID)
        
        if not verify_channel:
            return
        
        # Create embed with all answers
        embed = discord.Embed(
            title=f"📋 New Member Verification",
            description=f"**Member:** {member.mention}\n**Username:** {member.name}\n**ID:** {member.id}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        # Add each answer
        for i, question in enumerate(VERIFY_QUESTIONS, 1):
            answer = answers.get(f"question_{i}", "No answer provided")
            
            if len(answer) > 1024:
                answer = answer[:1021] + "..."
            
            embed.add_field(
                name=f"Q{i}: {question}",
                value=answer,
                inline=False
            )
        
        embed.set_footer(text="Use the buttons below to accept or deny this verification")
        
        # Send to verification channel with buttons
        view = VerificationView(member, answers, member_username=member.name)
        await verify_channel.send(embed=embed, view=view)
        
        print(f"✅ Verification submitted for {member.name}")
        
    except Exception as e:
        print(f"❌ Error verifying {member.name}: {e}")

@bot.tree.command(name="verify-all", description="Send verification to all members with pending role (Admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def verify_all(interaction: discord.Interaction):
    """Send verification questionnaire to all members with pending role"""
    
    if PENDING_ROLE_ID == 0:
        await interaction.response.send_message(
            "❌ PENDING_ROLE_ID not configured!",
            ephemeral=True
        )
        return
    
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    pending_role = guild.get_role(PENDING_ROLE_ID)
    
    if not pending_role:
        await interaction.followup.send(
            f"❌ Pending role {PENDING_ROLE_ID} not found!",
            ephemeral=True
        )
        return
    
    # Get all members with pending role
    members_to_verify = [m for m in guild.members if pending_role in m.roles]
    
    if not members_to_verify:
        await interaction.followup.send(
            "ℹ️ No members with pending role found!",
            ephemeral=True
        )
        return
    
    total = len(members_to_verify)
    
    print(f"\n🚀 Starting /verify-all for {total} members...")
    
    # Spawn verification tasks for all members (non-blocking)
    for i, member in enumerate(members_to_verify, 1):
        # Spawn as background task (don't wait for response)
        asyncio.create_task(spawn_verification_for_member(member, interaction.guild))
    
        # Small delay between spawning
        await asyncio.sleep(0.3)
        
        if i % 20 == 0:
            print(f"📤 Spawned verification for {i}/{total} members...")
    
    # Send success message immediately (no waiting)
    embed = discord.Embed(
        title="✅ Verification Sent!",
        description=f"Verification questionnaires have been sent to {total} members!\n\n"
                    f"⏱️ Each member has 5 minutes per question to respond.\n"
                    f"📩 Submissions will appear in the verification channel as they complete.",
        color=discord.Color.green(),
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="Total Members", value=f"`{total}`", inline=True)
    embed.add_field(name="Status", value="🔄 Processing in background", inline=True)
    embed.set_footer(text="Check console for progress")
    
    await interaction.followup.send(embed=embed)
    print(f"✅ /verify-all spawned {total} background tasks\n")

@bot.tree.command(name="verify", description="Start or restart your server verification")
async def verify(interaction: discord.Interaction):
    """Allow members to start verification"""
    
    await interaction.response.defer(ephemeral=True)
    
    # Check if they have the pending role
    if PENDING_ROLE_ID == 0:
        await interaction.followup.send("❌ Verification not configured!", ephemeral=True)
        return
    
    guild = interaction.guild
    pending_role = guild.get_role(PENDING_ROLE_ID)
    
    if not pending_role:
        await interaction.followup.send("❌ Pending role not found!", ephemeral=True)
        return
    
    # Only allow unverified members to verify
    if pending_role not in interaction.user.roles:
        await interaction.followup.send(
            "✅ You're already verified!",
            ephemeral=True
        )
        return
    
    await interaction.followup.send(
        "📝 Check your DMs for verification questions!",
        ephemeral=True
    )
    
    print(f"📋 Verification started by {interaction.user.name}")
    
    # Spawn verification in background
    asyncio.create_task(spawn_verification_for_member(interaction.user, guild))

@bot.tree.command(name="check", description="Create an age check channel for a member (Moderator only)")
@app_commands.describe(member="The member to check on")
@app_commands.checks.has_permissions(moderate_members=True)
async def check(interaction: discord.Interaction, member: discord.Member):
	"""Create a check channel for discussing a member - member loses verified role"""
	
	await interaction.response.defer(ephemeral=True)
	
	try:
		guild = interaction.guild
		
		# Get roles
		verified_role = guild.get_role(VERIFIED_ROLE_ID) if VERIFIED_ROLE_ID else None
		check_role = guild.get_role(CHECK_ROLE_ID) if CHECK_ROLE_ID else None
		
		if not verified_role:
			await interaction.followup.send(
				"❌ Configuration error: Verified role not found!",
				ephemeral=True
			)
			return
		
		if not check_role:
			await interaction.followup.send(
				"❌ Configuration error: Check role not found! Make sure CHECK_ROLE_ID is set correctly.",
				ephemeral=True
			)
			return
		
		# Remove verified role and add check role
		if verified_role in member.roles:
			await member.remove_roles(verified_role)
			print(f"✅ Removed verified role from {member.name}")
		
		if check_role not in member.roles:
			await member.add_roles(check_role)
			print(f"✅ Added check role to {member.name}")
		
		# Create channel name: age-check-[member_id]
		channel_name = f"age-check-{member.id}"
		
		# Create the channel in the main server (no category)
		try:
			channel = await guild.create_text_channel(
				name=channel_name,
				topic=f"Check for {member.name} (ID: {member.id})"
			)
			print(f"✅ Channel created: {channel_name}")
		except discord.Forbidden:
			await interaction.followup.send(
				"❌ I don't have permission to create channels!",
				ephemeral=True
			)
			return
		
		# Set up permissions
		# By default, @everyone can't see it
		await channel.set_permissions(
			guild.default_role,
			view_channel=False
		)
		
		# Allow the member to see and chat
		await channel.set_permissions(
			member,
			view_channel=True,
			send_messages=True  # Member CAN send messages
		)
		
		# Allow all moderators to see and talk
		for role in guild.roles:
			if role.permissions.moderate_members or role.permissions.administrator:
				await channel.set_permissions(
					role,
					view_channel=True,
					send_messages=True
				)
		
		# Allow the user who created the check
		await channel.set_permissions(
			interaction.user,
			view_channel=True,
			send_messages=True
		)
		
		print(f"✅ Set permissions for {channel_name}")
		
		# Send the check embed
		check_embed = discord.Embed(
			title=f"👤 Member Check: {member.name}",
			description=f"Check channel for {member.mention}",
			color=discord.Color.blue(),
			timestamp=discord.utils.utcnow()
		)
		check_embed.add_field(
			name="Member",
			value=f"{member.mention}",
			inline=True
		)
		check_embed.add_field(
			name="Username",
			value=f"`{member.name}`",
			inline=True
		)
		check_embed.add_field(
			name="User ID",
			value=f"`{member.id}`",
			inline=True
		)
		check_embed.add_field(
			name="Join Date",
			value=f"{member.joined_at.strftime('%Y-%m-%d %H:%M:%S') if member.joined_at else 'Unknown'}",
			inline=True
		)
		check_embed.add_field(
			name="Account Created",
			value=f"{member.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
			inline=True
		)
		check_embed.add_field(
			name="Roles",
			value=", ".join([role.mention for role in member.roles if role != guild.default_role]) or "No roles",
			inline=False
		)
		check_embed.add_field(
			name="Is Bot",
			value="✅ Yes" if member.bot else "❌ No",
			inline=True
		)
		check_embed.add_field(
			name="Check Status",
			value="🔍 Pending Review",
			inline=True
		)
		check_embed.set_footer(text="Use the button below to close this check when done")
		check_embed.set_thumbnail(url=member.avatar.url if member.avatar else None)
		
		# Send embed with close button
		view = CheckChannelView(member, channel)
		await channel.send(embed=check_embed, view=view)
		
		# Send info message
		await channel.send(
			f"✅ Check channel created by {interaction.user.mention}\n"
			f"🔍 Moderators are reviewing your account\n"
			f"📝 Click the button above to close this check when done"
		)
		
		# Notify the moderator who created the check
		notify_embed = discord.Embed(
			title="✅ Check Channel Created",
			description=f"Check channel created for {member.mention}",
			color=discord.Color.green(),
			timestamp=discord.utils.utcnow()
		)
		notify_embed.add_field(
			name="Member",
			value=member.mention,
			inline=True
		)
		notify_embed.add_field(
			name="Channel",
			value=channel.mention,
			inline=True
		)
		notify_embed.add_field(
			name="Channel Name",
			value=f"`{channel_name}`",
			inline=True
		)
		notify_embed.add_field(
			name="Action Taken",
			value=f"❌ Removed: {verified_role.mention}\n✅ Added: {check_role.mention}",
			inline=False
		)
		notify_embed.add_field(
			name="Created By",
			value=interaction.user.mention,
			inline=False
		)
		
		await interaction.followup.send(embed=notify_embed, ephemeral=True)
		
		# Send DM to member notifying them
		try:
			dm_embed = discord.Embed(
				title="⚠️ Account Check",
				description="Your account is under review by moderators.",
				color=discord.Color.orange(),
				timestamp=discord.utils.utcnow()
			)
			dm_embed.add_field(
				name="What Happened",
				value="Your verified role has been temporarily removed while moderators review your account.",
				inline=False
			)
			dm_embed.add_field(
				name="What to Do",
				value=f"Please go to {channel.mention} and wait for moderators to review your information.",
				inline=False
			)
			dm_embed.add_field(
				name="Note",
				value="This is a routine check. Please remain calm and patient.",
				inline=False
			)
			dm_embed.set_footer(text="Moderators will close this check when done")
			
			await member.send(embed=dm_embed)
			print(f"📨 Sent check notification DM to {member.name}")
		except discord.Forbidden:
			print(f"⚠️ Could not send DM to {member.name} (DMs disabled)")
		
		print(f"✅ Check channel created for {member.name} by {interaction.user.name}")
		print(f"   Channel: {channel.name} (ID: {channel.id})")
		
	except Exception as e:
		await interaction.followup.send(
			f"❌ Error creating check channel: {str(e)}",
			ephemeral=True
		)
		print(f"❌ Error in /check command: {e}")
		import traceback
		traceback.print_exc()

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
            f"📤 Sent to <#{NSFW_VERIFY_CHANNEL_ID}>",
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
@verify_all.error
async def verify_all_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ You need Administrator permission to use this command!", ephemeral=True)

@check.error
async def check_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
	if isinstance(error, app_commands.MissingPermissions):
		await interaction.response.send_message(
			"❌ You need Moderator permission to use this command!",
			ephemeral=True
		)

# ============================================
# BOT EVENTS
# ============================================

@bot.event
async def on_member_join(member):
    """Handle new member joins - send verification questionnaire"""
    
    print(f"\n👤 New member joined: {member.name} ({member.id})")
    
    if MEMBER_VERIFY_CHANNEL_ID == 0:
        print(f"⚠️ MEMBER_VERIFY_CHANNEL_ID not configured, skipping verification")
        return
    
    if PENDING_ROLE_ID == 0:
        print(f"⚠️ PENDING_ROLE_ID not configured, skipping verification")
        return
    
    if VERIFIED_ROLE_ID == 0:
        print(f"⚠️ VERIFIED_ROLE_ID not configured, skipping verification")
        return
    
    try:
        # Give member the pending role
        guild = member.guild
        pending_role = guild.get_role(PENDING_ROLE_ID)
        
        if not pending_role:
            print(f"❌ Pending role {PENDING_ROLE_ID} not found!")
            return
        
        await member.add_roles(pending_role)
        print(f"✅ Added pending role to {member.name}")
        
        # Send welcome message and start verification
        welcome_embed = discord.Embed(
            title="👋 Welcome!",
            description="Thank you for joining our server! We need you to complete a verification process to join our community.",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        welcome_embed.add_field(
            name="What's Next?",
            value="Check your DMs for verification questions. You have 5 minutes to answer each question.",
            inline=False
        )
        
        try:
            await member.send(embed=welcome_embed)
        except discord.Forbidden:
            print(f"❌ Cannot send DM to {member} - DMs closed")
            return
        
        # Collect verification answers
        print(f"📋 Starting verification for {member.name}...")
        answers, success = await collect_member_verification(member)
        
        if not success:
            print(f"❌ Verification failed for {member.name}")
            return
        
        # Get the verification channel
        verify_channel = bot.get_channel(MEMBER_VERIFY_CHANNEL_ID)
        
        if not verify_channel:
            print(f"❌ Verification channel {MEMBER_VERIFY_CHANNEL_ID} not found!")
            return
        
        # Create embed with all answers
        embed = discord.Embed(
            title=f"📋 New Member Verification",
            description=f"**Member:** {member.mention}\n**Username:** {member.name}\n**ID:** {member.id}",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        # Add each answer
        for i, question in enumerate(VERIFY_QUESTIONS, 1):
            answer = answers.get(f"question_{i}", "No answer provided")
            
            # Truncate long answers for embed field
            if len(answer) > 1024:
                answer = answer[:1021] + "..."
            
            embed.add_field(
                name=f"Q{i}: {question}",
                value=answer,
                inline=False
            )
        
        embed.set_footer(text="Use the buttons below to accept or deny this verification")
        
        # Send to verification channel with buttons
        view = VerificationView(member, answers, member_username=member.name)
        msg = await verify_channel.send(embed=embed, view=view)
        
        print(f"✅ Verification submitted for {member.name} - Message ID: {msg.id}")
        
    except Exception as e:
        print(f"❌ Error in member join handler: {e}")
        import traceback
        traceback.print_exc()

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
    print(f"   Member Verification Channel: {MEMBER_VERIFY_CHANNEL_ID}")
    print(f"   Pending Role: {PENDING_ROLE_ID}")
    print(f"   Verified Role: {VERIFIED_ROLE_ID}")
    print(f"   Check Role: {CHECK_ROLE_ID}")
    print(f"   Roblox Group ID: {ROBLOX_GROUP_ID}")
    print("\n💡 Available Commands:")
    print("   - /nsfw-verify: Submit image for verification")
    print("   - /requestaccess: Request to join Roblox group")
    print("   - /verify: Start verification")
    print("   - /verify-all: Send verification to all pending members")
    print("   - /check: Create age check channel for a member")
    print("\n📝 Events:")
    print("   - Member Join: Automatic verification questionnaire")

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
