"""
cmd_vault.vault

Core CommandVault engine providing SQLite WAL indexing, SHA-256 deduplication,
n-gram + BM25 hybrid semantic search, and gzip archive compression.
"""

from __future__ import annotations

import contextlib
import fcntl
import gzip
import hashlib
import json
import math
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union


def extract_ngrams(text: str, n_range: Tuple[int, int] = (3, 4)) -> Set[str]:
    """Extract character n-grams and word tokens for sub-word semantic vector matching."""
    tokens = re.findall(r"\w+", text.lower())
    ngrams = set(tokens)
    clean_text = " ".join(tokens)
    for n in range(n_range[0], n_range[1] + 1):
        for i in range(len(clean_text) - n + 1):
            ngrams.add(clean_text[i : i + n])
    return ngrams


def cosine_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    """Calculate Cosine similarity between two token n-gram sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a.intersection(set_b))
    denominator = math.sqrt(len(set_a) * len(set_b))
    return intersection / denominator if denominator > 0 else 0.0


@contextlib.contextmanager
def exclusive_lock(lock_path: Path):
    """POSIX flock exclusive process locking."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.touch(exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


class CommandVault:
    """Fast local CLI command history & methodology vault with SQLite WAL index & SHA-256 deduplication."""

    def __init__(self, vault_dir: Optional[Union[str, Path]] = None):
        if vault_dir is None:
            self.vault_dir = Path.home() / ".cmd_vault"
        else:
            self.vault_dir = Path(vault_dir)

        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.vault_dir / "vault.db"
        self.archive_dir = self.vault_dir / "archives"
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.vault_dir / ".vault.lock"

        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initialize SQLite database with WAL mode and performance pragmas."""
        with exclusive_lock(self.lock_path):
            conn = self._get_connection()
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                conn.execute("PRAGMA mmap_size=268435456;")
                conn.execute("PRAGMA cache_size=-64000;")
                conn.execute("PRAGMA temp_store=MEMORY;")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS command_entries (
                        id TEXT PRIMARY KEY,
                        command TEXT NOT NULL,
                        description TEXT,
                        category TEXT DEFAULT 'command',
                        tags TEXT DEFAULT '',
                        exit_code INTEGER DEFAULT 0,
                        hash TEXT UNIQUE NOT NULL,
                        tokens_json TEXT,
                        usage_count INTEGER DEFAULT 1,
                        created_at REAL,
                        updated_at REAL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_hash ON command_entries(hash);")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON command_entries(category);")
                conn.commit()
            finally:
                conn.close()

    def record_command(
        self,
        command: str,
        description: str = "",
        category: str = "command",
        tags: str = "",
        exit_code: int = 0,
    ) -> Dict:
        """
        Record a CLI command or methodology entry into the vault.
        Deduplicates automatically using SHA-256 hash.
        """
        cmd_clean = command.strip()
        if not cmd_clean:
            raise ValueError("Command cannot be empty")

        cmd_hash = hashlib.sha256(cmd_clean.encode("utf-8")).hexdigest()
        now = time.time()

        with exclusive_lock(self.lock_path):
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                existing = cursor.execute(
                    "SELECT id, usage_count, description, tags FROM command_entries WHERE hash = ?",
                    (cmd_hash,),
                ).fetchone()

                if existing:
                    entry_id = existing["id"]
                    new_count = existing["usage_count"] + 1
                    updated_desc = description if description else existing["description"]
                    updated_tags = tags if tags else existing["tags"]

                    cursor.execute(
                        """
                        UPDATE command_entries
                        SET usage_count = ?, description = ?, tags = ?, exit_code = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (new_count, updated_desc, updated_tags, exit_code, now, entry_id),
                    )
                    conn.commit()
                    return {
                        "id": entry_id,
                        "command": cmd_clean,
                        "hash": cmd_hash,
                        "usage_count": new_count,
                        "is_duplicate": True,
                        "action": "updated",
                    }
                else:
                    entry_id = f"cmd_{cmd_hash[:12]}"
                    ngrams = extract_ngrams(f"{cmd_clean} {description} {tags}")
                    ngrams_json = json.dumps(list(ngrams))

                    cursor.execute(
                        """
                        INSERT INTO command_entries
                        (id, command, description, category, tags, exit_code, hash, tokens_json, usage_count, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                        """,
                        (
                            entry_id,
                            cmd_clean,
                            description,
                            category,
                            tags,
                            exit_code,
                            cmd_hash,
                            ngrams_json,
                            now,
                            now,
                        ),
                    )
                    conn.commit()
                    return {
                        "id": entry_id,
                        "command": cmd_clean,
                        "hash": cmd_hash,
                        "usage_count": 1,
                        "is_duplicate": False,
                        "action": "inserted",
                    }
            finally:
                conn.close()

    def suggest(self, query: str = "", category: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """
        Suggest commands matching a query string using BM25 keyword matching + n-gram vector cosine similarity.
        Boosts results by usage count.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if category:
                rows = cursor.execute("SELECT * FROM command_entries WHERE category = ?", (category,)).fetchall()
            else:
                rows = cursor.execute("SELECT * FROM command_entries").fetchall()

            if not query.strip():
                # If query is empty, return top commands by usage count & recency
                sorted_rows = sorted(rows, key=lambda r: (r["usage_count"], r["updated_at"]), reverse=True)
                results = []
                for r in sorted_rows[:limit]:
                    results.append(
                        {
                            "id": r["id"],
                            "command": r["command"],
                            "description": r["description"],
                            "category": r["category"],
                            "tags": r["tags"],
                            "score": 1.0,
                            "usage_count": r["usage_count"],
                        }
                    )
                return results

            query_ngrams = extract_ngrams(query)
            query_tokens = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 1]

            results = []
            for r in rows:
                cmd_text = r["command"].lower()
                desc_text = (r["description"] or "").lower()
                tags_text = (r["tags"] or "").lower()
                full_text = f"{cmd_text} {desc_text} {tags_text}"

                # BM25 / Keyword exact substring matching score
                bm25_score = 0.0
                for t in query_tokens:
                    if t in cmd_text:
                        bm25_score += 20.0
                    if t in desc_text:
                        bm25_score += 10.0
                    if t in tags_text:
                        bm25_score += 15.0

                # Dense Vector N-Gram Cosine Similarity Score
                entry_ngrams = set(json.loads(r["tokens_json"] or "[]"))
                vec_score = cosine_similarity(query_ngrams, entry_ngrams) * 40.0

                # Frequency multiplier boost
                frequency_boost = math.log1p(r["usage_count"]) * 5.0

                total_score = bm25_score + vec_score + frequency_boost

                if total_score > 0.5:
                    results.append(
                        {
                            "id": r["id"],
                            "command": r["command"],
                            "description": r["description"],
                            "category": r["category"],
                            "tags": r["tags"],
                            "score": round(total_score, 2),
                            "usage_count": r["usage_count"],
                            "exit_code": r["exit_code"],
                        }
                    )

            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:limit]
        finally:
            conn.close()

    def deduplicate(self) -> Dict[str, int]:
        """
        Perform a full sweep scan of the vault to verify SHA-256 deduplication integrity.
        Merges any entries with identical command hashes.
        """
        with exclusive_lock(self.lock_path):
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                rows = cursor.execute("SELECT id, command, hash, usage_count FROM command_entries").fetchall()

                hash_map: Dict[str, List[sqlite3.Row]] = {}
                for r in rows:
                    h = r["hash"]
                    if h not in hash_map:
                        hash_map[h] = []
                    hash_map[h].append(r)

                merged_count = 0
                removed_count = 0

                for h, entries in hash_map.items():
                    if len(entries) > 1:
                        primary = entries[0]
                        total_usage = sum(e["usage_count"] for e in entries)
                        primary_id = primary["id"]

                        cursor.execute(
                            "UPDATE command_entries SET usage_count = ? WHERE id = ?",
                            (total_usage, primary_id),
                        )
                        for duplicate in entries[1:]:
                            cursor.execute("DELETE FROM command_entries WHERE id = ?", (duplicate["id"],))
                            removed_count += 1
                        merged_count += 1

                conn.commit()
                return {"groups_merged": merged_count, "entries_removed": removed_count}
            finally:
                conn.close()

    def compress_archive(self, archive_name: Optional[str] = None) -> Path:
        """
        Export current vault entries to a timestamped gzip-compressed JSON archive file in archives directory.
        """
        with exclusive_lock(self.lock_path):
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                rows = cursor.execute("SELECT * FROM command_entries").fetchall()
                entries_data = [dict(r) for r in rows]

                if not archive_name:
                    timestamp = time.strftime("%Y%m%d_%H%M%S")
                    archive_name = f"cmd_vault_export_{timestamp}.json.gz"

                archive_path = self.archive_dir / archive_name
                json_bytes = json.dumps(entries_data, indent=2).encode("utf-8")

                with gzip.open(archive_path, "wb") as f_out:
                    f_out.write(json_bytes)

                return archive_path
            finally:
                conn.close()

    def audit(self) -> Dict:
        """
        Audit the command vault performance metrics, entry counts, and disk usage.
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            total_entries = cursor.execute("SELECT COUNT(*) FROM command_entries").fetchone()[0]
            total_usage = cursor.execute("SELECT SUM(usage_count) FROM command_entries").fetchone()[0] or 0
            unique_hashes = cursor.execute("SELECT COUNT(DISTINCT hash) FROM command_entries").fetchone()[0]

            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
            archive_files = list(self.archive_dir.glob("*.json.gz"))
            archive_size = sum(f.stat().st_size for f in archive_files)

            journal_mode = cursor.execute("PRAGMA journal_mode;").fetchone()[0]

            return {
                "total_entries": total_entries,
                "total_usage_sum": total_usage,
                "unique_hashes": unique_hashes,
                "db_size_bytes": db_size,
                "archive_count": len(archive_files),
                "archive_size_bytes": archive_size,
                "journal_mode": journal_mode,
                "vault_dir": str(self.vault_dir),
            }
        finally:
            conn.close()
