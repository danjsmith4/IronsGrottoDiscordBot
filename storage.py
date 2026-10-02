"""SQLite and JSON persistence; no Discord dependencies."""
import datetime
import json
import logging
import math
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import List, Optional, Tuple

from config import EVENTBAN_DB_PATH, LEADERBOARD_DB_PATH, WAVE_BOSSES

logger = logging.getLogger(__name__)
TIME_PART = re.compile(r'\d+(?:\.\d+)?')


class BumpStore:
    """A single persistent reminder, separate from existing bot databases."""

    def __init__(self, path='bump_reminder.sqlite3'):
        self.path = path
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('CREATE TABLE IF NOT EXISTS reminder (id INTEGER PRIMARY KEY, next_due INTEGER NOT NULL, message_id INTEGER, last_user INTEGER, paused INTEGER NOT NULL)')
            conn.execute('INSERT OR IGNORE INTO reminder VALUES (1, 0, NULL, NULL, 0)')

    def read(self):
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory = sqlite3.Row
            return dict(conn.execute('SELECT * FROM reminder WHERE id=1').fetchone())

    def sent(self, message_id):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('UPDATE reminder SET message_id=? WHERE id=1', (message_id,))

    def complete(self, user_id, next_due):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('UPDATE reminder SET next_due=?, last_user=?, message_id=NULL WHERE id=1', (next_due, user_id))

    def pause(self, paused):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('UPDATE reminder SET paused=? WHERE id=1', (int(paused),))

def db():
    return sqlite3.connect(EVENTBAN_DB_PATH)

