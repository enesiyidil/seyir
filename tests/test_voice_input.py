import unittest
from typing import ClassVar
from unittest.mock import patch

from bildirim import voice_input as voice


class VoiceCommandsTest(unittest.TestCase):
    apps: ClassVar[list[dict[str, str]]] = [
        {"id": voice._CODEX, "name": "ChatGPT"},
        {"id": voice._TEAMS, "name": "Microsoft Teams"},
        {"id": "com.apple.Safari", "name": "Safari"},
    ]

    def setUp(self):
        self.dialog = voice.TeamsDraft()
        self.native = self.enterContext(
            patch.object(voice, "native", return_value={"reply": "ok"})
        )

    def say(self, text, mode="desktop"):
        return voice.local_command(
            text, {"mode": mode}, self.apps, voice._CODEX, self.dialog
        )

    def test_recorded_codex_draft_preserves_text(self):
        for command in [
            "Ekrandaki kod Ex'e şu komutu yaz Merhaba, nasılsın?",
            "Codex e Merhaba, nasılsın? yaz",
            "Cotex'e Merhaba, nasılsın? yaz",
            "Kotekse Merhaba, nasılsın? yaz",
            "Koldeks’e Merhaba, nasılsın? yaz",
        ]:
            self.say(command)
            req = self.native.call_args.kwargs
            self.assertEqual(
                (req["op"], req["id"], req["text"], req["submit"]),
                ("write", voice._CODEX, "Merhaba, nasılsın?", "no"),
            )

    def test_draft_and_submit_are_separate(self):
        for phrase, body, submit in [
            ("Codex’e merhaba yaz ama gönderme", "merhaba", "no"),
            ("Codex’e merhaba yaz ve gönder", "merhaba", "yes"),
            (
                "Codex’e şunu yaz: belgeyi düzenle ve gönder",
                "belgeyi düzenle ve gönder",
                "no",
            ),
            ("Codex’e şunu yaz ama gönderme: merhaba", "merhaba", "no"),
        ]:
            self.say(phrase)
            req = self.native.call_args.kwargs
            self.assertEqual((req["text"], req["submit"]), (body, submit))
        self.say("gönder")
        self.assertEqual(self.native.call_args.kwargs["op"], "send")

    def test_space_and_page(self):
        with (
            patch.object(voice, "_switch_space", return_value="geçildi") as space,
            patch.object(voice.desk, "scroll") as scroll,
            patch.object(voice.desk, "require_input"),
        ):
            self.say("ekranı sağa kaydır")
            space.assert_called_once_with("sag")
            scroll.assert_not_called()
            self.say("sayfayı sağa kaydır")
            scroll.assert_called_once_with(dx=6, dy=0)

    def test_space_requires_macos_change_notification(self):
        import plistlib

        prefs = plistlib.dumps({"AppleSymbolicHotKeys": {}})
        with patch.object(voice.subprocess, "check_output", return_value=prefs):
            self.native.side_effect = [{"changed": False}, {"changed": True}]
            self.assertIn("bildirmedi", self.say("Ekranı sağa kaydır"))
            self.assertIn("geçildi", self.say("Ekranı sağa kaydır"))
            self.native.assert_called_with(op="space", key="124", flags=str(1 << 18))

    def test_only_latest_codex_receipt_can_be_used_once(self):
        self.native.side_effect = [
            {"reply": "Taslakta.", "receipt": "digest"},
            {"reply": "ok"},
            {"reply": "ok"},
        ]
        self.say("Codex'e merhaba yaz")
        self.say("gönder")
        self.assertEqual(self.native.call_args.kwargs["receipt"], "digest")
        self.say("gönder")
        self.assertEqual(self.native.call_args.kwargs["receipt"], "")

    def test_window_does_not_write_to_another_app(self):
        self.assertIn("Mac-M4", self.say("Teams’ten Ali’ye merhaba yaz", "window"))
        self.native.assert_not_called()

    def test_apps(self):
        self.assertIn("Safari", self.say("hangi uygulamalar açık?"))
        self.say("Safari’ye geç")
        self.native.assert_called_once_with(op="activate", id="com.apple.Safari")

    def test_teams_name_and_body(self):
        self.say("Teams'ten Ayşe Yılmaz'a şunu yaz: Rapor hazır, bakabilir misin?")
        req = self.native.call_args.kwargs
        self.assertEqual(
            (req["recipient"], req["text"], req["submit"]),
            ("Ayşe Yılmaz", "Rapor hazır, bakabilir misin?", "no"),
        )

    def test_teams_dialog(self):
        self.assertIn("kime", self.say("Teams’ten birine mesaj yaz"))
        self.assertIn("ne yazayım", self.say("Ayşe Yılmaz"))
        self.native.assert_not_called()
        self.say("Toplantı on dakika sonra.")
        req = self.native.call_args.kwargs
        self.assertEqual(
            (req["recipient"], req["text"], req["submit"]),
            ("Ayşe Yılmaz", "Toplantı on dakika sonra.", "no"),
        )

    def test_ambiguous_recipient_preserves_draft_for_retry(self):
        self.native.side_effect = [
            {"error": "E-posta söyle.", "code": "recipient"},
            {"reply": "ok"},
        ]
        self.say("Teams’ten Ece’ye günaydın yaz")
        self.say("ece@example.org")
        req = self.native.call_args.kwargs
        self.assertEqual(
            (req["recipient"], req["text"], req["submit"]),
            ("ece@example.org", "günaydın", "no"),
        )

    def test_cancel_pending_message(self):
        self.say("Teams’ten Ayşe Yılmaz’a mesaj yaz")
        self.assertIn("iptal", self.say("vazgeç"))
        self.native.assert_not_called()

    def test_local_language_model_cannot_change_recipient_or_body(self):
        import json

        request = "Teams üzerinden Ece Kaya için bir taslak hazırlar mısın? Mesajım: Rapor hazır."
        for person, text in [
            ("Başka Kişi", "Rapor hazır."),
            ("Ece Kaya", "Eklenmiş bir vaat."),
        ]:
            model = {"draft": True, "recipient": person, "text": text}
            answer = {"choices": [{"message": {"content": json.dumps(model)}}]}
            with patch("bildirim.mail.qwen._post_chat", return_value=answer):
                self.assertIn(
                    "doğrulayamadım",
                    voice.natural_command(request, self.apps, self.dialog),
                )
                self.native.assert_not_called()

    def test_no_submit_while_waiting_for_recipient(self):
        self.say("Teams’ten birine mesaj yaz")
        self.assertIn("tamamla", self.say("gönder"))
        self.native.assert_not_called()

    def test_model_not_called_for_reported_command(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from bildirim import voice_control

        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data").mkdir()
            with (
                patch.object(voice_control, "project_root", return_value=root),
                patch.object(
                    voice_control, "read_session", return_value={"mode": "desktop"}
                ),
                patch.object(
                    voice_control,
                    "application_context",
                    return_value=(self.apps, voice._CODEX),
                ),
                patch.object(voice_control, "_grok_action") as model,
            ):
                voice_control.handle_spoken("Ekrandaki kod Ex'e şu komutu yaz merhaba")
                model.assert_not_called()
                self.assertEqual(self.native.call_args.kwargs["submit"], "no")


if __name__ == "__main__":
    unittest.main()
