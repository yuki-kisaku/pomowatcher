import unittest
from unittest.mock import patch

from pomowatcher_app.windows import media_monitor


class FakeStatus:
    PLAYING = "playing"


class FakePlaybackInfo:
    def __init__(self, status: str) -> None:
        self.playback_status = status


class FakeSession:
    def __init__(self, source: str, status: str) -> None:
        self.source_app_user_model_id = source
        self._status = status

    def get_playback_info(self) -> FakePlaybackInfo:
        return FakePlaybackInfo(self._status)


class FakeManager:
    def __init__(self, *sessions: FakeSession) -> None:
        self._sessions = sessions

    def get_sessions(self) -> tuple[FakeSession, ...]:
        return self._sessions


class WindowsMediaMonitorTest(unittest.TestCase):
    def test_ChromeのYouTube再生を検知する(self) -> None:
        manager = FakeManager(FakeSession("chrome.exe", "playing"))
        with patch.object(
            media_monitor,
            "GlobalSystemMediaTransportControlsSessionPlaybackStatus",
            FakeStatus,
        ):
            self.assertTrue(
                media_monitor.WindowsMediaMonitor._has_other_playing_session(manager)
            )

    def test_一時停止中のChromeは再生中にしない(self) -> None:
        manager = FakeManager(FakeSession("chrome.exe", "paused"))
        with patch.object(
            media_monitor,
            "GlobalSystemMediaTransportControlsSessionPlaybackStatus",
            FakeStatus,
        ):
            self.assertFalse(
                media_monitor.WindowsMediaMonitor._has_other_playing_session(manager)
            )

    def test_自分のmpvは他メディアとして扱わない(self) -> None:
        manager = FakeManager(FakeSession("mpv.exe", "playing"))
        with patch.object(
            media_monitor,
            "GlobalSystemMediaTransportControlsSessionPlaybackStatus",
            FakeStatus,
        ):
            self.assertFalse(
                media_monitor.WindowsMediaMonitor._has_other_playing_session(manager)
            )


if __name__ == "__main__":
    unittest.main()
