import discord
from discord.ext import commands
from discord import app_commands
import logging
import os
import re

from database import Database
from scheduler import encontrar_horarios_comuns, formatar_disponibilidades

logger = logging.getLogger(__name__)

# Instância global — compartilhada com main.py
db: Database = None
BASE_URL: str = ""


def create_bot(database: Database, base_url: str) -> commands.Bot:
    global db, BASE_URL
    db = database
    BASE_URL = base_url.rstrip("/")

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

    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True

    bot = commands.Bot(command_prefix="!", intents=intents)

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

    class MesaModal(discord.ui.Modal, title="Criar Nova Mesa"):
        rodada_id = discord.ui.TextInput(label="ID da Rodada", placeholder="Ex: 1", max_length=5)
        nome = discord.ui.TextInput(label="Nome da Mesa", placeholder="Ex: Mesa 1")
        players = discord.ui.TextInput(label="Jogadores (Marque com @)", style=discord.TextStyle.paragraph, placeholder="@Player1 @Player2")

        async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)

            player_ids = extrair_players(interaction.guild, self.players.value)
            if len(player_ids) < 2:
                await interaction.followup.send(f"❌ Encontrei menos de 2 jogadores no servidor usando os nomes informados ({self.players.value}).")
                return

            try:
                r_id = int(self.rodada_id.value)
            except ValueError:
                await interaction.followup.send("❌ ID da rodada deve ser um número inteiro.")
                return

            rodada = db.get_rodada(r_id)
            if not rodada:
                await interaction.followup.send(f"❌ Rodada `{r_id}` não encontrada.")
                return

            mesa_id = db.criar_mesa(r_id, self.nome.value, player_ids)

            notificados, falhas = [], []
            for pid in player_ids:
                member = interaction.guild.get_member(int(pid))
                if not member:
                    falhas.append(pid)
                    continue

                token = db.criar_token(pid, mesa_id, r_id)
                link = f"{BASE_URL}/disponibilidade/{token}"

                outros = [
                    interaction.guild.get_member(int(p)).display_name
                    for p in player_ids
                    if p != pid and interaction.guild.get_member(int(p))
                ]

                try:
                    await member.send(
                        f"⚔️ **Magic Tournament — {rodada['nome']}**\n\n"
                        f"Você foi sorteado para a **{self.nome.value}** junto com: **{', '.join(outros)}**\n\n"
                        f"📅 A rodada vai de **{rodada['data_ini']}** até **{rodada['data_fim']}**\n\n"
                        f"Marque seus horários disponíveis clicando no link abaixo:\n"
                        f"🔗 {link}\n\n"
                        f"_O link é pessoal, não compartilhe com ninguém._"
                    )
                    notificados.append(member.display_name)
                    logger.info(f"DM enviada: player={pid} mesa={mesa_id} token={token}")
                except discord.Forbidden:
                    falhas.append(member.display_name)

            msg = f"✅ **{self.nome.value}** criada na Rodada `{r_id}`!\n"
            if notificados:
                msg += f"📨 DM enviada para: {', '.join(notificados)}\n"
            if falhas:
                msg += f"⚠️ Falha ao enviar DM para: {', '.join(str(f) for f in falhas)} (privacidade bloqueada)"

            await interaction.followup.send(msg)

    def construir_embed_status(rodada_id: int, guild: discord.Guild) -> discord.Embed | None:
        r = db.get_rodada(rodada_id)
        if not r: return None
        mesas = db.get_mesas_rodada(rodada_id)
        tokens_db = db.get_tokens_rodada(rodada_id)

        embed = discord.Embed(
            title=f"📊 Status Administrativo: {r['nome']}", 
            description=f"📅 **Período:** {r['data_ini']} até {r['data_fim']}\n_Monitore os votos caindo em tempo real ou notifique os atrasados com os botões abaixo._",
            color=0x2b2d31
        )
        
        for m in mesas:
            players = db.get_players_mesa(m["id"])
            status_txt = f"🔒 Confirmada ({m['horario']})" if m["confirmada"] else "⏳ Aguardando Votos"
            
            linhas = []
            for pid in players:
                membro = guild.get_member(int(pid)) if guild else None
                nome = membro.display_name if membro else f"<@{pid}>"
                
                usou = False
                for t in tokens_db:
                    if t["mesa_id"] == m["id"] and t["discord_id"] == str(pid) and t["usado"] == 1:
                        usou = True
                        break
                
                icone = "✅" if usou else "❌"
                linhas.append(f"{icone} {nome}")
                
            texto_players = "\n".join(linhas) if linhas else "Nenhum jogador."
            embed.add_field(name=f"🃏 {m['nome']} — {status_txt}", value=texto_players, inline=False)
            
        return embed

    class RodadaStatusView(discord.ui.View):
        def __init__(self, rodada_id: int):
            super().__init__(timeout=None)
            self.rodada_id = rodada_id

        @discord.ui.button(label="🔄 Atualizar Agora", style=discord.ButtonStyle.secondary)
        async def btn_atualizar(self, interaction: discord.Interaction, button: discord.ui.Button):
            embed = construir_embed_status(self.rodada_id, interaction.guild)
            if embed:
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                await interaction.response.send_message("Rodada não encontrada.", ephemeral=True)

        @discord.ui.button(label="🔔 Cutucar Atrasados", style=discord.ButtonStyle.primary)
        async def btn_cobrar(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.defer(ephemeral=True)
            tokens = db.get_tokens_rodada(self.rodada_id)
            r = db.get_rodada(self.rodada_id)
            cobrancas = 0
            
            for t in tokens:
                if t["usado"] == 0:
                    membro = interaction.guild.get_member(int(t["discord_id"])) if interaction.guild else None
                    if membro:
                        try:
                            mesa = db.get_mesa(t["mesa_id"])
                            url = f"{BASE_URL}/disponibilidade/{t['token']}"
                            embed = discord.Embed(
                                title="🔔 Chamada da Organização!",
                                description=f"O prazo está correndo! Falta você preencher sua disponibilidade para proteger a **{mesa['nome']}** da sua **{r['nome']}**.",
                                color=0xFF0000
                            )
                            embed.add_field(name="Link Direto", value=url)
                            await membro.send(embed=embed)
                            cobrancas += 1
                        except discord.Forbidden:
                            pass
                            
            if cobrancas > 0:
                await interaction.followup.send(f"✅ **Sucesso:** Enviei links de cobrança no privado de {cobrancas} jogador(es) atrasados(as)!", ephemeral=True)
            else:
                await interaction.followup.send("Nenhum jogador pendente de votos nesta rodada! 🎉", ephemeral=True)

    class SeletorRodadaSelect(discord.ui.Select):
        def __init__(self, rodadas):
            options = []
            for r in rodadas:
                options.append(discord.SelectOption(label=f"ID {r['id']}: {r['nome']}", description=f"{r['data_ini']} a {r['data_fim']}", value=str(r['id'])))
            super().__init__(placeholder="Selecione a rodada para monitorar...", options=options)

        async def callback(self, interaction: discord.Interaction):
            rodada_id = int(self.values[0])
            embed = construir_embed_status(rodada_id, interaction.guild)
            if not embed:
                await interaction.response.send_message("Erro ao carregar os dados desta rodada.", ephemeral=True)
                return
            await interaction.response.edit_message(content=None, embed=embed, view=RodadaStatusView(rodada_id))

    class SeletorRodadaView(discord.ui.View):
        def __init__(self, rodadas):
            super().__init__(timeout=None)
            self.add_item(SeletorRodadaSelect(rodadas))

    class ApagarRodadaModal(discord.ui.Modal, title="Apagar Rodada"):
        rodada_id = discord.ui.TextInput(label="ID da Rodada", placeholder="Ex: 1", max_length=5)

        async def on_submit(self, interaction: discord.Interaction):
            try:
                r_id = int(self.rodada_id.value)
            except ValueError:
                await interaction.response.send_message("❌ ID deve ser número.", ephemeral=True)
                return

            rodada = db.get_rodada(r_id)
            if not rodada:
                await interaction.response.send_message("❌ Rodada não encontrada.", ephemeral=True)
                return

            db.apagar_rodada(r_id)
            await interaction.response.send_message(f"✅ Rodada `{r_id}` e todas as suas mesas/votos foram apagados!", ephemeral=True)

    class ApagarMesaModal(discord.ui.Modal, title="Apagar Mesa"):
        mesa_id = discord.ui.TextInput(label="ID da Mesa", placeholder="Ex: 1", max_length=5)

        async def on_submit(self, interaction: discord.Interaction):
            try:
                m_id = int(self.mesa_id.value)
            except ValueError:
                await interaction.response.send_message("❌ ID deve ser número.", ephemeral=True)
                return

            mesa = db.get_mesa(m_id)
            if not mesa:
                await interaction.response.send_message("❌ Mesa não encontrada.", ephemeral=True)
                return

            db.apagar_mesa(m_id)
            await interaction.response.send_message(f"✅ Mesa `{m_id}` junto com seus votos foram apagados com sucesso!", ephemeral=True)

    class ResetarModal(discord.ui.Modal, title="PERIGO DELETAR SERVIDOR"):
        confirmacao = discord.ui.TextInput(
            label="Digite APAGAR para confirmar a formatação",
            placeholder="APAGAR",
            max_length=6
        )

        async def on_submit(self, interaction: discord.Interaction):
            if self.confirmacao.value.strip().upper() == "APAGAR":
                db.resetar_banco()
                await interaction.response.send_message("💣 Torneio inteiramente formatado! As próximas mesas assumirão a Rodada N° 1.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Formatação cancelada. A palavra descrita não era idêntica a 'APAGAR'.", ephemeral=True)

    class EditarMesaModal(discord.ui.Modal, title="Editar Mesa"):
        mesa_id_input = discord.ui.TextInput(label="ID da Mesa", placeholder="Ex: 1", max_length=5)

        async def on_submit(self, interaction: discord.Interaction):
            try:
                m_id = int(self.mesa_id_input.value)
            except ValueError:
                await interaction.response.send_message("❌ ID deve ser número.", ephemeral=True)
                return

            mesa = db.get_mesa(m_id)
            if not mesa:
                await interaction.response.send_message("❌ Mesa não encontrada.", ephemeral=True)
                return

            rodada = db.get_rodada(mesa["rodada_id"])
            players = db.get_players_mesa(m_id)

            linhas = []
            for pid in players:
                member = interaction.guild.get_member(int(pid)) if interaction.guild else None
                nome = member.display_name if member else f"<@{pid}>"
                linhas.append(f"• {nome}")

            txt_players = "\n".join(linhas) if linhas else "Nenhum jogador."

            embed = discord.Embed(
                title=f"✏️ Editar {mesa['nome']}",
                description=(
                    f"**Rodada:** {rodada['nome']}\n"
                    f"**Status:** {'🔒 Confirmada' if mesa['confirmada'] else '⏳ Aberta'}\n\n"
                    f"**Jogadores atuais ({len(players)}):**\n{txt_players}"
                ),
                color=0x5865F2
            )

            await interaction.response.send_message(
                embed=embed,
                view=EditarMesaView(m_id, mesa['nome'], mesa['rodada_id']),
                ephemeral=True
            )

    class EditarMesaView(discord.ui.View):
        def __init__(self, mesa_id: int, mesa_nome: str, rodada_id: int):
            super().__init__(timeout=None)
            self.mesa_id = mesa_id
            self.mesa_nome = mesa_nome
            self.rodada_id = rodada_id

        @discord.ui.button(label="➕ Adicionar Jogador", style=discord.ButtonStyle.success)
        async def btn_add(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_message(
                f"👇 Selecione o jogador para adicionar à **{self.mesa_nome}**:",
                view=AdicionarPlayerView(self.mesa_id, self.mesa_nome, self.rodada_id),
                ephemeral=True
            )

        @discord.ui.button(label="➖ Remover Jogador", style=discord.ButtonStyle.danger)
        async def btn_remove(self, interaction: discord.Interaction, button: discord.ui.Button):
            players = db.get_players_mesa(self.mesa_id)
            if not players:
                await interaction.response.send_message("❌ Nenhum jogador na mesa.", ephemeral=True)
                return

            options = []
            for pid in players:
                member = interaction.guild.get_member(int(pid)) if interaction.guild else None
                nome = member.display_name if member else pid
                options.append(discord.SelectOption(label=nome, value=pid))

            await interaction.response.send_message(
                f"👇 Selecione o jogador para remover da **{self.mesa_nome}**:",
                view=RemoverPlayerView(self.mesa_id, self.mesa_nome, options),
                ephemeral=True
            )

    class AdicionarPlayerView(discord.ui.View):
        def __init__(self, mesa_id: int, mesa_nome: str, rodada_id: int):
            super().__init__(timeout=None)
            self.mesa_id = mesa_id
            self.mesa_nome = mesa_nome
            self.rodada_id = rodada_id
            self.select = discord.ui.UserSelect(
                placeholder="Selecione o jogador...",
                min_values=1,
                max_values=1
            )
            self.select.callback = self.select_callback
            self.add_item(self.select)

        async def select_callback(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            member = self.select.values[0]
            pid = str(member.id)

            players = db.get_players_mesa(self.mesa_id)
            if pid in players:
                await interaction.followup.send(f"⚠️ **{member.display_name}** já está nesta mesa.", ephemeral=True)
                return

            db.adicionar_player_mesa(self.mesa_id, pid)

            rodada = db.get_rodada(self.rodada_id)
            token = db.criar_token(pid, self.mesa_id, self.rodada_id)
            link = f"{BASE_URL}/disponibilidade/{token}"

            outros = []
            for p in db.get_players_mesa(self.mesa_id):
                if p != pid:
                    m = interaction.guild.get_member(int(p))
                    if m:
                        outros.append(m.display_name)

            try:
                await member.send(
                    f"⚔️ **Magic Tournament — {rodada['nome']}**\n\n"
                    f"Você foi adicionado à **{self.mesa_nome}** junto com: **{', '.join(outros)}**\n\n"
                    f"📅 A rodada vai de **{rodada['data_ini']}** até **{rodada['data_fim']}**\n\n"
                    f"Marque seus horários disponíveis clicando no link abaixo:\n"
                    f"🔗 {link}\n\n"
                    f"_O link é pessoal, não compartilhe com ninguém._"
                )
                await interaction.followup.send(
                    f"✅ **{member.display_name}** adicionado à **{self.mesa_nome}** e notificado por DM!",
                    ephemeral=True
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    f"✅ **{member.display_name}** adicionado à **{self.mesa_nome}**, mas não foi possível enviar DM (privacidade bloqueada).",
                    ephemeral=True
                )

    class RemoverPlayerSelect(discord.ui.Select):
        def __init__(self, mesa_id: int, mesa_nome: str, options: list):
            super().__init__(placeholder="Selecione o jogador para remover...", options=options)
            self.mesa_id = mesa_id
            self.mesa_nome = mesa_nome

        async def callback(self, interaction: discord.Interaction):
            pid = self.values[0]
            member = interaction.guild.get_member(int(pid)) if interaction.guild else None
            nome = member.display_name if member else pid

            db.remover_player_mesa(self.mesa_id, pid)

            await interaction.response.send_message(
                f"✅ **{nome}** removido da **{self.mesa_nome}**! (votos e tokens apagados)",
                ephemeral=True
            )

    class RemoverPlayerView(discord.ui.View):
        def __init__(self, mesa_id: int, mesa_nome: str, options: list):
            super().__init__(timeout=None)
            self.add_item(RemoverPlayerSelect(mesa_id, mesa_nome, options))

    class PainelView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if not interaction.user.guild_permissions.administrator:
                await interaction.response.send_message("❌ Acesso Negado! Você é um jogador. Apenas a organização do torneio pode tocar nesses controles mestres.", ephemeral=True)
                return False
            return True

        @discord.ui.button(label="🏆 Criar Rodada", style=discord.ButtonStyle.blurple, custom_id="btn_nova_rodada", row=0)
        async def btn_rodada(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(RodadaModal())

        @discord.ui.button(label="🎴 Criar Mesa", style=discord.ButtonStyle.success, custom_id="btn_nova_mesa", row=0)
        async def btn_mesa(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(MesaModal())

        @discord.ui.button(label="📊 Status Dinâmico", style=discord.ButtonStyle.secondary, custom_id="btn_status", row=0)
        async def btn_status(self, interaction: discord.Interaction, button: discord.ui.Button):
            rodadas = db.get_todas_rodadas()
            if not rodadas:
                await interaction.response.send_message("❌ Nenhuma rodada encontrada no sistema.", ephemeral=True)
                return
            await interaction.response.send_message("👇 Selecione qual rodada deseja acompanhar nos bastidores:", view=SeletorRodadaView(rodadas[:25]), ephemeral=True)

        @discord.ui.button(label="✏️ Editar Mesa", style=discord.ButtonStyle.secondary, custom_id="btn_editar_mesa", row=1)
        async def btn_editar_mesa(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(EditarMesaModal())

        @discord.ui.button(label="🗑️ Apagar Rodada", style=discord.ButtonStyle.danger, custom_id="btn_apagar_rodada", row=1)
        async def btn_apagar_rodada(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(ApagarRodadaModal())

        @discord.ui.button(label="🗑️ Apagar Mesa", style=discord.ButtonStyle.danger, custom_id="btn_apagar_mesa", row=1)
        async def btn_apagar_mesa(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(ApagarMesaModal())

        @discord.ui.button(label="☢️ FORMATAR TORNEIO", style=discord.ButtonStyle.danger, custom_id="btn_resetar", row=2)
        async def btn_resetar(self, interaction: discord.Interaction, button: discord.ui.Button):
            await interaction.response.send_modal(ResetarModal())

    # ── Eventos ──────────────────────────────────────────────────────────────

    @bot.event
    async def on_ready():
        logger.info(f"Bot online: {bot.user}")
        bot.add_view(PainelView())
        try:
            # Sincroniza apenas o novo comando /painel sobrescrevendo antigas referências
            synced = await bot.tree.sync()
            logger.info(f"{len(synced)} slash commands sincronizados")
        except Exception as e:
            logger.error(f"Erro ao sincronizar: {e}")

    # ── /painel ──────────────────────────────────────────────────────────────

    @bot.tree.command(name="painel", description="Abre o painel iterativo de administração")
    @app_commands.checks.has_permissions(administrator=True)
    async def painel(interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚙️ Painel de Controle - Magic Tournament",
            description="Use os botões abaixo para gerenciar o torneio de forma iterativa.\n\n"
                        "🏆 **Criar Rodada:** Comece uma nova etapa do torneio.\n"
                        "🎴 **Criar Mesa:** Associe jogadores para votarem juntos em horários.\n"
                        "📊 **Status:** Veja exatamente quem já escolheu.\n"
                        "✏️ **Editar Mesa:** Adicione ou remova jogadores de uma mesa existente.",
            color=discord.Color.dark_theme()
        )
        await interaction.response.send_message(embed=embed, view=PainelView())

    return bot


class ConfirmarHorarioView(discord.ui.View):
    def __init__(self, bot_instance, mesa_id: int, opcoes: list[str], rodada_nome: str, mesa_nome: str, players: list):
        super().__init__(timeout=None)
        self.bot_instance = bot_instance
        self.mesa_id = mesa_id
        self.players = players
        self.mesa_nome = mesa_nome
        self.rodada_nome = rodada_nome

        for idx, op in enumerate(opcoes):
            btn = discord.ui.Button(label=op, style=discord.ButtonStyle.success, custom_id=f"conf_{mesa_id}_{idx}")
            btn.callback = self.make_callback(op)
            self.add_item(btn)
            
    def make_callback(self, horario: str):
        async def callback(interaction: discord.Interaction):
            db.marcar_confirmada(self.mesa_id, horario)
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(content=f"✅ Você bateu o martelo! O jogo foi marcado para **{horario}** e os jogadores foram avisados por DM simultaneamente.", view=self)
            
            guild = self.bot_instance.guilds[0] if self.bot_instance.guilds else None
            for pid in self.players:
                if guild:
                    member = guild.get_member(int(pid))
                    if member:
                        try:
                            view_horario = discord.ui.View()
                            view_horario.add_item(discord.ui.Button(label=f"⏰ {horario}", style=discord.ButtonStyle.primary, disabled=True))

                            await member.send(
                                f"🎉 **{self.mesa_nome} — Horário Confirmado!**\n\n"
                                f"📅 O seu confronto oficial da **{self.rodada_nome}** foi agendado pelo organizador para o horário abaixo.\n\n"
                                f"Prepare seu deck e boa sorte! 🃏",
                                view=view_horario
                            )
                        except discord.Forbidden:
                            pass
        return callback


class RetryMesaView(discord.ui.View):
    def __init__(self, bot_instance, mesa_id: int, rodada_nome: str, mesa_nome: str, players: list):
        super().__init__(timeout=None)
        self.bot_instance = bot_instance
        self.mesa_id = mesa_id
        self.rodada_nome = rodada_nome
        self.mesa_nome = mesa_nome
        self.players = players

    @discord.ui.button(label="🔄 Revotar Mesa", style=discord.ButtonStyle.primary)
    async def btn_retry(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        db.limpar_disponibilidades_mesa(self.mesa_id)
        db.resetar_tokens_mesa(self.mesa_id)

        mesa = db.get_mesa(self.mesa_id)
        rodada = db.get_rodada(mesa["rodada_id"])

        guild = self.bot_instance.guilds[0] if self.bot_instance.guilds else None
        notificados, falhas = [], []

        for pid in self.players:
            member = guild.get_member(int(pid)) if guild else None
            if not member:
                falhas.append(pid)
                continue

            token = db.criar_token(pid, self.mesa_id, mesa["rodada_id"])
            link = f"{BASE_URL}/disponibilidade/{token}"

            outros = [
                guild.get_member(int(p)).display_name
                for p in self.players
                if p != pid and guild.get_member(int(p))
            ]

            try:
                await member.send(
                    f"🔄 **Segunda Chamada — {self.mesa_nome}**\n\n"
                    f"Os horários que vocês marcaram infelizmente **não bateram** com os de: **{', '.join(outros)}** 😔\n\n"
                    f"O organizador está pedindo uma **nova votação**. "
                    f"Desta vez, tente expandir ao máximo seus horários disponíveis para aumentar as chances de Match!\n\n"
                    f"💡 _Dica: Conforme seus adversários votarem, você verá os horários deles no calendário!_\n\n"
                    f"🔗 {link}"
                )
                notificados.append(member.display_name)
            except discord.Forbidden:
                falhas.append(member.display_name if member else pid)

        button.disabled = True
        button.label = "✅ Revotação Enviada"
        button.style = discord.ButtonStyle.secondary
        await interaction.message.edit(view=self)

        msg = f"✅ **Revotação iniciada para {self.mesa_nome}!**\n"
        if notificados:
            msg += f"📨 Novos links enviados para: {', '.join(notificados)}\n"
        if falhas:
            msg += f"⚠️ Falha ao enviar para: {', '.join(str(f) for f in falhas)}"
        await interaction.followup.send(msg)


async def verificar_mesa(bot: commands.Bot, mesa_id: int):
    """Chamado pela API após salvar disponibilidade. Verifica se todos responderam."""
    players = db.get_players_mesa(mesa_id)
    disponibilidades = db.get_disponibilidades_mesa(mesa_id)

    if len(disponibilidades) < len(players):
        return  # ainda faltam respostas

    mesa = db.get_mesa(mesa_id)
    rodada = db.get_rodada(mesa["rodada_id"])
    
    opcoes = encontrar_horarios_comuns(disponibilidades, limite=3)

    # Monta dict nome dos players pra formatação
    guild = bot.guilds[0] if bot.guilds else None
    guild_members = {}
    if guild:
        for pid in players:
            m = guild.get_member(int(pid))
            if m:
                guild_members[pid] = m.display_name

    resumo = formatar_disponibilidades(disponibilidades, guild_members)
    
    if guild:
        for member in guild.members:
            if member.guild_permissions.administrator and not member.bot:
                if opcoes:
                    try:
                        view = ConfirmarHorarioView(bot, mesa_id, opcoes, rodada['nome'], mesa['nome'], players)
                        await member.send(
                            f"🔔 **Ação Necessária:** A **{mesa['nome']}** marcou todos os votos!\n\n"
                            f"Cruzei as disposições e encontrei {len(opcoes)} opção(ões) de horários perfeitamente alinhadas entre eles. "
                            f"Como você é o Juíz/Organizador, **clique no botão** da sua escolha abaixo para decretar o horário oficial e eu avisarei os combatentes automaticamente!\n\n"
                            f"**Visão das respostas originais enviadas:**\n{resumo}",
                            view=view
                        )
                    except discord.Forbidden:
                        pass
                else:
                    try:
                        view = RetryMesaView(bot, mesa_id, rodada['nome'], mesa['nome'], players)
                        await member.send(
                            f"⚠️ **Aviso de Choque de Horários:** A **{mesa['nome']}** fechou os votos, mas...\n"
                            f"Os horários marcados por eles não deram 'Match' em dia e horário nenhum.\n\n"
                            f"**Respostas isoladas:**\n{resumo}\n\n"
                            f"Clique no botão abaixo para iniciar uma **revotação** — os jogadores receberão novos links "
                            f"e poderão ver os horários dos adversários no calendário!",
                            view=view
                        )
                    except discord.Forbidden:
                        pass
                break # Envia sempre pro primeiro administrador logado que der sucesso na DM
        logger.info(f"Mesa {mesa_id} aguardando decisao do admin.")
