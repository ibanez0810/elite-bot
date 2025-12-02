import os
import discord
from discord.ext import commands, tasks
from datetime import datetime
from zoneinfo import ZoneInfo
import asyncio
import json
from pathlib import Path

from flask import Flask
from threading import Thread

# ==============================
# KEEP-ALIVE WEBSEITE (für Replit + UptimeRobot)
# ==============================

app = Flask(__name__)

@app.route("/")
def home():
    return "Guild Helper Bot is running"

def run_web():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()


# ==============================
# KONFIG
# ==============================

# Bot-Token aus Replit-Secret (Key: BOT_TOKEN)
BOT_TOKEN = os.getenv("BOT_TOKEN")

ELITE_CHANNEL_ID = 1333099958286549106
ELITE_ROLE_ID = 1444804570680398006   # @Elite
LEADER_ROLE_ID = 1333093607791657031  # @Leader

ELITE_HOURS = {0, 6, 8, 10, 12, 14, 16, 18, 20, 22}
QUIET_HOURS = {0, 6, 8, 22}

MEDALS_PER_PLACE = {
    1: 8,
    2: 6,
    3: 5,
    4: 4,
    5: 3,
    6: 2,
    7: 1,
    8: 0,
}

DATA_FILE = Path("elite_data.json")

# ==============================
# BOT & INTENTS
# ==============================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ==============================
# DATENVERWALTUNG
# ==============================

def load_data():
    if DATA_FILE.exists():
        with DATA_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {"players": {}}


def save_data(data):
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


data = load_data()


def ensure_player(uid):
    uid = str(uid)
    if uid not in data["players"]:
        data["players"][uid] = {
            "medals": 0,
            "pvm_runs": 0,
            "pvp_runs": 0,
            "manual_medals": 0
        }
    else:
        data["players"][uid].setdefault("manual_medals", 0)
    return data["players"][uid]


def add_participation(uid, medals=0, is_pvp=False):
    player = ensure_player(uid)
    if is_pvp:
        player["pvp_runs"] += 1
    else:
        player["pvm_runs"] += 1
        player["medals"] += medals
    save_data(data)


# ==============================
# BUTTONS / VIEW
# ==============================

class EliteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60 * 60)
        self.taken_places = set()
        self.user_choices = set()

    async def _handle_place(self, interaction, place):
        user_id = interaction.user.id

        if user_id in self.user_choices:
            await interaction.response.send_message(
                "Du hast in diesem Run bereits eine Auswahl getroffen.",
                ephemeral=True
            )
            return

        if place in self.taken_places:
            await interaction.response.send_message(
                f"Platz {place} ist schon vergeben.",
                ephemeral=True
            )
            return

        medals = MEDALS_PER_PLACE.get(place, 0)
        add_participation(user_id, medals=medals)

        self.taken_places.add(place)
        self.user_choices.add(user_id)

        await interaction.response.send_message(
            f"Danke, dass du **Platz {place}** belegt hast! (+{medals} Medaillen)",
            ephemeral=True
        )

    @discord.ui.button(label="Platz 1 (8)", style=discord.ButtonStyle.green)
    async def place1(self, interaction, button):
        await self._handle_place(interaction, 1)

    @discord.ui.button(label="Platz 2 (6)", style=discord.ButtonStyle.green)
    async def place2(self, interaction, button):
        await self._handle_place(interaction, 2)

    @discord.ui.button(label="Platz 3 (5)", style=discord.ButtonStyle.green)
    async def place3(self, interaction, button):
        await self._handle_place(interaction, 3)

    @discord.ui.button(label="Platz 4 (4)", style=discord.ButtonStyle.blurple)
    async def place4(self, interaction, button):
        await self._handle_place(interaction, 4)

    @discord.ui.button(label="Platz 5 (3)", style=discord.ButtonStyle.blurple)
    async def place5(self, interaction, button):
        await self._handle_place(interaction, 5)

    @discord.ui.button(label="Platz 6 (2)", style=discord.ButtonStyle.gray)
    async def place6(self, interaction, button):
        await self._handle_place(interaction, 6)

    @discord.ui.button(label="Platz 7 (1)", style=discord.ButtonStyle.gray)
    async def place7(self, interaction, button):
        await self._handle_place(interaction, 7)

    @discord.ui.button(label="PvP", style=discord.ButtonStyle.red)
    async def pvp(self, interaction, button):
        user_id = interaction.user.id

        if user_id in self.user_choices:
            await interaction.response.send_message(
                "Du hast bereits eine Auswahl getroffen.",
                ephemeral=True
            )
            return

        add_participation(user_id, medals=0, is_pvp=True)
        self.user_choices.add(user_id)

        await interaction.response.send_message(
            "Danke, dass du als **PvP** dabei warst! (0 Medaillen)",
            ephemeral=True
        )

    @discord.ui.button(label="PvM (kein Rang)", style=discord.ButtonStyle.gray)
    async def pvm_norank(self, interaction, button):
        user_id = interaction.user.id

        if user_id in self.user_choices:
            await interaction.response.send_message(
                "Du hast bereits eine Auswahl getroffen.",
                ephemeral=True
            )
            return

        add_participation(user_id, medals=0, is_pvp=False)
        self.user_choices.add(user_id)

        await interaction.response.send_message(
            "Danke, dass du als **PvM (kein Rang)** dabei warst! (0 Medaillen)",
            ephemeral=True
        )


