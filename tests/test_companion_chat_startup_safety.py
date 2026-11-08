"""Regression checks for safe Android secure-chat startup."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "android-companion/app/src/main/java/com/mark56/companion/ChatActivity.kt"
MAIN = ROOT / "android-companion/app/src/main/java/com/mark56/companion/MainActivity.kt"


class CompanionChatStartupSafetyTests(unittest.TestCase):
    def test_optional_voice_services_are_not_started_during_chat_launch(self):
        source = CHAT.read_text(encoding="utf-8")
        on_create = source.split("override fun onCreate", 1)[1].split("override fun onResume", 1)[0]
        self.assertNotIn("initializeVoice()", on_create)
        self.assertIn("voiceInitializationAttempted = true", source)
        self.assertIn("initializeVoice()", source.split("private fun toggleListening", 1)[1])

    def test_chat_launch_credential_reads_are_inside_exception_guard(self):
        source = MAIN.read_text(encoding="utf-8")
        button = source.split('val chatButton = actionButton("OPEN JARVIS CHAT', 1)[1].split(
            "val featuresCard", 1
        )[0]
        self.assertLess(button.index("try {"), button.index("tokenStore.read()"))
        self.assertLess(button.index("try {"), button.index("settings.hasCommandScope()"))
        self.assertIn("Secure chat could not read this phone's pairing", button)


if __name__ == "__main__":
    unittest.main()
