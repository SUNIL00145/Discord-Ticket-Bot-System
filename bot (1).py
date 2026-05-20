import discord
from discord.ext import commands
import asyncio
import json
import os
import time
from datetime import datetime, timezone
from io import BytesIO

#CONFIG
BOT_TOKEN = "TOKEN"
STAFF_ROLE_ID = 11111111111111111
TRANSCRIPT_CHANNEL_ID = 111111111111111111  
DATA_FILE = "ticket_data.json"
TICKET_COOLDOWN = 30

CATEGORIES = {
    "Bug Report": ("Bug Report", 11111111111111111111),
    "Product Buy": ("Product Buy", 11111111111111111),
    "Sponsorship": ("Sponsorship", 111111111111111),
    "Installation-Help": ("Installation-Help", 111111111111111111),
}

TICKET_DESCRIPTIONS = {
    "Bug Report": "🛠️ Please describe your **Bug Report** clearly.\nOur support team will assist you shortly.",
    "Product Buy": "💳 Please provide details about your **Product Buy**, invoice ID, or transaction.\nBilling staff will assist you shortly.",
    "Sponsorship": "🤝 Please explain your **sponsorship request** with full details.\nOur team will review and respond soon.",
    "Installation-Help": "📌 Please describe your Installation-Help detail.\nStaff will assist you shortly."
}

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

#DATA
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
else:
    data = {}

data.setdefault("counters", {k: 0 for k in CATEGORIES})
data.setdefault("open_tickets", {})

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def next_ticket_number(cat):
    data["counters"][cat] += 1
    save_data()
    return f"{cat}-{data['counters'][cat]:03d}"

def safe_topic(channel):
    try:
        return json.loads(channel.topic)
    except:
        return {}

#COOLDOWN
ticket_cooldowns = {}

def on_cooldown(user_id):
    now = time.monotonic()
    last = ticket_cooldowns.get(user_id)
    if last and now - last < TICKET_COOLDOWN:
        return True
    ticket_cooldowns[user_id] = now
    return False

def cooldown_left(user_id):
    return max(0, int(TICKET_COOLDOWN - (time.monotonic() - ticket_cooldowns.get(user_id, 0))))

#DM
async def send_dm(user, embed):
    try:
        await user.send(embed=embed)
    except:
        pass

#TRANSCRIPT
async def create_transcript(channel: discord.TextChannel):
    lines = []
    lines.append(f"Transcript for #{channel.name}")
    lines.append(f"Server: {channel.guild.name}")
    lines.append(f"Created at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 60)
    lines.append("")

    async for msg in channel.history(limit=None, oldest_first=True):
        time_str = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
        author = f"{msg.author} ({msg.author.id})"

        lines.append(f"[{time_str}] {author}")

        if msg.content:
            lines.append(msg.content)

        for att in msg.attachments:
            lines.append(f"[Attachment] {att.url}")

        for emb in msg.embeds:
            if emb.title:
                lines.append(f"[Embed Title] {emb.title}")
            if emb.description:
                lines.append(emb.description)

        lines.append("-" * 40)

    transcript_text = "\n".join(lines).encode("utf-8")

    return discord.File(
        fp=BytesIO(transcript_text),
        filename=f"{channel.name}.txt"
    )

#CREATE TICKET
async def create_ticket(interaction, cat):
    user = interaction.user
    label, category_id = CATEGORIES[cat]
    key = f"{user.id}:{cat}"

    if key in data["open_tickets"]:
        return await interaction.followup.send(
            embed=discord.Embed(
                title="❗ Ticket Already Open",
                description="You already have an open ticket in this category.",
                color=0xED4245
            ),
            ephemeral=True
        )

    number = next_ticket_number(cat)
    category = interaction.guild.get_channel(category_id)

    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
        user: discord.PermissionOverwrite(read_messages=True),
        interaction.guild.get_role(STAFF_ROLE_ID): discord.PermissionOverwrite(read_messages=True),
    }

    channel = await interaction.guild.create_text_channel(
        name=number,
        category=category,
        overwrites=overwrites
    )

    await channel.edit(topic=json.dumps({
        "creator_id": user.id,
        "category": cat,
        "created_at": datetime.now(timezone.utc).isoformat()
    }))

    data["open_tickets"][key] = channel.id
    save_data()

    await channel.send(
        f"<@&{STAFF_ROLE_ID}>",
        embed=discord.Embed(
            title=f"{label} Ticket",
            description=f"{user.mention}, {TICKET_DESCRIPTIONS.get(cat, 'Please describe your issue.')}",
            color=0x2F3136
        ),
        view=TicketButtons()
    )

    # DM CREATE 
    dm = discord.Embed(title="🎫 Ticket Created", color=0x57F287)
    dm.add_field(name="Server", value=interaction.guild.name, inline=False)
    dm.add_field(name="Category", value=label, inline=True)
    dm.add_field(name="Ticket ID", value=number, inline=True)
    dm.add_field(name="Ticket Link", value=channel.mention, inline=False)
    await send_dm(user, dm)

    await interaction.followup.send(
        embed=discord.Embed(
            title="✅ Ticket Created",
            description=channel.mention,
            color=0x57F287
        ),
        ephemeral=True
    )