# ==============================
# ERINNERUNGEN
# ==============================

@tasks.loop(minutes=1)
async def elite_reminder():
    """Checkt jede Minute Europe/Vienna und triggert bei xx:00/xx:08."""
    channel = bot.get_channel(ELITE_CHANNEL_ID)
    if not channel:
        return

    now = datetime.now(ZoneInfo("Europe/Vienna"))
    hour = now.hour
    minute = now.minute

    if hour not in ELITE_HOURS:
        return

    if minute == 0:
        if hour in QUIET_HOURS:
            prefix = ""
        else:
            prefix = f"<@&{ELITE_ROLE_ID}> "

        await channel.send(
            f"{prefix}**Elite läuft jetzt!** 🥷\n"
            "Nach der Elite könnt ihr euren Platz eintragen."
        )

    if minute == 8:
        view = EliteView()
        await channel.send(
            "Elite vorbei – bitte tragt euren Platz oder PvP ein:",
            view=view
        )


@elite_reminder.before_loop
async def before_elite():
    await bot.wait_until_ready()


# ==============================
# KOMMANDOS
# ==============================

@bot.command(name="testrun")
async def testrun(ctx):
    await ctx.send("⚔️ **Test-Run** – hier sind die Buttons:")
    await ctx.send(view=EliteView())


@bot.command(name="medals")
async def medals(ctx):
    if not data["players"]:
        return await ctx.send("Es sind noch keine Daten vorhanden.")

    guild = ctx.guild

    sorted_players = sorted(
        data["players"].items(),
        key=lambda x: x[1]["medals"] + x[1]["manual_medals"],
        reverse=True
    )

    msg = "**Medaillen-Übersicht:**\n"
    for uid, stats in sorted_players:
        member = guild.get_member(int(uid))
        name = member.display_name if member else f"ID {uid}"
        total = stats["medals"] + stats["manual_medals"]
        msg += (
            f"**{name}** – {total} Medaillen "
            f"(Auto: {stats['medals']}, Manuell: {stats['manual_medals']}, "
            f"PvM: {stats['pvm_runs']}, PvP: {stats['pvp_runs']})\n"
        )

    await ctx.send(msg)


@bot.command(name="allmedals")
async def allmedals(ctx):
    auto_total = sum(p["medals"] for p in data["players"].values())
    manual_total = sum(p["manual_medals"] for p in data["players"].values())
    total = auto_total + manual_total

    await ctx.send(
        "**Gesamt gesammelte Medaillen:**\n"
        f"- Automatisch: **{auto_total}**\n"
        f"- Manuell: **{manual_total}**\n"
        f"- Gesamt: **{total}**"
    )


@bot.command(name="collected")
async def collected(ctx, amount: int):
    if amount < 0:
        return await ctx.send("Negative Zahlen gehen nicht 😅")

    player = ensure_player(ctx.author.id)
    before = player["manual_medals"]
    player["manual_medals"] += amount
    if player["manual_medals"] < 0:
        player["manual_medals"] = 0
    save_data(data)

    await ctx.send(
        f"{ctx.author.mention}, es wurden **{amount}** manuelle Medaillen hinzugefügt.\n"
        f"Manuell gesamt: **{player['manual_medals']}** (vorher: {before})."
    )


