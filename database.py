"""
database.py — SQLite database manager
Monthly rotating signal DB + persistent lifetime PNL + config storage

Directory layout:
  data/
    config.db          ← watchlist, bot config, RSI history
    lifetime.db        ← all closed trades across all months
    signals_2025_01.db ← monthly signal tables (auto-created)
    signals_2025_02.db
    ...
"""
from __future__ import annotations
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────
def _conn(path: str) -> sqlite3.Connection:
    c = sqlite3.connect(path, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


# ─────────────────────────────────────────────────────────────
#  DatabaseManager
# ─────────────────────────────────────────────────────────────
class DatabaseManager:
    def __init__(self, db_dir: str = "data") -> None:
        self.db_dir      = db_dir
        os.makedirs(db_dir, exist_ok=True)
        self.config_db   = os.path.join(db_dir, "config.db")
        self.lifetime_db = os.path.join(db_dir, "lifetime.db")

    # ── Path helpers ─────────────────────────────────────
    def _monthly_path(self, year: int | None = None, month: int | None = None) -> str:
        now = datetime.now()
        y = year  or now.year
        m = month or now.month
        return os.path.join(self.db_dir, f"signals_{y:04d}_{m:02d}.db")

    # ── Bootstrap ────────────────────────────────────────
    def initialize(self) -> None:
        self._init_config()
        self._init_lifetime()
        self._init_monthly()          # current month
        self._migrate_signals_table() # backward-compat column additions

    def _migrate_signals_table(self) -> None:
        """Add new columns to all existing monthly DBs (silent if already present)."""
        new_cols = [
            "ALTER TABLE signals ADD COLUMN is_executed     INTEGER DEFAULT 0",
            "ALTER TABLE signals ADD COLUMN peak_price      REAL    DEFAULT NULL",
            "ALTER TABLE signals ADD COLUMN peak_tp_touched TEXT    DEFAULT NULL",
        ]
        for fname in os.listdir(self.db_dir):
            if fname.startswith("signals_") and fname.endswith(".db"):
                path = os.path.join(self.db_dir, fname)
                with _conn(path) as c:
                    for sql in new_cols:
                        try:
                            c.execute(sql)
                        except Exception:
                            pass  # column already exists

    def _init_config(self) -> None:
        with _conn(self.config_db) as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS config (
                    key        TEXT PRIMARY KEY,
                    value      TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS watchlist (
                    symbol    TEXT PRIMARY KEY,
                    active    INTEGER DEFAULT 1,
                    added_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS rsi_history (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol     TEXT NOT NULL,
                    timeframe  TEXT NOT NULL,
                    rsi_value  REAL NOT NULL,
                    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_rsi_sym_tf
                    ON rsi_history(symbol, timeframe);
                CREATE TABLE IF NOT EXISTS dynamic_watchlist (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol     TEXT NOT NULL,
                    rank       INTEGER,
                    fetched_at TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol      TEXT NOT NULL UNIQUE,
                    side        TEXT NOT NULL,
                    qty         REAL NOT NULL,
                    entry_price REAL NOT NULL,
                    sl_price    REAL NOT NULL,
                    tp3_price   REAL NOT NULL,
                    risk_usd    REAL NOT NULL,
                    leverage    INTEGER NOT NULL,
                    sl_order_id INTEGER,
                    tp_order_id INTEGER,
                    avg_count   INTEGER DEFAULT 1,
                    signal_ids  TEXT DEFAULT '',
                    opened_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
            """)
            defaults = {
                "default_timeframe":   "15m",
                "scan_interval":       "300",
                "min_confidence":      "6",
                "auto_scan":           "true",
                "signal_expiry_hours": "4",
                "notify_lean":         "false",
                "leverage_suggestion": "5",
                "risk_per_trade_pct":  "1",
                "trade_risk_usd":      "5.0",
                "trade_min_confidence": "7",
            }
            c.executemany(
                "INSERT OR IGNORE INTO config(key,value) VALUES(?,?)",
                defaults.items(),
            )

    def _init_lifetime(self) -> None:
        with _conn(self.lifetime_db) as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS lifetime_signals (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id   INTEGER,
                    month_table TEXT,
                    symbol      TEXT,
                    timeframe   TEXT,
                    signal_type TEXT,
                    confidence  INTEGER,
                    entry_price REAL,
                    exit_price  REAL,
                    sl_price    REAL,
                    tp1_price   REAL,
                    tp2_price   REAL,
                    tp3_price   REAL,
                    pnl_pct     REAL,
                    pnl_usdt    REAL DEFAULT 0,
                    status      TEXT,
                    created_at  TIMESTAMP,
                    closed_at   TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_lt_symbol  ON lifetime_signals(symbol);
                CREATE INDEX IF NOT EXISTS idx_lt_created ON lifetime_signals(created_at);
                CREATE INDEX IF NOT EXISTS idx_lt_status  ON lifetime_signals(status);
            """)

    def _init_monthly(self, year: int | None = None, month: int | None = None) -> str:
        path = self._monthly_path(year, month)
        with _conn(path) as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS signals (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol            TEXT NOT NULL,
                    timeframe         TEXT NOT NULL,
                    signal_type       TEXT NOT NULL,
                    confidence        INTEGER,
                    bull_score        REAL,
                    bear_score        REAL,
                    entry_price       REAL,
                    current_price     REAL,
                    sl_price          REAL,
                    tp1_price         REAL,
                    tp2_price         REAL,
                    tp3_price         REAL,
                    tp1_hit           INTEGER DEFAULT 0,
                    tp2_hit           INTEGER DEFAULT 0,
                    tp3_hit           INTEGER DEFAULT 0,
                    rsi               REAL,
                    macd_hist         REAL,
                    adx               REAL,
                    ema9              REAL,
                    ema21             REAL,
                    ema50             REAL,
                    bb_position       REAL,
                    volume_ratio      REAL,
                    momentum          REAL,
                    divergence        TEXT,
                    funding_rate      REAL,
                    atr               REAL,
                    pnl_pct           REAL DEFAULT 0,
                    pnl_usdt          REAL DEFAULT 0,
                    status            TEXT DEFAULT 'OPEN',
                    invalidated_reason TEXT,
                    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    closed_at         TIMESTAMP,
                    expires_at        TIMESTAMP,
                    is_executed       INTEGER DEFAULT 0,
                    peak_price        REAL    DEFAULT NULL,
                    peak_tp_touched   TEXT    DEFAULT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sig_sym    ON signals(symbol);
                CREATE INDEX IF NOT EXISTS idx_sig_status ON signals(status);
                CREATE INDEX IF NOT EXISTS idx_sig_create ON signals(created_at);
            """)
        return path

    # ─────────────────────────────────────────────────────
    #  Signal CRUD
    # ─────────────────────────────────────────────────────
    def save_signal(self, signal, expiry_hours: float = 4.0) -> int:
        path = self._monthly_path()
        expires = datetime.now() + timedelta(hours=expiry_hours)
        with _conn(path) as c:
            cur = c.execute("""
                INSERT INTO signals (
                    symbol, timeframe, signal_type, confidence,
                    bull_score, bear_score, entry_price, current_price,
                    sl_price, tp1_price, tp2_price, tp3_price,
                    rsi, macd_hist, adx, ema9, ema21, ema50,
                    bb_position, volume_ratio, momentum,
                    divergence, funding_rate, atr, expires_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                signal.symbol, signal.timeframe, signal.signal_type, signal.confidence,
                signal.bull_score, signal.bear_score,
                signal.entry_price, signal.entry_price,
                signal.sl_price, signal.tp1_price, signal.tp2_price, signal.tp3_price,
                signal.rsi, signal.macd_hist, signal.adx,
                signal.ema9, signal.ema21, signal.ema50,
                signal.bb_position, signal.volume_ratio, signal.momentum,
                signal.divergence, signal.funding_rate, signal.atr,
                expires.isoformat(),
            ))
            return cur.lastrowid

    def get_open_signals(self, year: int | None = None, month: int | None = None) -> List[Dict]:
        path = self._monthly_path(year, month)
        if not os.path.exists(path):
            return []
        with _conn(path) as c:
            rows = c.execute(
                "SELECT * FROM signals WHERE status='OPEN' ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_signal_status(
        self,
        signal_id: int,
        status: str,
        current_price: float,
        pnl_pct: float,
        pnl_usdt: float = 0.0,
        year: int | None = None,
        month: int | None = None,
    ) -> None:
        path = self._monthly_path(year, month)
        with _conn(path) as c:
            c.execute("""
                UPDATE signals
                SET status=?, current_price=?, pnl_pct=?, pnl_usdt=?,
                    closed_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (status, current_price, pnl_pct, pnl_usdt, signal_id))

        if status not in ("OPEN",):
            self._sync_to_lifetime(signal_id, year, month)

    def mark_tp_hit(self, signal_id: int, tp_num: int,
                    year: int | None = None, month: int | None = None) -> None:
        """Mark TP1 or TP2 as hit without closing the position."""
        col  = {1: "tp1_hit", 2: "tp2_hit", 3: "tp3_hit"}.get(tp_num)
        path = self._monthly_path(year, month)
        if col:
            with _conn(path) as c:
                c.execute(f"UPDATE signals SET {col}=1 WHERE id=?", (signal_id,))

    def invalidate_signal(self, signal_id: int, reason: str,
                          year: int | None = None, month: int | None = None) -> None:
        path = self._monthly_path(year, month)
        with _conn(path) as c:
            c.execute("""
                UPDATE signals
                SET status='INVALIDATED', invalidated_reason=?,
                    closed_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (reason, signal_id))
        self._sync_to_lifetime(signal_id, year, month)

    def _sync_to_lifetime(self, signal_id: int,
                          year: int | None = None, month: int | None = None) -> None:
        path    = self._monthly_path(year, month)
        now     = datetime.now()
        y, m    = year or now.year, month or now.month
        tbl_key = f"signals_{y:04d}_{m:02d}"

        with _conn(path) as c:
            row = c.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
        if not row:
            return
        row = dict(row)

        with _conn(self.lifetime_db) as c:
            existing = c.execute(
                "SELECT id FROM lifetime_signals WHERE signal_id=? AND month_table=?",
                (signal_id, tbl_key),
            ).fetchone()

            if existing:
                c.execute("""
                    UPDATE lifetime_signals
                    SET exit_price=?, pnl_pct=?, pnl_usdt=?, status=?, closed_at=?
                    WHERE signal_id=? AND month_table=?
                """, (
                    row["current_price"], row["pnl_pct"], row["pnl_usdt"],
                    row["status"], row["closed_at"],
                    signal_id, tbl_key,
                ))
            else:
                c.execute("""
                    INSERT INTO lifetime_signals (
                        signal_id, month_table, symbol, timeframe, signal_type,
                        confidence, entry_price, exit_price, sl_price,
                        tp1_price, tp2_price, tp3_price,
                        pnl_pct, pnl_usdt, status, created_at, closed_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    signal_id, tbl_key,
                    row["symbol"], row["timeframe"], row["signal_type"],
                    row["confidence"], row["entry_price"], row["current_price"],
                    row["sl_price"], row["tp1_price"], row["tp2_price"], row["tp3_price"],
                    row["pnl_pct"], row["pnl_usdt"], row["status"],
                    row["created_at"], row["closed_at"],
                ))

    # ─────────────────────────────────────────────────────
    #  Statistics
    # ─────────────────────────────────────────────────────
    def _stats_query(self, path: str, where: str = "", params: tuple = ()) -> Dict:
        if not os.path.exists(path):
            return {}
        with _conn(path) as c:
            row = c.execute(f"""
                SELECT
                    COUNT(*)  AS total,
                    SUM(CASE WHEN status IN ('TP1','TP2','TP3') THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN status='SL'      THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN status='EXPIRED' THEN 1 ELSE 0 END) AS expired,
                    SUM(CASE WHEN status='OPEN'    THEN 1 ELSE 0 END) AS open_count,
                    ROUND(SUM(CASE WHEN status NOT IN ('OPEN','EXPIRED')
                                   THEN pnl_pct ELSE 0 END), 4)       AS total_pnl,
                    ROUND(AVG(CASE WHEN status NOT IN ('OPEN','EXPIRED')
                                   THEN pnl_pct END), 4)              AS avg_pnl,
                    ROUND(MAX(pnl_pct), 4)                             AS best_trade,
                    ROUND(MIN(CASE WHEN status NOT IN ('OPEN','EXPIRED')
                                   THEN pnl_pct END), 4)              AS worst_trade,
                    COUNT(DISTINCT symbol)                             AS symbols_traded
                FROM signals
                {where}
            """, params).fetchone()
        return dict(row) if row else {}

    def get_daily_stats(self, date_str: str | None = None) -> Dict:
        if not date_str:
            date_str = datetime.now().strftime("%Y-%m-%d")
        return self._stats_query(
            self._monthly_path(),
            "WHERE DATE(created_at)=?",
            (date_str,),
        )

    def get_weekly_stats(self) -> Dict:
        return self._stats_query(
            self._monthly_path(),
            "WHERE created_at >= datetime('now','-7 days')",
        )

    def get_monthly_stats(self, year: int | None = None, month: int | None = None) -> Dict:
        return self._stats_query(self._monthly_path(year, month))

    def get_lifetime_stats(self, symbol: str | None = None) -> Dict:
        if not os.path.exists(self.lifetime_db):
            return {}
        where  = "WHERE status NOT IN ('OPEN','EXPIRED')"
        params: tuple = ()
        if symbol:
            where += " AND symbol=?"
            params = (symbol,)
        with _conn(self.lifetime_db) as c:
            row = c.execute(f"""
                SELECT
                    COUNT(*)  AS total,
                    SUM(CASE WHEN status IN ('TP1','TP2','TP3') THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN status='SL' THEN 1 ELSE 0 END) AS losses,
                    ROUND(SUM(pnl_pct),4) AS total_pnl,
                    ROUND(AVG(pnl_pct),4) AS avg_pnl,
                    ROUND(MAX(pnl_pct),4) AS best_trade,
                    ROUND(MIN(pnl_pct),4) AS worst_trade
                FROM lifetime_signals {where}
            """, params).fetchone()
        return dict(row) if row else {}

    def get_win_rate_by_symbol(self) -> List[Dict]:
        if not os.path.exists(self.lifetime_db):
            return []
        with _conn(self.lifetime_db) as c:
            rows = c.execute("""
                SELECT
                    symbol,
                    COUNT(*) AS total,
                    SUM(CASE WHEN status IN ('TP1','TP2','TP3') THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN status='SL' THEN 1 ELSE 0 END) AS losses,
                    ROUND(100.0*SUM(CASE WHEN status IN ('TP1','TP2','TP3')
                                         THEN 1 ELSE 0 END)/COUNT(*), 1) AS win_rate,
                    ROUND(SUM(pnl_pct),2) AS total_pnl
                FROM lifetime_signals
                WHERE status NOT IN ('OPEN','EXPIRED')
                GROUP BY symbol
                HAVING total >= 3
                ORDER BY win_rate DESC, total DESC
                LIMIT 20
            """).fetchall()
        return [dict(r) for r in rows]

    def get_recent_signals(self, limit: int = 10,
                           year: int | None = None, month: int | None = None) -> List[Dict]:
        path = self._monthly_path(year, month)
        if not os.path.exists(path):
            return []
        with _conn(path) as c:
            rows = c.execute("""
                SELECT id, symbol, timeframe, signal_type, confidence,
                       status, pnl_pct, created_at,
                       is_executed, peak_price, peak_tp_touched
                FROM signals ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ─────────────────────────────────────────────────────
    #  Config
    # ─────────────────────────────────────────────────────
    def get_config(self, key: str, default: str | None = None) -> str | None:
        with _conn(self.config_db) as c:
            row = c.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_config(self, key: str, value: str) -> None:
        with _conn(self.config_db) as c:
            c.execute("""
                INSERT OR REPLACE INTO config(key,value,updated_at)
                VALUES(?,?,CURRENT_TIMESTAMP)
            """, (key, value))

    # ─────────────────────────────────────────────────────
    #  Trades (Binance Demo active positions)
    # ─────────────────────────────────────────────────────
    def save_trade(
        self,
        symbol: str,
        side: str,
        qty: float,
        entry_price: float,
        sl_price: float,
        tp3_price: float,
        risk_usd: float,
        leverage: int,
        sl_order_id: int | None = None,
        tp_order_id: int | None = None,
        signal_id: int | None = None,
    ) -> int:
        sig_ids = str(signal_id) if signal_id else ""
        with _conn(self.config_db) as c:
            cur = c.execute("""
                INSERT INTO trades
                    (symbol, side, qty, entry_price, sl_price, tp3_price,
                     risk_usd, leverage, sl_order_id, tp_order_id, avg_count, signal_ids)
                VALUES (?,?,?,?,?,?,?,?,?,?,1,?)
            """, (symbol, side, qty, entry_price, sl_price, tp3_price,
                  risk_usd, leverage, sl_order_id, tp_order_id, sig_ids))
            return cur.lastrowid

    def get_open_trade(self, symbol: str) -> dict | None:
        with _conn(self.config_db) as c:
            row = c.execute(
                "SELECT * FROM trades WHERE symbol=?", (symbol,)
            ).fetchone()
        return dict(row) if row else None

    def get_all_open_trades(self) -> List[Dict]:
        with _conn(self.config_db) as c:
            rows = c.execute(
                "SELECT * FROM trades ORDER BY opened_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_trade_average(
        self,
        symbol: str,
        new_qty: float,
        new_entry_price: float,
        new_tp3_price: float,
        new_tp_order_id: int | None = None,
        signal_id: int | None = None,
    ) -> None:
        with _conn(self.config_db) as c:
            row = c.execute(
                "SELECT avg_count, signal_ids FROM trades WHERE symbol=?", (symbol,)
            ).fetchone()
            if not row:
                return
            count   = (row["avg_count"] or 1) + 1
            sig_ids = row["signal_ids"] or ""
            if signal_id:
                sig_ids = f"{sig_ids},{signal_id}".strip(",")
            c.execute("""
                UPDATE trades
                SET qty=?, entry_price=?, tp3_price=?,
                    tp_order_id=COALESCE(?,tp_order_id),
                    avg_count=?, signal_ids=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE symbol=?
            """, (new_qty, new_entry_price, new_tp3_price,
                  new_tp_order_id, count, sig_ids, symbol))

    def update_trade_orders(
        self,
        symbol: str,
        sl_order_id: int | None = None,
        tp_order_id: int | None = None,
    ) -> None:
        with _conn(self.config_db) as c:
            c.execute("""
                UPDATE trades
                SET sl_order_id=COALESCE(?,sl_order_id),
                    tp_order_id=COALESCE(?,tp_order_id),
                    updated_at=CURRENT_TIMESTAMP
                WHERE symbol=?
            """, (sl_order_id, tp_order_id, symbol))

    def delete_trade(self, symbol: str) -> None:
        with _conn(self.config_db) as c:
            c.execute("DELETE FROM trades WHERE symbol=?", (symbol,))

    # ─────────────────────────────────────────────────────
    #  Watchlist
    # ─────────────────────────────────────────────────────
    def get_watchlist(self, active_only: bool = True) -> List[str]:
        q = "SELECT symbol FROM watchlist"
        if active_only:
            q += " WHERE active=1"
        q += " ORDER BY symbol"
        with _conn(self.config_db) as c:
            return [r["symbol"] for r in c.execute(q).fetchall()]

    def add_to_watchlist(self, symbol: str) -> None:
        with _conn(self.config_db) as c:
            c.execute(
                "INSERT OR REPLACE INTO watchlist(symbol,active) VALUES(?,1)",
                (symbol,),
            )

    def remove_from_watchlist(self, symbol: str) -> None:
        with _conn(self.config_db) as c:
            c.execute("UPDATE watchlist SET active=0 WHERE symbol=?", (symbol,))

    # ─────────────────────────────────────────────────────
    #  RSI history (for divergence detection)
    # ─────────────────────────────────────────────────────
    def save_rsi(self, symbol: str, timeframe: str, rsi: float) -> None:
        with _conn(self.config_db) as c:
            c.execute(
                "INSERT INTO rsi_history(symbol,timeframe,rsi_value) VALUES(?,?,?)",
                (symbol, timeframe, rsi),
            )
            # Keep only last 60 entries per symbol/timeframe
            c.execute("""
                DELETE FROM rsi_history
                WHERE symbol=? AND timeframe=?
                  AND id NOT IN (
                      SELECT id FROM rsi_history
                      WHERE symbol=? AND timeframe=?
                      ORDER BY id DESC LIMIT 60
                  )
            """, (symbol, timeframe, symbol, timeframe))

    def get_rsi_history(self, symbol: str, timeframe: str) -> List[float]:
        with _conn(self.config_db) as c:
            rows = c.execute("""
                SELECT rsi_value FROM rsi_history
                WHERE symbol=? AND timeframe=?
                ORDER BY id DESC LIMIT 30
            """, (symbol, timeframe)).fetchall()
        return [r["rsi_value"] for r in reversed(rows)]

    # ─────────────────────────────────────────────────────
    #  DB discovery
    # ─────────────────────────────────────────────────────
    def get_available_months(self) -> List[str]:
        months = []
        for f in os.listdir(self.db_dir):
            if f.startswith("signals_") and f.endswith(".db"):
                months.append(f[8:-3])   # "YYYY_MM"
        return sorted(months)

    # ── [FEATURE 3] Executed flag ─────────────────────────
    def mark_executed(self, signal_id: int, executed: bool = True,
                      year: int | None = None, month: int | None = None) -> None:
        """Mark signal as executed (trade taken) or observation only."""
        path = self._monthly_path(year, month)
        if not os.path.exists(path):
            return
        with _conn(path) as c:
            c.execute(
                "UPDATE signals SET is_executed=? WHERE id=?",
                (1 if executed else 0, signal_id),
            )

    # ── [FEATURE 5] Peak tracking ─────────────────────────
    def update_peak(self, signal_id: int, peak_price: float, peak_tp: str,
                    year: int | None = None, month: int | None = None) -> None:
        """Update highest/lowest price reached and corresponding TP level."""
        path = self._monthly_path(year, month)
        if not os.path.exists(path):
            return
        with _conn(path) as c:
            c.execute(
                "UPDATE signals SET peak_price=?, peak_tp_touched=? WHERE id=?",
                (peak_price, peak_tp, signal_id),
            )

    def get_peak_analysis(self, date_from: str, date_to: str,
                          year: int | None = None, month: int | None = None) -> Dict:
        """Distribution of peak_tp_touched for SL trades in a date range."""
        path = self._monthly_path(year, month)
        if not os.path.exists(path):
            return {}
        with _conn(path) as c:
            rows = c.execute("""
                SELECT COALESCE(peak_tp_touched, 'NONE') AS peak_tp, COUNT(*) AS cnt
                FROM signals
                WHERE status = 'SL'
                  AND created_at BETWEEN ? AND ?
                GROUP BY peak_tp_touched
            """, (date_from, date_to)).fetchall()
        return {r["peak_tp"]: r["cnt"] for r in rows}

    def ensure_month_db(self, year: int | None = None, month: int | None = None) -> str:
        """Create monthly DB if it doesn't exist yet (called at month rollover)."""
        return self._init_monthly(year, month)

    # ─────────────────────────────────────────────────────
    #  Dynamic Watchlist  (Top 30 by volume, refreshed 6×/day)
    # ─────────────────────────────────────────────────────
    def save_dynamic_watchlist(
        self, symbols: List[str], fetched_at: datetime | None = None
    ) -> None:
        ts = (fetched_at or datetime.now()).isoformat()
        with _conn(self.config_db) as c:
            c.execute("DELETE FROM dynamic_watchlist")
            c.executemany(
                "INSERT INTO dynamic_watchlist(symbol, rank, fetched_at) VALUES(?,?,?)",
                [(sym, rank + 1, ts) for rank, sym in enumerate(symbols)],
            )

    def get_dynamic_watchlist(self) -> List[str]:
        with _conn(self.config_db) as c:
            rows = c.execute(
                "SELECT symbol FROM dynamic_watchlist ORDER BY rank ASC"
            ).fetchall()
        return [r["symbol"] for r in rows]

    def get_dynamic_watchlist_age(self) -> int:
        """Minutes since last fetch. Returns 9999 if table is empty."""
        with _conn(self.config_db) as c:
            row = c.execute(
                "SELECT fetched_at FROM dynamic_watchlist ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row or not row["fetched_at"]:
            return 9999
        try:
            fetched = datetime.fromisoformat(row["fetched_at"])
            return int((datetime.now() - fetched).total_seconds() / 60)
        except Exception:
            return 9999

    # ─────────────────────────────────────────────────────
    #  Expiry management
    # ─────────────────────────────────────────────────────
    def expire_old_signals(self) -> int:
        """Mark timed-out OPEN signals as EXPIRED. Returns count."""
        path = self._monthly_path()
        if not os.path.exists(path):
            return 0
        with _conn(path) as c:
            cur = c.execute("""
                UPDATE signals
                SET status='EXPIRED', closed_at=CURRENT_TIMESTAMP
                WHERE status='OPEN' AND expires_at < CURRENT_TIMESTAMP
            """)
            count = cur.rowcount
        # Sync all newly expired signals to lifetime
        if count > 0:
            with _conn(path) as c:
                expired_ids = [
                    r["id"] for r in c.execute(
                        "SELECT id FROM signals WHERE status='EXPIRED' AND closed_at >= datetime('now','-1 minute')"
                    ).fetchall()
                ]
            for sid in expired_ids:
                self._sync_to_lifetime(sid)
        return count
