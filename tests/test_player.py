"""Testa a lógica de seleção de segmentos e controle de delay do PlayerManager."""

import unittest
from datetime import datetime, timedelta
from pathlib import Path

from tests._helpers import make_config, TempSegments
from modules.player import PlayerManager


class ParseSegmentTimeTests(unittest.TestCase):
    def test_parses_valid_timestamp(self):
        player = PlayerManager(make_config())
        seg = Path("20260517_143000.ts")
        self.assertEqual(
            player._parse_segment_time(seg),
            datetime(2026, 5, 17, 14, 30, 0),
        )

    def test_returns_none_on_invalid_name(self):
        player = PlayerManager(make_config())
        self.assertIsNone(player._parse_segment_time(Path("garbage.ts")))
        self.assertIsNone(player._parse_segment_time(Path("not-a-date.ts")))


class GetReadySegmentsTests(unittest.TestCase):
    def test_only_returns_segments_older_than_delay(self):
        with TempSegments() as ts:
            now = datetime.now()
            # 3 segmentos antigos (prontos) e 2 recentes (não prontos)
            ready_paths = [
                ts.create_at(now - timedelta(seconds=300)),
                ts.create_at(now - timedelta(seconds=250)),
                ts.create_at(now - timedelta(seconds=200)),
            ]
            ts.create_at(now - timedelta(seconds=60))
            ts.create_at(now - timedelta(seconds=10))

            config = make_config(
                segment_folder=str(ts.dir),
                delay_seconds=120,
            )
            player = PlayerManager(config)

            ready = player._get_ready_segments()
            self.assertEqual(
                sorted(p.name for p in ready),
                sorted(p.name for p in ready_paths),
            )

    def test_empty_folder_returns_empty_list(self):
        with TempSegments() as ts:
            config = make_config(segment_folder=str(ts.dir))
            player = PlayerManager(config)
            self.assertEqual(player._get_ready_segments(), [])

    def test_ignores_files_with_invalid_names(self):
        with TempSegments() as ts:
            now = datetime.now()
            valid = ts.create_at(now - timedelta(seconds=300))
            (ts.dir / "junk.ts").write_bytes(b"x")
            (ts.dir / "20260101_999999.ts").write_bytes(b"x")  # hora inválida

            config = make_config(segment_folder=str(ts.dir), delay_seconds=60)
            player = PlayerManager(config)
            ready = player._get_ready_segments()
            self.assertEqual([p.name for p in ready], [valid.name])

    def test_returns_segments_in_chronological_order(self):
        with TempSegments() as ts:
            now = datetime.now()
            # Cria fora de ordem para validar que o sort funciona
            ts.create_at(now - timedelta(seconds=200))
            ts.create_at(now - timedelta(seconds=300))
            ts.create_at(now - timedelta(seconds=250))

            config = make_config(segment_folder=str(ts.dir), delay_seconds=60)
            player = PlayerManager(config)
            ready = player._get_ready_segments()
            self.assertEqual(
                [p.name for p in ready],
                sorted(p.name for p in ready),
            )


class BufferProgressTests(unittest.TestCase):
    def test_empty_folder_progress_is_zero(self):
        with TempSegments() as ts:
            config = make_config(
                segment_folder=str(ts.dir),
                delay_seconds=120,
                segment_duration=5,
            )
            player = PlayerManager(config)
            self.assertEqual(player._buffer_progress(), 0.0)

    def test_progress_caps_at_one(self):
        with TempSegments() as ts:
            # delay 60s / 5s por segmento = precisa de 12 segmentos.
            # Vamos criar 30, então o progresso deve saturar em 1.0.
            for i in range(30):
                ts.create_at(datetime.now() - timedelta(seconds=i * 5))
            config = make_config(
                segment_folder=str(ts.dir),
                delay_seconds=60,
                segment_duration=5,
            )
            player = PlayerManager(config)
            self.assertEqual(player._buffer_progress(), 1.0)

    def test_progress_is_proportional(self):
        with TempSegments() as ts:
            # delay 120s / 5s = precisa de 24 segmentos. Criamos 6 → 25%.
            for i in range(6):
                ts.create_at(datetime.now() - timedelta(seconds=i * 5))
            config = make_config(
                segment_folder=str(ts.dir),
                delay_seconds=120,
                segment_duration=5,
            )
            player = PlayerManager(config)
            self.assertAlmostEqual(player._buffer_progress(), 0.25, places=4)


class MpvCommandTests(unittest.TestCase):
    def test_screen_flags_interpolate_monitor_index(self):
        """Regressão: --fs-screen precisa ser f-string (não literal '{monitor}')."""
        player = PlayerManager(make_config(mpv_fullscreen_monitor=2))
        cmd = player._build_mpv_cmd(Path("/tmp/fake.ts"))

        # Nenhuma flag pode conter '{monitor}' literal
        for arg in cmd:
            self.assertNotIn(
                "{monitor}", arg,
                f"--fs-screen ou --screen não interpolou: {arg!r}",
            )
        self.assertIn("--screen=2", cmd)
        self.assertIn("--fs-screen=2", cmd)

    def test_defaults_to_monitor_zero(self):
        config = make_config()
        config.pop("mpv_fullscreen_monitor", None)
        player = PlayerManager(config)
        cmd = player._build_mpv_cmd(Path("/tmp/fake.ts"))
        self.assertIn("--screen=0", cmd)
        self.assertIn("--fs-screen=0", cmd)

    def test_first_segment_is_last_positional_arg(self):
        """MPV interpreta o último arg posicional como o arquivo a tocar."""
        player = PlayerManager(make_config())
        seg = Path("/tmp/specific.ts")
        cmd = player._build_mpv_cmd(seg)
        # Compara como Path para neutralizar separador POSIX vs Windows
        self.assertEqual(Path(cmd[-1]), seg)


class DelayControlTests(unittest.TestCase):
    def test_set_delay_clamps_to_minimum_10(self):
        player = PlayerManager(make_config(delay_seconds=120))
        player.set_delay(5)
        self.assertEqual(player.get_delay(), 10)
        player.set_delay(-100)
        self.assertEqual(player.get_delay(), 10)

    def test_set_delay_accepts_valid_values(self):
        player = PlayerManager(make_config(delay_seconds=120))
        player.set_delay(300)
        self.assertEqual(player.get_delay(), 300)

    def test_set_delay_updates_config_dict(self):
        # Critical: main.py espera que set_delay mute config compartilhado
        config = make_config(delay_seconds=120)
        player = PlayerManager(config)
        player.set_delay(180)
        self.assertEqual(config["delay_seconds"], 180)


if __name__ == "__main__":
    unittest.main()