@bot.command(name="collectedremove")
async def collectedremove(ctx, amount: int):
    if amount < 0:
        return await ctx.send("Negative Zahlen gehen nicht 😅")

    player = ensure_player(ctx.author.id)
    before = player["manual_medals"]
    player["manual_medals"] = max(0, player["manual_medals"] - amount)
    save_data(data)

    await ctx.send(
        f"{ctx.author.mention}, es wurden **{amount}** manuelle Medaillen abgezogen.\n"
        f"Manuell gesamt: **{player['manual_medals']}** (vorher: {before})."
    )


@bot.command(name="setmanual")
async def setmanual(ctx, member: discord.Member, amount: int):
    leader_role = ctx.guild.get_role(LEADER_ROLE_ID)

    if not leader_role or leader_role not in ctx.author.roles:
        return await ctx.send("Nur die Leader-Rolle darf diesen Befehl nutzen.")

    if amount < 0:
        return await ctx.send("Negative Zahlen gehen nicht 😅")

    player = ensure_player(member.id)
    before = player["manual_medals"]
    player["manual_medals"] = amount
    save_data(data)

    await ctx.send(
        f"Die **manuellen Medaillen** von {member.mention} wurden von **{before}** auf **{amount}** gesetzt."
    )


@bot.command(name="elitereset")
async def elitereset(ctx):
    leader_role = ctx.guild.get_role(LEADER_ROLE_ID)

    if not leader_role or leader_role not in ctx.author.roles:
        return await ctx.send("Nur die Leader-Rolle darf diesen Befehl nutzen.")

    global data
    data = {"players": {}}
    save_data(data)

    await ctx.send("Alle Medaillen-Daten wurden zurückgesetzt.")


@bot.command(name="info")
async def info(ctx):
    await ctx.send(
        "**DEUTSCH 🇩🇪**\n"
        "- Der Bot erinnert automatisch zu jeder Elite.\n"
        "- Nach der Elite sendet er Buttons für Platzierung / PvP / PvM (kein Rang).\n"
        "- Jeder Klick trägt Medaillen & Runs automatisch ein.\n"
        "- `!medals` → Übersicht aller Spieler.\n"
        "- `!allmedals` → Gesamtzahl aller Medaillen (automatisch + manuell).\n"
        "- `!collected <Zahl>` → Manuelle Medaillen **hinzufügen** "
        "(z.B. alte Runs oder vergessene Platzierungen).\n"
        "- `!collectedremove <Zahl>` → Manuelle Medaillen wieder **abziehen**, "
        "falls du dich vertippt hast.\n"
        "- `!setmanual @User <Zahl>` → Setzt die manuellen Medaillen eines Spielers direkt "
        "(nur Leader-Rolle).\n\n"
        "**ENGLISH 🇬🇧**\n"
        "- The bot automatically reminds your guild for each Elite.\n"
        "- After Elite it sends buttons for placements / PvP / PvM (no rank).\n"
        "- Every click updates medals & runs automatically.\n"
        "- `!medals` → Overview of all players.\n"
        "- `!allmedals` → Total medals (automatic + manual).\n"
        "- `!collected <number>` → **Add** manual medals "
        "(e.g. for previous runs or missed placements).\n"
        "- `!collectedremove <number>` → **Remove** manual medals again if you mistyped.\n"
        "- `!setmanual @User <number>` → Directly sets a player's manual medals "
        "(Leader role only).\n"
    )


@bot.command(name="comands")
async def comands(ctx):
    await ctx.send(
        "**Befehle:**\n"
        "- `!testrun` – Buttons testen\n"
        "- `!medals` – Übersicht aller Spieler\n"
        "- `!allmedals` – Gesamtmedaillen (automatisch + manuell)\n"
        "- `!collected <Zahl>` – manuelle Medaillen **hinzufügen** "
        "(z.B. alte oder vergessene Runs)\n"
        "- `!collectedremove <Zahl>` – manuelle Medaillen **abziehen** "
        "(Korrektur bei Vertippern)\n"
        "- `!setmanual @User <Zahl>` – setzt manuelle Medaillen eines Spielers direkt "
        "(nur Leader)\n"
        "- `!elitereset` – Reset aller Daten (nur Leader-Rolle)\n"
        "- `!info` – Infos (DE/EN)\n"
        "- `!comands` – diese Befehlsübersicht"
    )


# ==============================
# START
# ==============================

@bot.event
async def on_ready():
    print(f"Eingeloggt als {bot.user} (ID: {bot.user.id})")
    if not elite_reminder.is_running():
        elite_reminder.start()


if __name__ == "__main__":
    keep_alive()
    bot.run(BOT_TOKEN)