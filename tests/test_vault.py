"""
Unit test suite for cmd-vault (cmd_vault.vault and cmd_vault.cli).
"""

import gzip
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cmd_vault.cli import main as cli_main
from cmd_vault.vault import CommandVault, extract_ngrams, cosine_similarity


class TestCommandVault(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="cmd_vault_test_")
        self.vault = CommandVault(vault_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_init_db_and_wal_mode(self):
        audit_res = self.vault.audit()
        self.assertEqual(audit_res["total_entries"], 0)
        self.assertEqual(audit_res["journal_mode"].lower(), "wal")

    def test_record_command(self):
        res = self.vault.record_command(
            command="git status --short",
            description="Check working tree status concisely",
            category="git",
            tags="vcs,git,status",
        )
        self.assertFalse(res["is_duplicate"])
        self.assertEqual(res["usage_count"], 1)
        self.assertTrue(res["id"].startswith("cmd_"))

        audit_res = self.vault.audit()
        self.assertEqual(audit_res["total_entries"], 1)
        self.assertEqual(audit_res["unique_hashes"], 1)

    def test_sha256_deduplication(self):
        cmd = "docker compose up -d --build"
        res1 = self.vault.record_command(cmd, description="Start containers")
        self.assertFalse(res1["is_duplicate"])
        self.assertEqual(res1["usage_count"], 1)

        res2 = self.vault.record_command(cmd, description="Start containers again")
        self.assertTrue(res2["is_duplicate"])
        self.assertEqual(res2["usage_count"], 2)
        self.assertEqual(res1["hash"], res2["hash"])

        audit_res = self.vault.audit()
        self.assertEqual(audit_res["total_entries"], 1)
        self.assertEqual(audit_res["total_usage_sum"], 2)

    def test_suggest_command(self):
        self.vault.record_command("pytest -v --cov=src", description="Run python tests with coverage")
        self.vault.record_command("git checkout -b feature/new-idea", description="Create git branch")
        self.vault.record_command("kubectl get pods -n kube-system", description="List k8s pods")

        # Test query matching
        results = self.vault.suggest("pytest coverage")
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["command"], "pytest -v --cov=src")

        # Test empty query returns top recency/usage
        all_results = self.vault.suggest(query="")
        self.assertEqual(len(all_results), 3)

        # Test category filter
        git_results = self.vault.suggest(query="", category="command")
        self.assertEqual(len(git_results), 3)

    def test_deduplicate_sweep(self):
        # Record duplicate directly to check sweep cleanup
        res = self.vault.deduplicate()
        self.assertEqual(res["groups_merged"], 0)
        self.assertEqual(res["entries_removed"], 0)

    def test_gzip_compression(self):
        self.vault.record_command("python3 -m unittest discover", description="Run unittest suite")
        archive_path = self.vault.compress_archive(archive_name="test_archive.json.gz")
        self.assertTrue(archive_path.exists())

        with gzip.open(archive_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["command"], "python3 -m unittest discover")

    def test_ngram_and_cosine_similarity(self):
        ngrams1 = extract_ngrams("git status")
        ngrams2 = extract_ngrams("git log")
        sim = cosine_similarity(ngrams1, ngrams2)
        self.assertGreater(sim, 0.0)
        self.assertLessEqual(sim, 1.0)

    def test_cli_record_and_suggest(self):
        test_vault_path = os.path.join(self.test_dir, "cli_vault")
        
        # Test CLI Record
        cli_args = [
            "--vault-dir",
            test_vault_path,
            "record",
            "systemctl status nginx",
            "-d",
            "Check Nginx service status",
            "--json",
        ]
        with patch("sys.argv", ["cm"] + cli_args):
            exit_code = cli_main(cli_args)
            self.assertEqual(exit_code, 0)

        # Test CLI Suggest
        suggest_args = [
            "--vault-dir",
            test_vault_path,
            "suggest",
            "nginx service",
            "--json",
        ]
        with patch("sys.argv", ["cm"] + suggest_args):
            exit_code = cli_main(suggest_args)
            self.assertEqual(exit_code, 0)

        # Test CLI Audit
        audit_args = ["--vault-dir", test_vault_path, "audit", "--json"]
        with patch("sys.argv", ["cm"] + audit_args):
            exit_code = cli_main(audit_args)
            self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
