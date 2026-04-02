import discord
from discord.ext import commands
from discord import app_commands
import logging
import os
import re
import secrets
import asyncio

from database import Database
from scheduler import encontrar_horarios_comuns, formatar_disponibilidades

logger = logging.getLogger(__name__)

# Instâncias globais — compartilhadas entre as classes e funçõe
db: Database = None
BASE_URL: str = ""

def extrair_players(guild: discord.Guild, texto: str) -> list[str]:
    p_ids = []
    reais = re.findall(r"<@!?(\d+)>", texto)
    if reais:
        p_ids.extend(reais)
        texto = re.sub(r"<@!?\d+>", " ", texto)
        
    nomes = re.findall(r"@([^\s]+)", texto)
    for nome in nomes:
        nome_lower = nome.lower()
        for m in guild.members:
            if m.name.lower().startswith(nome_lower) or (m.display_name and m.display_name.lower().startswith(nome_lower)):
                p_ids.append(str(m.id))
                break
    return p_ids

# ─── CLASSES DE INTERFACE (MODALS, VIEWS, SELECTS) ───

class RodadaModal(discord.ui.Modal, title="Criar Nova Rodada"):
    nome = discord.ui.TextInput(label="Nome da rodada", placeholder="Ex: Rodada 1")
    data_ini = discord.ui.TextInput(label="Data Início", placeholder="Ex: 30/03")
    data_fim = discord.ui.TextInput(label="Data Fim", placeholder="Ex: 05/04")

    async def on_submit(self, interaction: discord.Interaction):
        rodada_id = db.criar_rodada(self.nome.value, str(interaction.guild_id), self.data_ini.value, self.data_fim.value)
        await interaction.response.send_message(
            f"🏆 **Rodada '{self.nome.value}' criada!** (ID: `{rodada_id}`)\n"
            f"📅 Período: **{self.data_ini.value}** até **{self.data_fim.value}**\n\n"
            f"Retorne ao Painel e adicione Mesas a essa rodada.",
            ephemeral=True
        )

