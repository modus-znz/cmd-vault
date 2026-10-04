"""
cmd_vault.cli

Command line interface for cmd-vault (cm).
Supports 'cm suggest', 'cm record', 'cm search', 'cm dedup', 'cm compress', and 'cm audit'.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .vault import CommandVault


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cm",
        description="cmd-vault: Fast local CLI command history & winning methodology memory system",
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--vault-dir", type=str, default=None, help="Custom path for vault database directory"
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Available commands")

    # cm suggest [query]
    suggest_parser = subparsers.add_parser(
        "suggest", help="Suggest commands matching context or query keywords"
    )
    suggest_parser.add_argument("query", nargs="?", default="", help="Query keywords or prompt")
    suggest_parser.add_argument(
        "-l", "--limit", type=int, default=10, help="Maximum number of suggestions (default: 10)"
    )
    suggest_parser.add_argument(
        "-c", "--category", type=str, default=None, help="Filter suggestions by category"
    )
    suggest_parser.add_argument(
        "--json", action="store_true", help="Output results in JSON format"
    )

    # cm record <command>
    record_parser = subparsers.add_parser(
        "record", help="Record a command or methodology pattern into vault memory"
    )
    record_parser.add_argument("command", type=str, help="CLI command line string to record")
    record_parser.add_argument(
        "-d", "--description", type=str, default="", help="Optional description of command purpose"
    )
    record_parser.add_argument(
        "-c", "--category", type=str, default="command", help="Category label (default: command)"
    )
    record_parser.add_argument(
        "-t", "--tags", type=str, default="", help="Comma-separated tags"
    )
    record_parser.add_argument(
        "-e", "--exit-code", type=int, default=0, help="Command execution exit code (default: 0)"
    )
    record_parser.add_argument(
        "--json", action="store_true", help="Output result in JSON format"
    )

    # cm search [query]
    search_parser = subparsers.add_parser("search", help="Search history entries by query")
    search_parser.add_argument("query", type=str, help="Search query string")
    search_parser.add_argument(
        "-l", "--limit", type=int, default=10, help="Maximum search results (default: 10)"
    )
    search_parser.add_argument(
        "--json", action="store_true", help="Output results in JSON format"
    )

    # cm dedup
    subparsers.add_parser("dedup", help="Perform deduplication audit across vault entries")

    # cm compress
    compress_parser = subparsers.add_parser(
        "compress", help="Compress vault entries into a gzip JSON archive"
    )
    compress_parser.add_argument(
        "-o", "--output", type=str, default=None, help="Archive output filename"
    )

    # cm audit
    audit_parser = subparsers.add_parser("audit", help="Audit vault storage, stats, and database mode")
    audit_parser.add_argument("--json", action="store_true", help="Output audit metrics as JSON")

    return parser


def main(args: Optional[List[str]] = None) -> int:
    parser = create_parser()
    parsed_args = parser.parse_args(args)

    vault = CommandVault(vault_dir=parsed_args.vault_dir)

    if parsed_args.subcommand == "suggest":
        suggestions = vault.suggest(
            query=parsed_args.query,
            category=parsed_args.category,
            limit=parsed_args.limit,
        )
        if parsed_args.json:
            print(json.dumps(suggestions, indent=2))
        else:
            if not suggestions:
                print(f"No command suggestions found for query: '{parsed_args.query}'")
                return 0
            print(f"--- CMD-VAULT SUGGESTIONS ({len(suggestions)} matches) ---")
            for idx, item in enumerate(suggestions, 1):
                desc_str = f" - {item['description']}" if item['description'] else ""
                print(f"[{idx}] {item['command']}{desc_str}")
                print(f"    Relevance Score: {item['score']} | Executions: {item['usage_count']} | Category: {item['category']}")
        return 0

    elif parsed_args.subcommand == "record":
        res = vault.record_command(
            command=parsed_args.command,
            description=parsed_args.description,
            category=parsed_args.category,
            tags=parsed_args.tags,
            exit_code=parsed_args.exit_code,
        )
        if parsed_args.json:
            print(json.dumps(res, indent=2))
        else:
            status_str = "Deduplicated & Updated" if res["is_duplicate"] else "Recorded New"
            print(f"[SUCCESS] {status_str} command in vault!")
            print(f"  ID: {res['id']} | Hash: {res['hash'][:12]} | Executions: {res['usage_count']}")
        return 0

    elif parsed_args.subcommand == "search":
        results = vault.suggest(query=parsed_args.query, limit=parsed_args.limit)
        if parsed_args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"--- SEARCH RESULTS FOR '{parsed_args.query}' ({len(results)} matches) ---")
            for idx, item in enumerate(results, 1):
                print(f"[{idx}] {item['command']} (Score: {item['score']})")
        return 0

    elif parsed_args.subcommand == "dedup":
        res = vault.deduplicate()
        print(f"[DEDUP] Merged {res['groups_merged']} duplicate groups, removed {res['entries_removed']} redundant records.")
        return 0

    elif parsed_args.subcommand == "compress":
        archive_path = vault.compress_archive(archive_name=parsed_args.output)
        print(f"[COMPRESS] Successfully created gzip archive: {archive_path}")
        return 0

    elif parsed_args.subcommand == "audit":
        metrics = vault.audit()
        if parsed_args.json:
            print(json.dumps(metrics, indent=2))
        else:
            print("=" * 60)
            print(" CMD-VAULT SYSTEM AUDIT")
            print("=" * 60)
            print(f" Vault Directory : {metrics['vault_dir']}")
            print(f" SQLite Mode     : {metrics['journal_mode']}")
            print(f" Total Entries   : {metrics['total_entries']}")
            print(f" Unique Hashes   : {metrics['unique_hashes']}")
            print(f" Total Executions: {metrics['total_usage_sum']}")
            print(f" DB Disk Size    : {metrics['db_size_bytes']} bytes")
            print(f" Archives Count  : {metrics['archive_count']} ({metrics['archive_size_bytes']} bytes)")
            print("=" * 60)
        return 0

    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
