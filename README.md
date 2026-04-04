# ⚔️ Magic Tournament Bot

Bot Discord + calendário web para organizar horários de torneios de Magic: The Gathering.

## Como funciona

1. Admin usa `/painel` -> **🏆 Criar Rodada** para definir as datas
2. Admin usa `/painel` -> **🎴 Criar Mesa** para definir os players de cada mesa
3. Bot envia DM para cada player com um **link pessoal** do calendário
4. Player abre o link e marca os horários disponíveis arrastando na grade
5. Bot cruza automaticamente:
   - ✅ **Achou horário em comum** → DM para todos com o horário confirmado
   - ⚠️ **Sem horário comum** → DM para o admin com as disponibilidades para resolver manualmente

---

## Setup

### 1. Criar o bot no Discord

1. Acesse [discord.com/developers/applications](https://discord.com/developers/applications)
2. **New Application** → dê um nome
3. Vá em **Bot** → **Add Bot**
4. Em **Privileged Gateway Intents**, ative:
   - `SERVER MEMBERS INTENT`
   - `MESSAGE CONTENT INTENT`
5. Copie o **Token** (vai no `.env` como `DISCORD_TOKEN`)
6. Vá em **OAuth2 → URL Generator**:
   - Scopes: `bot` + `applications.commands`
   - Bot Permissions: `Send Messages`, `Read Message History`
7. Use a URL gerada para convidar o bot ao servidor

### 2. Instalar dependências

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configurar variáveis de ambiente

```bash
cp .env.example .env
# Edite o .env com seu editor
```

Preencha:
- `DISCORD_TOKEN` — token do bot
- `BASE_URL` — URL pública onde vai rodar (ex: `https://magic-bot.up.railway.app`)

### 4. Rodar localmente

```bash
python main.py
```

Acesse `http://localhost:8000/health` para confirmar que está rodando.

---

## Deploy no Railway

```bash
# Instale o CLI do Railway
npm install -g @railway/cli

# Login
railway login

# Dentro da pasta do projeto
railway init
railway up
```

No dashboard do Railway, configure as variáveis de ambiente:
- `DISCORD_TOKEN`
- `BASE_URL` → use a URL que o Railway gerou (ex: `https://magic-bot-production.up.railway.app`)

---

## Comandos Discord

| Comando | Permissão | Descrição |
|---|---|---|
| `/painel` | Admin | Abre o painel administrativo com todas as funções |

No **Painel**, você encontra:
- 🏆 **Criar Rodada**: Define nome e período (ex: 30/03 a 05/04)
- 📝 **Editar Rodada**: Altera nome ou datas de uma rodada existente
- 🎴 **Criar Mesa**: Seleciona os players (2 a 4) para uma rodada
- 📊 **Status Dinâmico**: Acompanha quem já votou e permite **"Cutucar Atrasados"** (reenviar links)
- 👥 **Editar Jogadores**: Adiciona ou remove players de mesas ativas
- ☢️ **NUCLEAR RESET**: Limpa todo o banco de dados (Cuidado!)

---

### Exemplo de uso semanal

1. `/painel` -> **Criar Rodada** (ID será gerado)
2. `/painel` -> **Criar Mesa** -> Selecione a rodada e os jogadores
3. O Bot envia as DMs automaticamente.
4. Acompanhe em **Status Dinâmico**.

---

## Estrutura do projeto

```
magic-bot/
├── main.py          # FastAPI: serve o calendário e recebe as respostas
├── bot.py           # Bot Discord: slash commands e notificações
├── database.py      # Banco SQLite: rodadas, mesas, disponibilidades, tokens
├── scheduler.py     # Lógica de cruzamento de horários
├── requirements.txt
├── Procfile         # Para Railway/Render
├── .env.example
└── README.md
```

---

## Endpoints da API

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/disponibilidade/{token}` | Página do calendário para o player |
| `POST` | `/disponibilidade/{token}` | Salva disponibilidade `{"slots": ["1,40", "1,41"]}` |
| `GET` | `/health` | Status do serviço |
