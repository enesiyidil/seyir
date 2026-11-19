import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import shlex
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request

from bildirim import cursor_usage
from bildirim.bots.agent_bot import _start_bridge
from bildirim.config import Settings, project_setting
from bildirim.mail import applescript, rules, watcher
from bildirim.mail.store import ProcessedStore


class PublicSetupTest(unittest.TestCase):
    def test_seyir_settings_accept_previous_names(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(project_setting("BRIDGE_PORT", "18765"), "18765")
            os.environ["BILDIRIM_BRIDGE_PORT"] = "12345"
            self.assertEqual(project_setting("BRIDGE_PORT"), "12345")
            os.environ["SEYIR_BRIDGE_PORT"] = "23456"
            self.assertEqual(project_setting("BRIDGE_PORT"), "23456")

    def test_commands_require_user_and_group(self):
        empty = Settings({}, -10, {}, ())
        with self.assertRaises(SystemExit):
            empty.require_users()
        settings = Settings({}, -10, {}, (42,))
        self.assertTrue(settings.permits(-10, 42))
        self.assertFalse(settings.permits(-10, 10))
        self.assertFalse(settings.permits(-11, 42))
        self.assertFalse(empty.permits(-10, 42))

    def test_internal_domains_and_mailbox_follow_local_settings(self):
        mail = rules.MailItem("1", "", "Test <demo@example.org>", "", "", True)
        with patch.dict(os.environ, {"MAIL_INTERNAL_DOMAINS": "EXAMPLE.ORG, sample.org",
                                     "MAIL_ACCOUNT": 'Work "A"', "MAIL_INBOX": "Inbox"}):
            self.assertFalse(rules.is_external(mail))
            self.assertEqual(applescript._mailbox(), r'mailbox "Inbox" of account "Work \"A\""')
        with patch.dict(os.environ, {"MAIL_INTERNAL_DOMAINS": ""}):
            self.assertTrue(rules.is_external(mail))

    def test_failed_mark_read_is_retried(self):
        mailbox = [rules.MailItem("1", "[Bitbucket] example", "", "", "", True)]
        with tempfile.TemporaryDirectory() as directory:
            store = ProcessedStore(Path(directory) / "mail.json")
            settings = Settings({}, -10, {"mail": 2}, (42,))
            with patch.object(applescript, "list_unread", return_value=mailbox), \
                 patch.object(applescript, "mark_read", side_effect=[RuntimeError(), None]) as mark, \
                 contextlib.redirect_stdout(io.StringIO()):
                for _ in range(3):
                    watcher.process_once(settings, store, "")
                self.assertEqual(mark.call_count, 2)
                self.assertTrue(store.get("1")["marked_read"])

    def test_explicit_session_usage(self):
        with patch.dict(os.environ, {"CURSOR_SESSION_TOKEN": "test-user::example"}), \
             patch.object(cursor_usage, "_get_usage_summary", return_value=({"membershipType": "demo"}, "")) as api:
            result = cursor_usage.fetch_usage_summary()
            api.assert_called_once_with("example", "test-user")
            self.assertTrue(result.ok)
            self.assertIn("demo", result.text)

    def test_fresh_hook_setup_preserves_other_commands(self):
        installer = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/install-hooks.py"))
        install = installer["install"]
        with tempfile.TemporaryDirectory(prefix="bildirim setup ") as directory:
            root = Path(directory)
            python = root / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.touch()
            path = root / "cursor/hooks.json"
            path.parent.mkdir()
            path.write_text(json.dumps({"version": 1, "hooks": {"stop": [{"command": "other"}]}}))
            with patch.dict(install.__globals__, {"ROOT": root}), contextlib.redirect_stdout(io.StringIO()):
                install(path.parent, False)
                original = path.read_bytes()
                key = root / "data/bridge.secret"
                secret = key.read_text()
                install(path.parent, False)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(key.read_text(), secret)
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            registrations = json.loads(original)["hooks"]["stop"]
            self.assertEqual(registrations[0], {"command": "other"})
            self.assertEqual(shlex.split(registrations[1]["command"])[0], str(python))

    def test_hook_requires_matching_secret(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch("bildirim.bots.agent_bot.project_root", return_value=Path(directory)):
            mirror = Mock()
            mirror.handle_hook.return_value = {"ok": True}
            server = _start_bridge(mirror, Mock(), 0, "example")
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            url = f"http://127.0.0.1:{server.server_port}/hook"
            for header in ({}, {"X-Bildirim-Secret": "wrong"}):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(urllib.request.Request(url, data=b"{}", headers=header))
                self.assertEqual(error.exception.code, 401)
                error.exception.close()
            mirror.handle_hook.assert_not_called()
            request = urllib.request.Request(url, data=b"{}", headers={"X-Bildirim-Secret": "example"})
            with urllib.request.urlopen(request) as response:
                self.assertTrue(json.load(response)["ok"])
            mirror.handle_hook.assert_called_once_with({})