#BUTTON VIEW
class TicketButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.secondary)
    async def claim(self, interaction, _):
        if not any(r.id == STAFF_ROLE_ID for r in interaction.user.roles):
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title="❌ Permission Denied",
                    description="Only staff can claim tickets.",
                    color=0xED4245
                ),
                ephemeral=True
            )

        meta = safe_topic(interaction.channel)
        if meta.get("claimed_by"):
            return await interaction.response.send_message(
                embed=discord.Embed(
                    title="❗ Already Claimed",
                    description="This ticket is already claimed.",
                    color=0xF1C40F
                ),
                ephemeral=True
            )

        meta["claimed_by"] = interaction.user.id
        await interaction.channel.edit(topic=json.dumps(meta))

        await interaction.response.send_message(
            embed=discord.Embed(
                title="🔒 Ticket Claimed",
                description=f"Claimed by {interaction.user.mention}",
                color=0x3498DB
            )
        )

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger)
    async def close(self, interaction, _):
        await interaction.response.defer(ephemeral=True)

        if not interaction.user.guild_permissions.administrator:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ Access Denied",
                    description="Only **admins** can close tickets.",
                    color=0xED4245
                ),
                ephemeral=True
            )

        meta = safe_topic(interaction.channel)
        creator = interaction.guild.get_member(meta.get("creator_id"))
        cat = meta.get("category")

        # 🧾 SEND TRANSCRIPT FIRST
        log_channel = interaction.guild.get_channel(TRANSCRIPT_CHANNEL_ID)
        if log_channel:
            transcript = await create_transcript(interaction.channel)
            await log_channel.send(
                content=f"🧾 **Transcript | {interaction.channel.name}**",
                file=transcript
            )

        data["open_tickets"].pop(f"{meta.get('creator_id')}:{cat}", None)
        save_data()

        # DM CLOSE
        if creator:
            dm = discord.Embed(title="🔒 Ticket Closed", color=0xED4245)
            dm.add_field(name="Server", value=interaction.guild.name, inline=False)
            dm.add_field(name="Category", value=CATEGORIES[cat][0], inline=True)
            dm.add_field(name="Ticket ID", value=interaction.channel.name, inline=True)
            dm.add_field(name="Closed By", value=interaction.user.mention, inline=False)
            await send_dm(creator, dm)

        await interaction.channel.delete()

#PANEL
class TicketSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(
            placeholder="Select ticket category",
            options=[discord.SelectOption(label=v[0], value=k) for k, v in CATEGORIES.items()]
        )

    async def callback(self, interaction):
        await interaction.response.send_message(
            embed=discord.Embed(
                title="⏳ Processing",
                description="Creating your ticket...",
                color=0x95A5A6
            ),
            ephemeral=True
        )

        if on_cooldown(interaction.user.id):
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="⏱ Cooldown Active",
                    description=f"Please wait **{cooldown_left(interaction.user.id)}s** before creating another ticket.",
                    color=0xF1C40F
                ),
                ephemeral=True
            )

        asyncio.create_task(create_ticket(interaction, self.values[0]))

class TicketPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())

@bot.command()
@commands.has_permissions(administrator=True)
async def send_panel(ctx):
    await ctx.send(
        embed=discord.Embed(
            title="🎫 Aether Tickets",
            description=(
                "📌Reach out to us for any queries:.\n\n"
            ),
            color=0x5865F2
        ),
        view=TicketPanel()
    )
    await ctx.message.delete()

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

bot.run(BOT_TOKEN)