def init_eventban_db():
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS event_bans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            issue TEXT NOT NULL,
            punishment TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bans_guild_user ON event_bans(guild_id, user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bans_guild_created ON event_bans(guild_id, created_at)")
    conn.commit()
    conn.close()

def insert_eventban(guild_id: int, user_id: int, moderator_id: int, event: str, issue: str, punishment: str) -> None:
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO event_bans(guild_id, user_id, moderator_id, event, issue, punishment, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (guild_id, user_id, moderator_id, event.strip(), issue.strip(), punishment.strip(),
         datetime.datetime.utcnow().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()

def get_banned_users_with_latest(guild_id: int) -> List[Tuple[int, str, str, str, str]]:
    """
    Returns list of (user_id, latest_event, latest_issue, latest_punishment, latest_created_at).
    """
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT eb.user_id, eb.event, eb.issue, eb.punishment, eb.created_at
        FROM event_bans eb
        JOIN (
            SELECT user_id, MAX(created_at) AS max_created
            FROM event_bans
            WHERE guild_id=?
            GROUP BY user_id
        ) latest ON latest.user_id = eb.user_id AND latest.max_created = eb.created_at
        WHERE eb.guild_id=?
        ORDER BY eb.created_at DESC
        """,
        (guild_id, guild_id),
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def get_user_eventbans(guild_id: int, user_id: int):
    """Return list of rows: (id, event, issue, punishment, created_at, moderator_id) newest first."""
    conn = db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, event, issue, punishment, created_at, moderator_id
        FROM event_bans
        WHERE guild_id=? AND user_id=?
        ORDER BY created_at DESC, id DESC
        """,
        (guild_id, user_id),
    )
    rows = cur.fetchall()
    conn.close()
    return rows

def delete_eventban_by_id(guild_id: int, record_id: int) -> int:
    """Delete a single record by its id (scoped to guild). Returns number of rows deleted (0 or 1)."""
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM event_bans WHERE id=? AND guild_id=?", (record_id, guild_id))
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count

def delete_eventbans_for_user(guild_id: int, user_id: int) -> int:
    """Delete all records for a user in a guild. Returns number of rows deleted."""
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM event_bans WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count

def get_latest_record_id(guild_id: int, user_id: int) -> Optional[int]:
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM event_bans WHERE guild_id=? AND user_id=? ORDER BY created_at DESC, id DESC LIMIT 1",
        (guild_id, user_id),
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


class LeaderboardStore:
    def __init__(self, path=LEADERBOARD_DB_PATH):
        self.conn = sqlite3.connect(path)
        self.cursor = self.conn.cursor()
        self.create_leaderboard_table()

    def close(self):
        self.conn.close()

    def clear(self, boss=None):
        with self.conn:
            if boss is None:
                return self.conn.execute('DELETE FROM leaderboards').rowcount
            return self.conn.execute('DELETE FROM leaderboards WHERE boss_name = ?', (boss,)).rowcount

    def create_leaderboard_table(self):
        self.cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS leaderboards (
                boss_name TEXT,
                rank INTEGER,
                user TEXT,
                time TEXT,
                proof_link TEXT,
                PRIMARY KEY (boss_name, rank)
            )
            '''
        )
        self.conn.commit()

    def load_json(self, path: str) -> dict:
        try:
            with open(path, "r") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError(f'{path} must contain a JSON object')
                return data
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            logger.exception('Cannot read leaderboard state %s', path)
            raise

    def save_json(self, path: str, data: dict):
        destination = Path(path)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent, delete=False) as f:
                temporary = f.name
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def convert_time(self, time_str: str) -> float:
        parts = time_str.strip().split(':')
        try:
            if not 1 <= len(parts) <= 3 or not all(TIME_PART.fullmatch(part) for part in parts):
                return float('inf')
            if len(parts) > 1 and (not parts[0].isdigit() or float(parts[1]) >= 60):
                return float('inf')
            if len(parts) == 3:
                m, s, ms = map(float, parts)
                if ms >= 1000:
                    return float('inf')
                return m * 60 + s + ms / 1000.0
            elif len(parts) == 2:
                m = float(parts[0]); s = float(parts[1])
                return m * 60 + s
            return float(time_str)
        except Exception:
            return float('inf')

    def distinct_users(self, prefix: str = "") -> List[str]:
        """Return up to 25 distinct usernames, optionally filtering by prefix (case-insensitive)."""
        like = f"%{prefix.strip().lower()}%"
        try:
            self.cursor.execute(
                "SELECT DISTINCT user FROM leaderboards WHERE lower(user) LIKE ? ORDER BY user LIMIT 25",
                (like,)
            )
            return [row[0] for row in self.cursor.fetchall()]
        except Exception:
            return []

    def is_wave_boss(self, boss_name: str) -> bool:
        return boss_name in WAVE_BOSSES

    def parse_wave(self, s: str) -> int:
        try:
            return int(str(s).strip())
        except Exception:
            return -1  # treat invalid as very low

    def _sort_key_for_boss(self, boss: str):
        """Return a sort key function for ranking."""
        if self.is_wave_boss(boss):
            # Higher wave is better → sort by negative wave (desc). Tie-breaker by user to stabilize.
            return lambda row: (-self.parse_wave(row[1]), row[0].lower())
        # default: lower time better
        return lambda row: (self.convert_time(row[1]), row[0].lower())

    def get_top_3_leaderboard(self, boss_name):
        self.cursor.execute(
            '''
            SELECT user, time, proof_link FROM leaderboards
            WHERE boss_name = ?
            ORDER BY (rank IS NULL), rank ASC, user ASC
            LIMIT 3
            ''',
            (boss_name,)
        )
        return self.cursor.fetchall()

    def get_all_leaderboard_entries(self, boss_name):
        self.cursor.execute(
            '''
            SELECT user, time, proof_link FROM leaderboards
            WHERE boss_name = ?
            ORDER BY (rank IS NULL), rank ASC, user ASC
            ''',
            (boss_name,)
        )
        return self.cursor.fetchall()

    def re_rank_leaderboard(self, boss_name):
        with self.conn:
            self._rank_rows(boss_name)

    def _rank_rows(self, boss_name):
        self.cursor.execute(
            '''
            SELECT rowid, user, time, proof_link FROM leaderboards
            WHERE boss_name = ?
            ''',
            (boss_name,)
        )
        entries = self.cursor.fetchall()

        key_fn = self._sort_key_for_boss(boss_name)
        sorted_entries = sorted(entries, key=lambda row: key_fn(row[1:]))

        self.cursor.execute('UPDATE leaderboards SET rank = NULL WHERE boss_name = ?', (boss_name,))

        self.cursor.executemany(
            'UPDATE leaderboards SET rank = ? WHERE rowid = ?',
            ((rank, row[0]) for rank, row in enumerate(sorted_entries, start=1)),
        )

    def save_entry(self, boss, user, value, proof_link=None):
        user = user.strip()
        value = value.strip()
        if not user or len(user) > 32:
            raise ValueError('Enter an OSRS name between 1 and 32 characters.')
        if len(value) > 20:
            raise ValueError('The time or wave value is too long.')
        if self.is_wave_boss(boss):
            if self.parse_wave(value) < 0:
                raise ValueError('Please enter a valid wave number (integer).')
            value = str(self.parse_wave(value))
        else:
            seconds = self.convert_time(value)
            if not math.isfinite(seconds) or seconds <= 0:
                raise ValueError('Please enter a positive time, such as 1:23.45.')
        with self.conn:
            self.cursor.execute('DELETE FROM leaderboards WHERE boss_name = ? AND user = ?', (boss, user))
            self.cursor.execute(
                'INSERT INTO leaderboards (boss_name, user, time, proof_link, rank) VALUES (?, ?, ?, ?, NULL)',
                (boss, user, value, proof_link or ''),
            )
            self._rank_rows(boss)
        return value

    def remove_entries(self, user, boss=None):
        clause = 'user = ?' + (' AND boss_name = ?' if boss else '')
        values = (user, boss) if boss else (user,)
        with self.conn:
            bosses = [row[0] for row in self.conn.execute(
                'SELECT DISTINCT boss_name FROM leaderboards WHERE ' + clause, values)]
            deleted = self.conn.execute('DELETE FROM leaderboards WHERE ' + clause, values).rowcount
            for name in bosses:
                self._rank_rows(name)
        return deleted, bosses
