import os
import sqlite3
import discord
from discord import app_commands, ui
from discord.ext import commands
from keep_alive import keep_alive

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Traccia l'ultimo messaggio SSU/SSD per canale { channel_id: message }
session_messages: dict[int, discord.Message] = {}

DB_PATH = "verona_rp.db"


# ---------------------------------------------------------------------------
# DATABASE SETUP
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS citizens (
            user_id     TEXT PRIMARY KEY,
            username    TEXT,
            cash        REAL DEFAULT 0,
            bank        REAL DEFAULT 0,
            stato_civile TEXT DEFAULT 'Celibe/Nubile',
            patente     INTEGER DEFAULT 0,
            porto_darmi INTEGER DEFAULT 0,
            partita_iva INTEGER DEFAULT 0,
            perma_jail  INTEGER DEFAULT 0,
            perma_jail_motivo TEXT DEFAULT '',
            perma_death INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS fdo (
            user_id     TEXT PRIMARY KEY,
            grado       TEXT DEFAULT '',
            reparto     TEXT DEFAULT '',
            in_servizio INTEGER DEFAULT 1
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS multe (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT,
            importo     REAL,
            motivo      TEXT,
            pagata      INTEGER DEFAULT 0,
            data        TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS arresti (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT,
            motivo      TEXT,
            data        TEXT DEFAULT (datetime('now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS veicoli (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     TEXT,
            veicolo     TEXT,
            targa       TEXT,
            sequestrato INTEGER DEFAULT 0,
            motivo_seq  TEXT DEFAULT ''
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS cartelle (
            user_id     TEXT PRIMARY KEY,
            note        TEXT DEFAULT ''
        )
    """)

    conn.commit()
    conn.close()


def ensure_citizen(user_id: str, username: str):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO citizens (user_id, username) VALUES (?, ?)",
        (user_id, username)
    )
    conn.commit()
    conn.close()


def is_blocked(user_id: str) -> str | None:
    """Returns a reason string if the user is blocked, else None."""
    conn = get_db()
    row = conn.execute(
        "SELECT perma_jail, perma_jail_motivo, perma_death FROM citizens WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    if row["perma_death"]:
        return "Il tuo personaggio è in stato di **Perma Death** e non può eseguire azioni."
    if row["perma_jail"]:
        return f"Sei in **Perma Jail**. Motivo: {row['perma_jail_motivo']}"
    return None


def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator


# ---------------------------------------------------------------------------
# EVENTS
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot avviato come {bot.user} (ID: {bot.user.id})")
    print("Comandi sincronizzati.")


# ---------------------------------------------------------------------------
# COMANDI GENERALI
# ---------------------------------------------------------------------------

@bot.tree.command(name="help-verona", description="Mostra tutti i comandi del bot VERONA ITA RP")
async def help_verona(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Comandi VERONA ITA RP",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else discord.Embed.Empty)

    embed.add_field(name="🪪 Documenti", value=(
        "`/help-verona` — Lista comandi\n"
        "`/mostra-documenti [utente]` — Documenti personali"
    ), inline=False)

    embed.add_field(name="💰 Economia & Lavoro", value=(
        "`/portafoglio` — Saldo contanti e banca\n"
        "`/preleva [somma]` — Preleva dalla banca\n"
        "`/paga-contanti [utente] [somma]` — Paga in contanti\n"
        "`/paga-carta [utente] [somma]` — Bonifico bancario\n"
        "`/partita-iva [utente] [registra/revoca]` — Gestisci P.IVA"
    ), inline=False)

    embed.add_field(name="🚔 Forze dell'Ordine & Giustizia", value=(
        "`/fdo-scheda [utente]` — Scheda agente FDO\n"
        "`/fdo-sospendi [utente]` — Sospendi/riattiva agente\n"
        "`/multa [utente] [importo] [motivo]` — Emetti multa\n"
        "`/paga-multa [id]` — Paga una multa\n"
        "`/storico-multe [utente]` — Storico multe\n"
        "`/storico-arresti [utente]` — Fedina penale\n"
        "`/perma-jail [utente] [motivo]` — Isolamento permanente\n"
        "`/perma-death [utente]` — Morte permanente del personaggio"
    ), inline=False)

    embed.add_field(name="🚗 Veicoli & Motorizzazione", value=(
        "`/immatricolazione [utente] [veicolo] [targa]` — Registra veicolo\n"
        "`/sequestro-veicolo [utente] [veicolo] [motivo]` — Sequestra veicolo\n"
        "`/rilascia-veicolo [id]` — Rilascia veicolo\n"
        "`/patente [utente] [rilascia/revoca]` — Gestisci patente"
    ), inline=False)

    embed.add_field(name="🏥 Sanità & Armi", value=(
        "`/aggiungi-cartella [utente] [note]` — Cartella clinica\n"
        "`/rimuovi-cartella [utente]` — Elimina cartella clinica\n"
        "`/porto-darmi [utente] [rilascia/revoca]` — Porto d'armi"
    ), inline=False)

    embed.add_field(name="⚙️ Admin & Sessioni", value=(
        "`/modifica-soldi [utente] [azione] [tipo] [qty]` — Admin soldi\n"
        "`/ssu` — Server On (inizio sessione RP)\n"
        "`/ssd` — Server Shut Down (fine sessione RP)\n"
        "`/votazione [titolo] [op1] [op2]` — Crea sondaggio"
    ), inline=False)

    embed.set_footer(text="VERONA ITA RP — Bot Ufficiale")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="mostra-documenti", description="Mostra i documenti personali di un cittadino")
@app_commands.describe(utente="Il cittadino di cui visualizzare i documenti (lascia vuoto per i tuoi)")
async def mostra_documenti(interaction: discord.Interaction, utente: discord.Member = None):
    target = utente or interaction.user
    ensure_citizen(str(target.id), target.display_name)
    conn = get_db()
    row = conn.execute("SELECT * FROM citizens WHERE user_id=?", (str(target.id),)).fetchone()
    conn.close()

    embed = discord.Embed(
        title=f"🪪 Documenti Ufficiali — {target.display_name}",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="👤 Nome", value=target.display_name, inline=True)
    embed.add_field(name="💍 Stato Civile", value=row["stato_civile"], inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="🚗 Patente", value="✅ Valida" if row["patente"] else "❌ Non posseduta", inline=True)
    embed.add_field(name="🔫 Porto d'Armi", value="✅ Valido" if row["porto_darmi"] else "❌ Non posseduto", inline=True)
    embed.add_field(name="📋 Partita IVA", value="✅ Registrata" if row["partita_iva"] else "❌ Non registrata", inline=True)
    if row["perma_jail"]:
        embed.add_field(name="🔒 Stato", value=f"⚠️ **PERMA JAIL** — {row['perma_jail_motivo']}", inline=False)
    if row["perma_death"]:
        embed.add_field(name="💀 Stato", value="☠️ **PERMA DEATH** — Personaggio deceduto permanentemente", inline=False)
    embed.set_footer(text="⚙️ VERONA ITA RP — Documenti Ufficiali")
    await interaction.response.send_message(embed=embed)


# ---------------------------------------------------------------------------
# ECONOMIA E LAVORO
# ---------------------------------------------------------------------------

@bot.tree.command(name="portafoglio", description="Mostra il tuo saldo contanti e bancario")
async def portafoglio(interaction: discord.Interaction):
    ensure_citizen(str(interaction.user.id), interaction.user.display_name)
    block = is_blocked(str(interaction.user.id))
    if block:
        await interaction.response.send_message(f"⛔ {block}", ephemeral=True)
        return
    conn = get_db()
    row = conn.execute("SELECT cash, bank FROM citizens WHERE user_id=?", (str(interaction.user.id),)).fetchone()
    conn.close()
    embed = discord.Embed(title=f"💼 Portafoglio di {interaction.user.display_name}", color=discord.Color.green())
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(name="💵 Contanti in tasca", value=f"```€{row['cash']:,.2f}```", inline=True)
    embed.add_field(name="🏦 Conto Bancario", value=f"```€{row['bank']:,.2f}```", inline=True)
    embed.set_footer(text="⚙️ VERONA ITA RP — Sistema Economico")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="preleva", description="Preleva denaro dalla banca ai contanti")
@app_commands.describe(somma="Importo da prelevare")
async def preleva(interaction: discord.Interaction, somma: float):
    ensure_citizen(str(interaction.user.id), interaction.user.display_name)
    block = is_blocked(str(interaction.user.id))
    if block:
        await interaction.response.send_message(f"⛔ {block}", ephemeral=True)
        return
    if somma <= 0:
        await interaction.response.send_message("❌ L'importo deve essere positivo.", ephemeral=True)
        return
    conn = get_db()
    row = conn.execute("SELECT bank FROM citizens WHERE user_id=?", (str(interaction.user.id),)).fetchone()
    if row["bank"] < somma:
        conn.close()
        await interaction.response.send_message("❌ Fondi insufficienti in banca.", ephemeral=True)
        return
    conn.execute(
        "UPDATE citizens SET bank=bank-?, cash=cash+? WHERE user_id=?",
        (somma, somma, str(interaction.user.id))
    )
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"✅ Hai prelevato **€{somma:,.2f}** dalla banca.")


@bot.tree.command(name="paga-contanti", description="Trasferisci contanti a un altro utente")
@app_commands.describe(utente="Destinatario", somma="Importo da pagare")
async def paga_contanti(interaction: discord.Interaction, utente: discord.Member, somma: float):
    ensure_citizen(str(interaction.user.id), interaction.user.display_name)
    ensure_citizen(str(utente.id), utente.display_name)
    block = is_blocked(str(interaction.user.id))
    if block:
        await interaction.response.send_message(f"⛔ {block}", ephemeral=True)
        return
    if somma <= 0:
        await interaction.response.send_message("❌ L'importo deve essere positivo.", ephemeral=True)
        return
    if utente.id == interaction.user.id:
        await interaction.response.send_message("❌ Non puoi pagare te stesso.", ephemeral=True)
        return
    conn = get_db()
    row = conn.execute("SELECT cash FROM citizens WHERE user_id=?", (str(interaction.user.id),)).fetchone()
    if row["cash"] < somma:
        conn.close()
        await interaction.response.send_message("❌ Contanti insufficienti.", ephemeral=True)
        return
    conn.execute("UPDATE citizens SET cash=cash-? WHERE user_id=?", (somma, str(interaction.user.id)))
    conn.execute("UPDATE citizens SET cash=cash+? WHERE user_id=?", (somma, str(utente.id)))
    conn.commit()
    conn.close()
    await interaction.response.send_message(
        f"✅ Hai pagato **€{somma:,.2f}** in contanti a {utente.mention}."
    )


@bot.tree.command(name="paga-carta", description="Bonifico bancario a un altro utente")
@app_commands.describe(utente="Destinatario", somma="Importo da trasferire")
async def paga_carta(interaction: discord.Interaction, utente: discord.Member, somma: float):
    ensure_citizen(str(interaction.user.id), interaction.user.display_name)
    ensure_citizen(str(utente.id), utente.display_name)
    block = is_blocked(str(interaction.user.id))
    if block:
        await interaction.response.send_message(f"⛔ {block}", ephemeral=True)
        return
    if somma <= 0:
        await interaction.response.send_message("❌ L'importo deve essere positivo.", ephemeral=True)
        return
    if utente.id == interaction.user.id:
        await interaction.response.send_message("❌ Non puoi fare un bonifico a te stesso.", ephemeral=True)
        return
    conn = get_db()
    row = conn.execute("SELECT bank FROM citizens WHERE user_id=?", (str(interaction.user.id),)).fetchone()
    if row["bank"] < somma:
        conn.close()
        await interaction.response.send_message("❌ Fondi insufficienti in banca.", ephemeral=True)
        return
    conn.execute("UPDATE citizens SET bank=bank-? WHERE user_id=?", (somma, str(interaction.user.id)))
    conn.execute("UPDATE citizens SET bank=bank+? WHERE user_id=?", (somma, str(utente.id)))
    conn.commit()
    conn.close()
    await interaction.response.send_message(
        f"✅ Hai trasferito **€{somma:,.2f}** dal tuo conto a {utente.mention}."
    )


@bot.tree.command(name="partita-iva", description="Registra o revoca la partita IVA di un cittadino")
@app_commands.describe(utente="Cittadino", azione="registra o revoca")
@app_commands.choices(azione=[
    app_commands.Choice(name="registra", value="registra"),
    app_commands.Choice(name="revoca", value="revoca"),
])
async def partita_iva(interaction: discord.Interaction, utente: discord.Member, azione: app_commands.Choice[str]):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo gli admin possono usare questo comando.", ephemeral=True)
        return
    ensure_citizen(str(utente.id), utente.display_name)
    valore = 1 if azione.value == "registra" else 0
    conn = get_db()
    conn.execute("UPDATE citizens SET partita_iva=? WHERE user_id=?", (valore, str(utente.id)))
    conn.commit()
    conn.close()
    stato = "registrata" if valore else "revocata"
    await interaction.response.send_message(f"✅ Partita IVA **{stato}** per {utente.mention}.")


# ---------------------------------------------------------------------------
# FORZE DELL'ORDINE E GIUSTIZIA
# ---------------------------------------------------------------------------

@bot.tree.command(name="fdo-scheda", description="Mostra la scheda di un agente delle forze dell'ordine")
@app_commands.describe(utente="Agente FDO")
async def fdo_scheda(interaction: discord.Interaction, utente: discord.Member):
    conn = get_db()
    row = conn.execute("SELECT * FROM fdo WHERE user_id=?", (str(utente.id),)).fetchone()
    conn.close()
    if not row:
        await interaction.response.send_message(f"❌ {utente.mention} non è registrato nelle FDO.", ephemeral=True)
        return
    embed = discord.Embed(title=f"🚔 Scheda Agente FDO — {utente.display_name}", color=discord.Color.dark_blue())
    embed.set_thumbnail(url=utente.display_avatar.url)
    embed.add_field(name="⭐ Grado", value=row["grado"] or "N/D", inline=True)
    embed.add_field(name="🏢 Reparto", value=row["reparto"] or "N/D", inline=True)
    embed.add_field(name="📡 Stato Servizio", value="🟢 **In servizio**" if row["in_servizio"] else "🔴 **Sospeso**", inline=True)
    embed.set_footer(text="⚙️ VERONA ITA RP — Forze dell'Ordine")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="fdo-aggiungi", description="Registra un nuovo agente nelle Forze dell'Ordine")
@app_commands.describe(utente="Agente da aggiungere", grado="Grado/Rango dell'agente", reparto="Reparto di appartenenza")
async def fdo_aggiungi(interaction: discord.Interaction, utente: discord.Member, grado: str, reparto: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo gli admin possono usare questo comando.", ephemeral=True)
        return
    conn = get_db()
    existing = conn.execute("SELECT user_id FROM fdo WHERE user_id=?", (str(utente.id),)).fetchone()
    if existing:
        conn.execute(
            "UPDATE fdo SET grado=?, reparto=?, in_servizio=1 WHERE user_id=?",
            (grado, reparto, str(utente.id))
        )
        conn.commit()
        conn.close()
        embed = discord.Embed(title="🔄 Scheda FDO Aggiornata", color=discord.Color.orange())
        embed.set_thumbnail(url=utente.display_avatar.url)
        embed.add_field(name="👤 Agente", value=utente.mention, inline=True)
        embed.add_field(name="⭐ Grado", value=grado, inline=True)
        embed.add_field(name="🏢 Reparto", value=reparto, inline=True)
        embed.add_field(name="📡 Stato", value="🟢 **In servizio**", inline=False)
        embed.set_footer(text="⚙️ VERONA ITA RP — Forze dell'Ordine")
        await interaction.response.send_message(embed=embed)
    else:
        conn.execute(
            "INSERT INTO fdo (user_id, grado, reparto, in_servizio) VALUES (?, ?, ?, 1)",
            (str(utente.id), grado, reparto)
        )
        conn.commit()
        conn.close()
        embed = discord.Embed(title="🚔 Nuovo Agente FDO Registrato", color=discord.Color.dark_blue())
        embed.set_thumbnail(url=utente.display_avatar.url)
        embed.add_field(name="👤 Agente", value=utente.mention, inline=True)
        embed.add_field(name="⭐ Grado", value=grado, inline=True)
        embed.add_field(name="🏢 Reparto", value=reparto, inline=True)
        embed.add_field(name="📡 Stato", value="🟢 **In servizio**", inline=False)
        embed.set_footer(text="⚙️ VERONA ITA RP — Forze dell'Ordine")
        await interaction.response.send_message(embed=embed)


@bot.tree.command(name="fdo-sospendi", description="Sospendi o riattiva un agente FDO")
@app_commands.describe(utente="Agente FDO da sospendere/riattivare")
async def fdo_sospendi(interaction: discord.Interaction, utente: discord.Member):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo gli admin possono usare questo comando.", ephemeral=True)
        return
    conn = get_db()
    row = conn.execute("SELECT in_servizio FROM fdo WHERE user_id=?", (str(utente.id),)).fetchone()
    if not row:
        conn.execute("INSERT INTO fdo (user_id, in_servizio) VALUES (?, 0)", (str(utente.id),))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"✅ {utente.mention} aggiunto nelle FDO come **sospeso**.")
        return
    nuovo_stato = 0 if row["in_servizio"] else 1
    conn.execute("UPDATE fdo SET in_servizio=? WHERE user_id=?", (nuovo_stato, str(utente.id)))
    conn.commit()
    conn.close()
    stato_str = "🟢 riattivato" if nuovo_stato else "🔴 sospeso"
    await interaction.response.send_message(f"✅ {utente.mention} è ora **{stato_str}** dal servizio.")


@bot.tree.command(name="multa", description="Registra una multa a carico di un cittadino")
@app_commands.describe(utente="Cittadino multato", importo="Importo della multa", motivo="Motivazione")
async def multa(interaction: discord.Interaction, utente: discord.Member, importo: float, motivo: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo gli admin/FDO possono emettere multe.", ephemeral=True)
        return
    ensure_citizen(str(utente.id), utente.display_name)
    if importo <= 0:
        await interaction.response.send_message("❌ L'importo deve essere positivo.", ephemeral=True)
        return
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO multe (user_id, importo, motivo) VALUES (?, ?, ?)",
        (str(utente.id), importo, motivo)
    )
    multa_id = cursor.lastrowid
    conn.commit()
    conn.close()
    embed = discord.Embed(title="🚨 Multa Emessa", color=discord.Color.red())
    embed.add_field(name="👤 Cittadino", value=utente.mention, inline=True)
    embed.add_field(name="🔢 ID Multa", value=f"`#{multa_id}`", inline=True)
    embed.add_field(name="💶 Importo", value=f"**€{importo:,.2f}**", inline=True)
    embed.add_field(name="📝 Motivo", value=motivo, inline=False)
    embed.add_field(name="💡 Come pagare", value=f"Usa `/paga-multa {multa_id}` per saldare la multa.", inline=False)
    embed.set_footer(text="⚙️ VERONA ITA RP — Polizia Municipale")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="paga-multa", description="Paga una multa attiva usando i soldi in banca")
@app_commands.describe(id_multa="ID della multa da pagare")
async def paga_multa(interaction: discord.Interaction, id_multa: int):
    ensure_citizen(str(interaction.user.id), interaction.user.display_name)
    block = is_blocked(str(interaction.user.id))
    if block:
        await interaction.response.send_message(f"⛔ {block}", ephemeral=True)
        return
    conn = get_db()
    multa_row = conn.execute(
        "SELECT * FROM multe WHERE id=? AND user_id=? AND pagata=0",
        (id_multa, str(interaction.user.id))
    ).fetchone()
    if not multa_row:
        conn.close()
        await interaction.response.send_message("❌ Multa non trovata o già pagata.", ephemeral=True)
        return
    cit = conn.execute("SELECT bank FROM citizens WHERE user_id=?", (str(interaction.user.id),)).fetchone()
    if cit["bank"] < multa_row["importo"]:
        conn.close()
        await interaction.response.send_message("❌ Fondi insufficienti in banca.", ephemeral=True)
        return
    conn.execute("UPDATE citizens SET bank=bank-? WHERE user_id=?", (multa_row["importo"], str(interaction.user.id)))
    conn.execute("UPDATE multe SET pagata=1 WHERE id=?", (id_multa,))
    conn.commit()
    conn.close()
    await interaction.response.send_message(
        f"✅ Multa #{id_multa} da **€{multa_row['importo']:,.2f}** pagata con successo."
    )


@bot.tree.command(name="storico-multe", description="Mostra lo storico multe di un utente")
@app_commands.describe(utente="Cittadino (lascia vuoto per il tuo storico)")
async def storico_multe(interaction: discord.Interaction, utente: discord.Member = None):
    target = utente or interaction.user
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM multe WHERE user_id=? ORDER BY id DESC",
        (str(target.id),)
    ).fetchall()
    conn.close()
    if not rows:
        await interaction.response.send_message(f"✅ {target.display_name} non ha multe registrate.")
        return
    embed = discord.Embed(title=f"📋 Storico Multe — {target.display_name}", color=discord.Color.orange())
    embed.set_thumbnail(url=target.display_avatar.url)
    for r in rows[:15]:
        stato = "✅ Pagata" if r["pagata"] else "❌ Da pagare"
        embed.add_field(
            name=f"{'✅' if r['pagata'] else '🚨'} Multa #{r['id']} — €{r['importo']:,.2f}",
            value=f"📌 **Stato:** {stato}\n📝 **Motivo:** {r['motivo']}\n📅 **Data:** {r['data']}",
            inline=False
        )
    embed.set_footer(text="⚙️ VERONA ITA RP — Registro Multe")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="storico-arresti", description="Mostra la fedina penale di un cittadino")
@app_commands.describe(utente="Cittadino")
async def storico_arresti(interaction: discord.Interaction, utente: discord.Member = None):
    target = utente or interaction.user
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM arresti WHERE user_id=? ORDER BY id DESC",
        (str(target.id),)
    ).fetchall()
    conn.close()
    if not rows:
        await interaction.response.send_message(f"✅ {target.display_name} ha la fedina penale pulita.")
        return
    embed = discord.Embed(title=f"⚖️ Fedina Penale — {target.display_name}", color=discord.Color.dark_red())
    for r in rows[:15]:
        embed.add_field(
            name=f"Arresto #{r['id']} — {r['data']}",
            value=r["motivo"],
            inline=False
        )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="perma-jail", description="Metti o rimuovi un utente dall'isolamento permanente")
@app_commands.describe(utente="Cittadino", motivo="Motivo del perma jail (lascia vuoto per rimuovere)")
async def perma_jail(interaction: discord.Interaction, utente: discord.Member, motivo: str = ""):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo gli admin possono usare questo comando.", ephemeral=True)
        return
    ensure_citizen(str(utente.id), utente.display_name)
    conn = get_db()
    row = conn.execute("SELECT perma_jail FROM citizens WHERE user_id=?", (str(utente.id),)).fetchone()
    if row["perma_jail"]:
        conn.execute(
            "UPDATE citizens SET perma_jail=0, perma_jail_motivo='' WHERE user_id=?",
            (str(utente.id),)
        )
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"✅ {utente.mention} è stato rilasciato dal Perma Jail.")
    else:
        if not motivo:
            conn.close()
            await interaction.response.send_message("❌ Specifica un motivo per il Perma Jail.", ephemeral=True)
            return
        conn.execute(
            "UPDATE citizens SET perma_jail=1, perma_jail_motivo=? WHERE user_id=?",
            (motivo, str(utente.id))
        )
        conn.execute(
            "INSERT INTO arresti (user_id, motivo) VALUES (?, ?)",
            (str(utente.id), f"[PERMA JAIL] {motivo}")
        )
        conn.commit()
        conn.close()
        embed = discord.Embed(title="🔒 Perma Jail", color=discord.Color.dark_gray())
        embed.add_field(name="Cittadino", value=utente.mention, inline=True)
        embed.add_field(name="Motivo", value=motivo, inline=False)
        await interaction.response.send_message(embed=embed)


@bot.tree.command(name="perma-death", description="Applica o rimuovi il Perma Death di un personaggio")
@app_commands.describe(utente="Cittadino")
async def perma_death(interaction: discord.Interaction, utente: discord.Member):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo gli admin possono usare questo comando.", ephemeral=True)
        return
    ensure_citizen(str(utente.id), utente.display_name)
    conn = get_db()
    row = conn.execute("SELECT perma_death FROM citizens WHERE user_id=?", (str(utente.id),)).fetchone()
    nuovo = 0 if row["perma_death"] else 1
    conn.execute("UPDATE citizens SET perma_death=? WHERE user_id=?", (nuovo, str(utente.id)))
    conn.commit()
    conn.close()
    if nuovo:
        embed = discord.Embed(title="💀 Perma Death Applicato", color=discord.Color.dark_gray())
        embed.description = f"{utente.mention} ha subito la **morte permanente del personaggio**. Tutti i comandi sono bloccati."
        await interaction.response.send_message(embed=embed)
    else:
        await interaction.response.send_message(f"✅ Perma Death rimosso per {utente.mention}.")


# ---------------------------------------------------------------------------
# VEICOLI E MOTORIZZAZIONE
# ---------------------------------------------------------------------------

@bot.tree.command(name="immatricolazione", description="Registra un veicolo a nome di un cittadino")
@app_commands.describe(utente="Proprietario", veicolo="Modello del veicolo", targa="Numero di targa")
async def immatricolazione(interaction: discord.Interaction, utente: discord.Member, veicolo: str, targa: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo gli admin/motorizzazione possono usare questo comando.", ephemeral=True)
        return
    ensure_citizen(str(utente.id), utente.display_name)
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO veicoli (user_id, veicolo, targa) VALUES (?, ?, ?)",
        (str(utente.id), veicolo, targa.upper())
    )
    vid = cursor.lastrowid
    conn.commit()
    conn.close()
    embed = discord.Embed(title="🚗 Veicolo Immatricolato", color=discord.Color.green())
    embed.add_field(name="ID Veicolo", value=str(vid), inline=True)
    embed.add_field(name="Proprietario", value=utente.mention, inline=True)
    embed.add_field(name="Veicolo", value=veicolo, inline=True)
    embed.add_field(name="Targa", value=targa.upper(), inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="sequestro-veicolo", description="Sequestra il veicolo di un cittadino")
@app_commands.describe(utente="Proprietario", veicolo="Modello del veicolo", motivo="Motivo del sequestro")
async def sequestro_veicolo(interaction: discord.Interaction, utente: discord.Member, veicolo: str, motivo: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo gli admin/FDO possono usare questo comando.", ephemeral=True)
        return
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM veicoli WHERE user_id=? AND veicolo=? AND sequestrato=0",
        (str(utente.id), veicolo)
    ).fetchone()
    if not row:
        conn.close()
        await interaction.response.send_message(f"❌ Nessun veicolo '{veicolo}' trovato per {utente.mention} o già sequestrato.", ephemeral=True)
        return
    conn.execute(
        "UPDATE veicoli SET sequestrato=1, motivo_seq=? WHERE id=?",
        (motivo, row["id"])
    )
    conn.commit()
    conn.close()
    embed = discord.Embed(title="🚨 Veicolo Sequestrato", color=discord.Color.red())
    embed.add_field(name="Proprietario", value=utente.mention, inline=True)
    embed.add_field(name="Veicolo", value=veicolo, inline=True)
    embed.add_field(name="Motivo", value=motivo, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="rilascia-veicolo", description="Rilascia un veicolo sequestrato")
@app_commands.describe(id_veicolo="ID del veicolo da rilasciare")
async def rilascia_veicolo(interaction: discord.Interaction, id_veicolo: int):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo gli admin/FDO possono usare questo comando.", ephemeral=True)
        return
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM veicoli WHERE id=? AND sequestrato=1",
        (id_veicolo,)
    ).fetchone()
    if not row:
        conn.close()
        await interaction.response.send_message("❌ Veicolo non trovato o non sequestrato.", ephemeral=True)
        return
    conn.execute("UPDATE veicoli SET sequestrato=0, motivo_seq='' WHERE id=?", (id_veicolo,))
    conn.commit()
    conn.close()
    await interaction.response.send_message(
        f"✅ Veicolo **{row['veicolo']}** (ID: {id_veicolo}) rilasciato dal deposito."
    )


@bot.tree.command(name="patente", description="Rilascia o revoca la patente di guida a un cittadino")
@app_commands.describe(utente="Cittadino", azione="rilascia o revoca")
@app_commands.choices(azione=[
    app_commands.Choice(name="rilascia", value="rilascia"),
    app_commands.Choice(name="revoca", value="revoca"),
])
async def patente(interaction: discord.Interaction, utente: discord.Member, azione: app_commands.Choice[str]):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo gli admin possono usare questo comando.", ephemeral=True)
        return
    ensure_citizen(str(utente.id), utente.display_name)
    valore = 1 if azione.value == "rilascia" else 0
    conn = get_db()
    conn.execute("UPDATE citizens SET patente=? WHERE user_id=?", (valore, str(utente.id)))
    conn.commit()
    conn.close()
    stato = "rilasciata" if valore else "revocata"
    await interaction.response.send_message(f"✅ Patente di guida **{stato}** per {utente.mention}.")


# ---------------------------------------------------------------------------
# SISTEMA SANITARIO E ARMI
# ---------------------------------------------------------------------------

@bot.tree.command(name="aggiungi-cartella", description="Crea o aggiorna la cartella clinica di un paziente")
@app_commands.describe(utente="Paziente", note="Patologie e note mediche")
async def aggiungi_cartella(interaction: discord.Interaction, utente: discord.Member, note: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo i medici/admin possono usare questo comando.", ephemeral=True)
        return
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO cartelle (user_id, note) VALUES (?, ?)",
        (str(utente.id), note)
    )
    conn.commit()
    conn.close()
    embed = discord.Embed(title=f"🏥 Cartella Clinica — {utente.display_name}", color=discord.Color.teal())
    embed.add_field(name="Paziente", value=utente.mention, inline=True)
    embed.add_field(name="Note / Patologie", value=note, inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="rimuovi-cartella", description="Elimina la cartella sanitaria di un cittadino")
@app_commands.describe(utente="Paziente")
async def rimuovi_cartella(interaction: discord.Interaction, utente: discord.Member):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo i medici/admin possono usare questo comando.", ephemeral=True)
        return
    conn = get_db()
    result = conn.execute("DELETE FROM cartelle WHERE user_id=?", (str(utente.id),))
    conn.commit()
    conn.close()
    if result.rowcount == 0:
        await interaction.response.send_message(f"❌ Nessuna cartella trovata per {utente.mention}.", ephemeral=True)
    else:
        await interaction.response.send_message(f"✅ Cartella clinica di {utente.mention} eliminata.")


@bot.tree.command(name="porto-darmi", description="Concedi o revoca il porto d'armi a un cittadino")
@app_commands.describe(utente="Cittadino", azione="rilascia o revoca")
@app_commands.choices(azione=[
    app_commands.Choice(name="rilascia", value="rilascia"),
    app_commands.Choice(name="revoca", value="revoca"),
])
async def porto_darmi(interaction: discord.Interaction, utente: discord.Member, azione: app_commands.Choice[str]):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo gli admin possono usare questo comando.", ephemeral=True)
        return
    ensure_citizen(str(utente.id), utente.display_name)
    valore = 1 if azione.value == "rilascia" else 0
    conn = get_db()
    conn.execute("UPDATE citizens SET porto_darmi=? WHERE user_id=?", (valore, str(utente.id)))
    conn.commit()
    conn.close()
    stato = "rilasciato" if valore else "revocato"
    await interaction.response.send_message(f"✅ Porto d'armi **{stato}** per {utente.mention}.")


# ---------------------------------------------------------------------------
# GESTIONE SESSIONI E UTILITY (ADMIN)
# ---------------------------------------------------------------------------

@bot.tree.command(name="modifica-soldi", description="[ADMIN] Modifica i saldi di un utente")
@app_commands.describe(
    utente="Utente target",
    azione="aggiungi, rimuovi o imposta",
    tipo="contanti o banca",
    quantita="Importo"
)
@app_commands.choices(
    azione=[
        app_commands.Choice(name="aggiungi", value="aggiungi"),
        app_commands.Choice(name="rimuovi", value="rimuovi"),
        app_commands.Choice(name="imposta", value="imposta"),
    ],
    tipo=[
        app_commands.Choice(name="contanti", value="cash"),
        app_commands.Choice(name="banca", value="bank"),
    ]
)
async def modifica_soldi(
    interaction: discord.Interaction,
    utente: discord.Member,
    azione: app_commands.Choice[str],
    tipo: app_commands.Choice[str],
    quantita: float
):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo gli admin possono usare questo comando.", ephemeral=True)
        return
    ensure_citizen(str(utente.id), utente.display_name)
    if quantita < 0:
        await interaction.response.send_message("❌ La quantità non può essere negativa.", ephemeral=True)
        return
    campo = tipo.value
    conn = get_db()
    if azione.value == "aggiungi":
        conn.execute(f"UPDATE citizens SET {campo}={campo}+? WHERE user_id=?", (quantita, str(utente.id)))
        desc = f"aggiunti €{quantita:,.2f}"
    elif azione.value == "rimuovi":
        row = conn.execute(f"SELECT {campo} FROM citizens WHERE user_id=?", (str(utente.id),)).fetchone()
        new_val = max(0.0, row[campo] - quantita)
        conn.execute(f"UPDATE citizens SET {campo}=? WHERE user_id=?", (new_val, str(utente.id)))
        desc = f"rimossi €{quantita:,.2f}"
    else:
        conn.execute(f"UPDATE citizens SET {campo}=? WHERE user_id=?", (quantita, str(utente.id)))
        desc = f"impostati a €{quantita:,.2f}"
    conn.commit()
    conn.close()
    tipo_str = "contanti" if campo == "cash" else "banca"
    await interaction.response.send_message(
        f"✅ {utente.mention}: {desc} nei **{tipo_str}**."
    )


@bot.tree.command(name="ssu", description="Annuncia l'inizio della sessione di Roleplay")
async def ssu(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo gli admin possono usare questo comando.", ephemeral=True)
        return
    old = session_messages.pop(interaction.channel_id, None)
    if old:
        try:
            await old.delete()
        except Exception:
            pass
    embed = discord.Embed(
        title="🟢 SERVER ON — Sessione RP Avviata",
        description=(
            "🎮 **VERONA ITA RP** è ora **ONLINE**!\n\n"
            "🏙️ La sessione di Roleplay è ufficialmente **iniziata**.\n"
            "🎭 Rimanete in personaggio e rispettate le regole del server.\n\n"
            "👥 Buon divertimento a tutti i cittadini di Verona!"
        ),
        color=discord.Color.green()
    )
    embed.set_footer(text="⚙️ VERONA ITA RP — Server Ufficiale")
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    session_messages[interaction.channel_id] = msg


@bot.tree.command(name="ssd", description="Annuncia la chiusura della sessione di Roleplay")
async def ssd(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Solo gli admin possono usare questo comando.", ephemeral=True)
        return
    old = session_messages.pop(interaction.channel_id, None)
    if old:
        try:
            await old.delete()
        except Exception:
            pass
    embed = discord.Embed(
        title="🔴 SERVER SHUT DOWN — Sessione RP Chiusa",
        description=(
            "🛑 **VERONA ITA RP** è ora **OFFLINE**.\n\n"
            "🌙 La sessione di Roleplay è ufficialmente **terminata**.\n"
            "🙏 Grazie a tutti per aver partecipato.\n\n"
            "📅 Ci vediamo alla prossima sessione!"
        ),
        color=discord.Color.red()
    )
    embed.set_footer(text="⚙️ VERONA ITA RP — Server Ufficiale")
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    session_messages[interaction.channel_id] = msg


class VoteView(ui.View):
    def __init__(self, titolo: str):
        super().__init__(timeout=None)
        self.titolo = titolo
        # { user_id: display_name }
        self.voters: dict[int, str] = {}

        btn = ui.Button(
            label="🗳️  Vota",
            style=discord.ButtonStyle.primary,
            custom_id="vote_main"
        )

        async def vote_callback(btn_interaction: discord.Interaction):
            uid = btn_interaction.user.id
            name = btn_interaction.user.display_name
            if uid in self.voters:
                self.voters.pop(uid)
                await btn_interaction.response.edit_message(embed=self._build_embed())
                await btn_interaction.followup.send("🗑️ Hai rimosso il tuo voto.", ephemeral=True)
            else:
                self.voters[uid] = name
                await btn_interaction.response.edit_message(embed=self._build_embed())
                await btn_interaction.followup.send("✅ Voto registrato!", ephemeral=True)

        btn.callback = vote_callback
        self.add_item(btn)

    def _build_embed(self) -> discord.Embed:
        count = len(self.voters)
        nomi = "\n".join(f"• {n}" for n in self.voters.values()) if self.voters else "*Nessun voto ancora*"
        embed = discord.Embed(
            title=f"📊 {self.titolo}",
            description=(
                "🗳️ Clicca **Vota** per partecipare.\n"
                "Clicca di nuovo per **rimuovere** il tuo voto.\n"
            ),
            color=discord.Color.purple()
        )
        embed.add_field(name=f"👥 Votanti: {count}", value=nomi, inline=False)
        embed.set_footer(text="⚙️ VERONA ITA RP — Votazione Ufficiale")
        return embed


@bot.tree.command(name="votazione", description="Crea una votazione RP con contatore dei partecipanti")
@app_commands.describe(titolo="Titolo o oggetto della votazione")
async def votazione(interaction: discord.Interaction, titolo: str):
    view = VoteView(titolo)
    await interaction.response.send_message(embed=view._build_embed(), view=view)


# ---------------------------------------------------------------------------
# AVVIO
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "Token Discord non trovato! Imposta la variabile d'ambiente DISCORD_TOKEN."
        )
    init_db()
    keep_alive()
    bot.run(TOKEN)
