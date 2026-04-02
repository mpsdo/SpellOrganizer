import sqlite3
import os
import secrets

DB_PATH = os.getenv("DB_PATH", "magic.db")


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._criar_tabelas()

    def _criar_tabelas(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS rodadas (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                nome      TEXT NOT NULL,
                guild_id  TEXT NOT NULL,
                data_ini  TEXT,
                data_fim  TEXT,
                criado_em TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS mesas (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                rodada_id  INTEGER NOT NULL REFERENCES rodadas(id),
                nome       TEXT NOT NULL,
                confirmada INTEGER DEFAULT 0,
                horario    TEXT
            );

            CREATE TABLE IF NOT EXISTS mesa_players (
                mesa_id    INTEGER NOT NULL REFERENCES mesas(id),
                discord_id TEXT NOT NULL,
                PRIMARY KEY (mesa_id, discord_id)
            );

            CREATE TABLE IF NOT EXISTS disponibilidades (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                discord_id TEXT NOT NULL,
                mesa_id    INTEGER NOT NULL,
                slots      TEXT NOT NULL,
                criado_em  TEXT DEFAULT (datetime('now')),
                UNIQUE(discord_id, mesa_id)
            );

            CREATE TABLE IF NOT EXISTS tokens (
                token      TEXT PRIMARY KEY,
                discord_id TEXT NOT NULL,
                mesa_id    INTEGER NOT NULL,
                rodada_id  INTEGER NOT NULL,
                usado      INTEGER DEFAULT 0,
                criado_em  TEXT DEFAULT (datetime('now'))
            );
        """)
        self.conn.commit()

    # ── Rodadas ──────────────────────────────────────────────────────────────

    def criar_rodada(self, nome: str, guild_id: str, data_ini: str = None, data_fim: str = None) -> int:
        cur = self.conn.execute(
            "INSERT INTO rodadas (nome, guild_id, data_ini, data_fim) VALUES (?,?,?,?)",
            (nome, guild_id, data_ini, data_fim)
        )
        self.conn.commit()
        return cur.lastrowid

    def get_rodada(self, rodada_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM rodadas WHERE id=?", (rodada_id,)).fetchone()
        return dict(row) if row else None

    def get_todas_rodadas(self) -> list:
        rows = self.conn.execute("SELECT * FROM rodadas ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

    # ── Mesas ────────────────────────────────────────────────────────────────

    def criar_mesa(self, rodada_id: int, nome: str, player_ids: list) -> int:
        cur = self.conn.execute(
            "INSERT INTO mesas (rodada_id, nome) VALUES (?,?)", (rodada_id, nome)
        )
        mesa_id = cur.lastrowid
        self.conn.executemany(
            "INSERT OR IGNORE INTO mesa_players (mesa_id, discord_id) VALUES (?,?)",
            [(mesa_id, pid) for pid in player_ids]
        )
        self.conn.commit()
        return mesa_id

    def get_mesa(self, mesa_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM mesas WHERE id=?", (mesa_id,)).fetchone()
        return dict(row) if row else None

    def get_mesas_rodada(self, rodada_id: int) -> list:
        rows = self.conn.execute("SELECT * FROM mesas WHERE rodada_id=?", (rodada_id,)).fetchall()
        return [dict(r) for r in rows]

    def marcar_confirmada(self, mesa_id: int, horario: str):
        self.conn.execute(
            "UPDATE mesas SET confirmada=1, horario=? WHERE id=?", (horario, mesa_id)
        )
        self.conn.commit()

    def apagar_mesa(self, mesa_id: int):
        self.conn.execute("DELETE FROM tokens WHERE mesa_id=?", (mesa_id,))
        self.conn.execute("DELETE FROM disponibilidades WHERE mesa_id=?", (mesa_id,))
        self.conn.execute("DELETE FROM mesa_players WHERE mesa_id=?", (mesa_id,))
        self.conn.execute("DELETE FROM mesas WHERE id=?", (mesa_id,))
        self.conn.commit()

    def apagar_rodada(self, rodada_id: int):
        mesas = self.get_mesas_rodada(rodada_id)
        for m in mesas:
            self.apagar_mesa(m["id"])
        self.conn.execute("DELETE FROM rodadas WHERE id=?", (rodada_id,))
        self.conn.commit()

    def resetar_banco(self):
        self.conn.executescript("""
            DELETE FROM tokens;
            DELETE FROM disponibilidades;
            DELETE FROM mesa_players;
            DELETE FROM mesas;
            DELETE FROM rodadas;
            DELETE FROM sqlite_sequence;
        """)
        self.conn.commit()

    # ── Players ───────────────────────────────────────────────────────────────

    def get_players_mesa(self, mesa_id: int) -> list:
        rows = self.conn.execute(
            "SELECT discord_id FROM mesa_players WHERE mesa_id=?", (mesa_id,)
        ).fetchall()
        return [r["discord_id"] for r in rows]

    # ── Disponibilidades ──────────────────────────────────────────────────────

    def salvar_disponibilidade(self, discord_id: str, mesa_id: int, slots: list):
        import json
        self.conn.execute(
            """INSERT INTO disponibilidades (discord_id, mesa_id, slots)
               VALUES (?,?,?)
               ON CONFLICT(discord_id, mesa_id) DO UPDATE SET slots=excluded.slots""",
            (discord_id, mesa_id, json.dumps(slots))
        )
        self.conn.commit()

    def get_disponibilidades_mesa(self, mesa_id: int) -> list:
        import json
        rows = self.conn.execute(
            "SELECT discord_id, slots FROM disponibilidades WHERE mesa_id=?", (mesa_id,)
        ).fetchall()
        return [{"discord_id": r["discord_id"], "slots": json.loads(r["slots"])} for r in rows]

    # ── Tokens ────────────────────────────────────────────────────────────────

    def criar_token(self, discord_id: str, mesa_id: int, rodada_id: int) -> str:
        token = secrets.token_urlsafe(24)
        self.conn.execute(
            "INSERT OR REPLACE INTO tokens (token, discord_id, mesa_id, rodada_id) VALUES (?,?,?,?)",
            (token, discord_id, mesa_id, rodada_id)
        )
        self.conn.commit()
        return token

    def get_token(self, token: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM tokens WHERE token=? AND usado=0", (token,)
        ).fetchone()
        return dict(row) if row else None

    def get_tokens_rodada(self, rodada_id: int) -> list:
        rows = self.conn.execute("SELECT * FROM tokens WHERE rodada_id=?", (rodada_id,)).fetchall()
        return [dict(r) for r in rows]

    def marcar_token_usado(self, token: str):
        self.conn.execute("UPDATE tokens SET usado=1 WHERE token=?", (token,))
        self.conn.commit()

    # ── Editar Mesa ───────────────────────────────────────────────────────────

    def adicionar_player_mesa(self, mesa_id: int, discord_id: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO mesa_players (mesa_id, discord_id) VALUES (?,?)",
            (mesa_id, discord_id)
        )
        self.conn.commit()

    def remover_player_mesa(self, mesa_id: int, discord_id: str):
        self.conn.execute("DELETE FROM mesa_players WHERE mesa_id=? AND discord_id=?", (mesa_id, discord_id))
        self.conn.execute("DELETE FROM disponibilidades WHERE mesa_id=? AND discord_id=?", (mesa_id, discord_id))
        self.conn.execute("DELETE FROM tokens WHERE mesa_id=? AND discord_id=?", (mesa_id, discord_id))
        self.conn.commit()

    # ── Retry / Revotar ───────────────────────────────────────────────────────

    def limpar_disponibilidades_mesa(self, mesa_id: int):
        self.conn.execute("DELETE FROM disponibilidades WHERE mesa_id=?", (mesa_id,))
        self.conn.commit()

    def resetar_tokens_mesa(self, mesa_id: int):
        self.conn.execute("DELETE FROM tokens WHERE mesa_id=?", (mesa_id,))
        self.conn.commit()

    def get_outros_votos_mesa(self, mesa_id: int, discord_id: str) -> dict:
        """Retorna contagem agregada de slots votados por OUTROS players da mesa."""
        import json
        rows = self.conn.execute(
            "SELECT slots FROM disponibilidades WHERE mesa_id=? AND discord_id!=?",
            (mesa_id, discord_id)
        ).fetchall()
        contagem = {}
        for r in rows:
            for s in json.loads(r["slots"]):
                contagem[s] = contagem.get(s, 0) + 1
        return contagem

    def contar_outros_votos_mesa(self, mesa_id: int, discord_id: str) -> int:
        """Conta quantos OUTROS players já enviaram disponibilidade."""
        row = self.conn.execute(
            "SELECT COUNT(DISTINCT discord_id) as c FROM disponibilidades WHERE mesa_id=? AND discord_id!=?",
            (mesa_id, discord_id)
        ).fetchone()
        return row["c"] if row else 0