class SeletorRodadaCriacaoSelect(discord.ui.Select):
    def __init__(self, rodadas, bot_instance):
        self.bot_instance = bot_instance
        options = []
        for r in rodadas:
            options.append(discord.SelectOption(
                label=f"Rodada: {r['nome']}", 
                description=f"ID {r['id']} | {r['data_ini']} a {r['data_fim']}", 
                value=str(r['id'])
            ))
        super().__init__(placeholder="Selecione a rodada para esta mesa...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            rodada_id = int(self.values[0])
            rodada = db.get_rodada(rodada_id)
            
            if not rodada:
                await interaction.followup.send("❌ Erro: Rodada não encontrada no banco de dados.", ephemeral=True)
                return

            mesas = db.get_mesas_rodada(rodada_id)
            proxima_num = len(mesas) + 1
            mesa_nome = f"Mesa {proxima_num}"

            await interaction.followup.send(
                f"🤝 **Criando {mesa_nome}** em **{rodada['nome']}**\n"
                f"👇 Use o menu abaixo para selecionar os jogadores (2 a 4 players):",
                view=SeletorPlayersView(rodada_id, mesa_nome, self.bot_instance),
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Erro ao selecionar rodada para mesa: {e}")
            await interaction.followup.send(f"❌ Erro interno: {e}", ephemeral=True)

class SeletorRodadaCriacaoView(discord.ui.View):
    def __init__(self, rodadas, bot_instance):
        super().__init__(timeout=None)
        self.add_item(SeletorRodadaCriacaoSelect(rodadas, bot_instance))

class SeletorPlayersView(discord.ui.View):
    def __init__(self, rodada_id: int, mesa_nome: str, bot_instance):
        super().__init__(timeout=None)
        self.rodada_id = rodada_id
        self.mesa_nome = mesa_nome
        self.bot_instance = bot_instance
        
        self.user_select = discord.ui.MemberSelect(
            placeholder="Selecione os jogadores da mesa...",
            min_values=2,
            max_values=4
        )
        self.user_select.callback = self.select_callback
        self.add_item(self.user_select)

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            members = self.user_select.values
            ids = [str(m.id) for m in members]

            m_id = db.criar_mesa(self.rodada_id, self.mesa_nome, ids)
            rodada = db.get_rodada(self.rodada_id)
            
            base_msg = (
                f"⚔️ **Magic Tournament — {rodada['nome']}**\n\n"
                f"Você foi escalado para a **{self.mesa_nome}**!\n"
                f"Adversários: {', '.join(m.display_name for m in members)}\n\n"
                f"📅 Período: **{rodada['data_ini']}** até **{rodada['data_fim']}**\n\n"
                f"Escolha seus horários no calendário:\n"
            )

            sucesso, falha = [], []
            for m in members:
                token = db.criar_token(str(m.id), m_id, self.rodada_id)
                link = f"{BASE_URL}/disponibilidade/{token}"
                try:
                    await m.send(f"{base_msg}🔗 {link}\n\n_O link é pessoal, não compartilhe._")
                    sucesso.append(m.display_name)
                except:
                    falha.append(m.display_name)

            resumo = f"✅ Mesa **{self.mesa_nome}** criada com sucesso!\n"
            if sucesso: resumo += f"📨 Links enviados: {', '.join(sucesso)}\n"
            if falha: resumo += f"⚠️ Falha na DM (privado fechado): {', '.join(falha)}"
            
            await interaction.followup.send(resumo, ephemeral=True)
        except Exception as e:
            logger.error(f"Erro ao salvar jogadores da mesa: {e}")
            await interaction.followup.send(f"❌ Erro ao criar mesa: {e}", ephemeral=True)

class SeletorRodadaSelect(discord.ui.Select):
    def __init__(self, rodadas):
        options = [
            discord.SelectOption(label=r['nome'], value=str(r['id']), description=f"ID: {r['id']}")
            for r in rodadas
        ]
        super().__init__(placeholder="Escolha a rodada...", options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rodada_id = int(self.values[0])
        embed = construir_embed_status(rodada_id, interaction.guild)
        if not embed:
            await interaction.followup.send("❌ Erro ao gerar status da rodada.", ephemeral=True)
            return
        await interaction.followup.send(embed=embed, view=RodadaStatusView(rodada_id), ephemeral=True)

class SeletorRodadaView(discord.ui.View):
    def __init__(self, rodadas):
        super().__init__(timeout=None)
        self.add_item(SeletorRodadaSelect(rodadas))

class RodadaStatusView(discord.ui.View):
    def __init__(self, rodada_id: int):
        super().__init__(timeout=None)
        self.rodada_id = rodada_id

    @discord.ui.button(label="🔄 Atualizar Agora", style=discord.ButtonStyle.primary)
    async def btn_atualizar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        embed = construir_embed_status(self.rodada_id, interaction.guild)
        if embed:
            await interaction.edit_original_response(embed=embed)

    @discord.ui.button(label="🔔 Cutucar Atrasados", style=discord.ButtonStyle.secondary)
    async def btn_notificar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        mesas = db.get_mesas_rodada(self.rodada_id)
        tokens = db.get_tokens_rodada(self.rodada_id)
        
        count = 0
        for t in tokens:
            if t["usado"] == 0:
                user = interaction.guild.get_member(int(t["discord_id"]))
                if user:
                    try:
                        link = f"{BASE_URL}/disponibilidade/{t['token']}"
                        await user.send(f"👋 Ei! O tempo está passando. Não esqueça de marcar seus horários para o torneio:\n🔗 {link}")
                        count += 1
                    except: pass
        await interaction.followup.send(f"✅ {count} jogadores notificados!", ephemeral=True)

class ConfirmarHorarioView(discord.ui.View):
    def __init__(self, bot, mesa_id, opcoes, rodada_nome, mesa_nome, players):
        super().__init__(timeout=None)
        self.bot = bot
        self.mesa_id = mesa_id
        self.rodada_nome = rodada_nome
        self.mesa_nome = mesa_nome
        self.players = players
        
        for i, opt in enumerate(opcoes):
            btn = discord.ui.Button(label=f"Agendar: {opt}", style=discord.ButtonStyle.success, custom_id=f"conf_{mesa_id}_{i}")
            btn.callback = self.criar_callback(opt)
            self.add_item(btn)

    def criar_callback(self, horario):
        async def callback(interaction: discord.Interaction):
            db.marcar_confirmada(self.mesa_id, horario)
            await interaction.response.edit_message(content=f"✅ Jogo marcado para **{horario}**! Jogadores avisados.", view=None)
            
            guild = interaction.guild
            for pid in self.players:
                member = guild.get_member(int(pid))
                if member:
                    try:
                        await member.send(f"🎉 **{self.mesa_nome} — Confirmada!**\n📅 Horário: **{horario}**\nBoa sorte!")
                    except: pass
        return callback

class RetryMesaView(discord.ui.View):
    def __init__(self, bot, mesa_id, rodada_nome, mesa_nome, players):
        super().__init__(timeout=None)
        self.bot = bot
        self.mesa_id = mesa_id
        self.rodada_nome = rodada_nome
        self.mesa_nome = mesa_nome
        self.players = players

    @discord.ui.button(label="🔄 Revotar Mesa", style=discord.ButtonStyle.danger)
    async def btn_retry(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        db.limpar_disponibilidades_mesa(self.mesa_id)
        db.resetar_tokens_mesa(self.mesa_id)
        
        mesa = db.get_mesa(self.mesa_id)
        rodada = db.get_rodada(mesa["rodada_id"])
        
        for pid in self.players:
            member = interaction.guild.get_member(int(pid))
            if member:
                token = db.criar_token(pid, self.mesa_id, mesa["rodada_id"])
                link = f"{BASE_URL}/disponibilidade/{token}"
                try:
                    await member.send(f"🔄 **Nova Votação — {self.mesa_nome}**\nOs horários anteriores não bateram. Tente novamente:\n🔗 {link}")
                except: pass
        
        button.disabled = True
        button.label = "✅ Revotação Enviada"
        await interaction.message.edit(view=self)

class PainelView(discord.ui.View):
    def __init__(self, bot_instance):
        super().__init__(timeout=None)
        self.bot = bot_instance

    @discord.ui.button(label="🏆 Criar Rodada", style=discord.ButtonStyle.primary, row=0)
    async def btn_rodada(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RodadaModal())

    @discord.ui.button(label="🎴 Criar Mesa", style=discord.ButtonStyle.success, row=0)
    async def btn_mesa(self, interaction: discord.Interaction, button: discord.ui.Button):
        rodadas = db.get_todas_rodadas()
        if not rodadas:
            await interaction.response.send_message("❌ Crie uma rodada primeiro!", ephemeral=True)
            return
        await interaction.response.send_message("Selecione a rodada:", view=SeletorRodadaCriacaoView(rodadas, self.bot), ephemeral=True)

    @discord.ui.button(label="📊 Status Dinâmico", style=discord.ButtonStyle.secondary, row=0)
    async def btn_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        rodadas = db.get_todas_rodadas()
        if not rodadas:
            await interaction.response.send_message("❌ Nenhuma rodada ativa.", ephemeral=True)
            return
        await interaction.response.send_message("Selecione a rodada:", view=SeletorRodadaView(rodadas), ephemeral=True)

    @discord.ui.button(label="☢️ NUCLEAR RESET", style=discord.ButtonStyle.danger, row=1)
    async def btn_reset(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("🚫 Apenas admins.", ephemeral=True)
            return
        db.resetar_banco()
        await interaction.response.send_message("💥 Banco de dados resetado com sucesso!", ephemeral=True)

# ─── FUNÇÕES AUXILIARES ───

def construir_embed_status(rodada_id: int, guild: discord.Guild) -> discord.Embed | None:
    r = db.get_rodada(rodada_id)
    if not r: return None
    mesas = db.get_mesas_rodada(rodada_id)
    tokens_db = db.get_tokens_rodada(rodada_id)
    
    embed = discord.Embed(title=f"📊 Status: {r['nome']}", color=0x3498db)
    for m in mesas:
        players = db.get_players_mesa(m["id"])
        status = []
        for pid in players:
            member = guild.get_member(int(pid))
            name = member.display_name if member else pid
            # Verifica se o player já votou olhando se o token dele foi usado
            votou = any(t for t in tokens_db if t["mesa_id"] == m["id"] and t["discord_id"] == str(pid) and t["usado"] == 1)
            status.append(f"{'✅' if votou else '⏳'} {name}")
        
        valor = "\n".join(status) if status else "Sem jogadores"
        res = "🔒 Marcada" if m["confirmada"] else "⏳ Aberta"
        if m["horario"]: res += f" ({m['horario']})"
        embed.add_field(name=f"{m['nome']} — {res}", value=valor, inline=False)
    return embed

async def verificar_mesa(bot: commands.Bot, mesa_id: int):
    players = db.get_players_mesa(mesa_id)
    disponibilidades = db.get_disponibilidades_mesa(mesa_id)
    if len(disponibilidades) < len(players): return

    mesa = db.get_mesa(mesa_id)
    rodada = db.get_rodada(mesa["rodada_id"])
    opcoes = encontrar_horarios_comuns(disponibilidades, limite=3)
    
    guild = bot.guilds[0] if bot.guilds else None
    if not guild: return
    
    # Enviar para o admin
    async for member in guild.fetch_members(limit=200):
        if member.guild_permissions.administrator and not member.bot:
            if opcoes:
                view = ConfirmarHorarioView(bot, mesa_id, opcoes, rodada["nome"], mesa["nome"], players)
                await member.send(f"🔔 Mesa **{mesa['nome']}** pronta! Escolha o horário:", view=view)
            else:
                view = RetryMesaView(bot, mesa_id, rodada["nome"], mesa["nome"], players)
                await member.send(f"⚠️ Mesa **{mesa['nome']}** sem match de horários.", view=view)
            break

# ─── SETUP DO BOT ───

def create_bot(database: Database, base_url: str) -> commands.Bot:
    global db, BASE_URL
    db = database
    BASE_URL = base_url.rstrip("/")

    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        logger.info(f"Bot logado como {bot.user}")
        await bot.tree.sync()

    @bot.tree.command(name="painel", description="Abre o painel administrativo do torneio")
    async def painel(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("🚫 Apenas administradores.", ephemeral=True)
            return
        await interaction.response.send_message("🛠️ **Painel de Controle Spell Organizer**", view=PainelView(bot))

    return bot
