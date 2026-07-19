import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from pomowatcher_app.bgm import MpvBgmPlayer


class FakeProcess:
    pid = 1234

    def poll(self):
        return None

    def terminate(self) -> None:
        return None

    def wait(self, timeout: int) -> None:
        return None


class MpvBgmPlayerTest(unittest.TestCase):
    def make_player(self, directory: Path) -> tuple[MpvBgmPlayer, Mock]:
        (directory / "bgm.mp3").write_bytes(b"test")
        adapter = Mock()
        adapter.launch.return_value = FakeProcess()
        adapter.send.return_value = True
        player = MpvBgmPlayer(
            adapter=adapter,
            bgm_dir=directory,
            file_candidates=(),
            muted=False,
            volume=50,
        )
        return player, adapter

    def test_他メディア再生中はmpvを起動しない(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            player, adapter = self.make_player(Path(temporary_directory))
            player.pause("media")
            self.assertFalse(player.start())
            adapter.launch.assert_not_called()

    def test_他メディア終了後はmpvを起動できる(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            player, adapter = self.make_player(Path(temporary_directory))
            player.pause("media")
            player.release("media")
            self.assertTrue(player.start())
            adapter.launch.assert_called_once()

    def test_複数の停止理由がある間はBGMを再開しない(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            player, adapter = self.make_player(Path(temporary_directory))
            player.start()
            player.pause("idle")
            player.pause("media")
            player.release("media")
            self.assertNotIn(["set_property", "pause", False], [call.args[0] for call in adapter.send.call_args_list])
            player.release("idle")
            adapter.send.assert_called_with(["set_property", "pause", False])


if __name__ == "__main__":
    unittest.main()
