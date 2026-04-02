# ⚔️ Magic Tournament Bot

Bot Discord + calendário web para organizar horários de torneios de Magic: The Gathering.

## Como funciona

1. Admin usa `/nova_rodada` para criar a rodada com as datas
2. Admin usa `/nova_mesa` para definir os players de cada mesa
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
| `/nova_rodada nome data_ini data_fim` | Admin | Cria uma rodada com período |
| `/nova_mesa rodada_id nome players` | Admin | Cria mesa e envia DM com link do calendário |
| `/status_rodada rodada_id` | Qualquer um | Mostra quem já respondeu |
| `/reenviar_link rodada_id player` | Admin | Reenvia o link para um player específico |

### Exemplo de uso semanal

```
/nova_rodada nome:Rodada5 data_ini:30/03 data_fim:05/04
/nova_mesa rodada_id:1 nome:Mesa1 players:@Mukekah @Andrio @Pedro
/nova_mesa rodada_id:1 nome:Mesa2 players:@Tiago @Rafael @Lucas
```

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
