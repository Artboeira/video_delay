"""Testa a remoção de segmentos antigos pelo CleanerManager."""

import unittest
from datetime import datetime, timedelta

from tests._helpers import make_config, TempSegments
from modules.cleaner import CleanerManager


class CleanerTests(unittest.TestCase):
    def test_removes_segments_older_than_max_age(self):
        with TempSegments() as ts:
            now = datetime.now()
            old = ts.create_at(now - timedelta(seconds=1200))  # > 600s
            young = ts.create_at(now - timedelta(seconds=60))  # < 600s

            config = make_config(
                segment_folder=str(ts.dir),
                max_segment_age_seconds=600,
            )
            cleaner = CleanerManager(config)
            cleaner._clean()

            self.assertFalse(old.exists(), "segmento antigo deveria ter sido removido")
            self.assertTrue(young.exists(), "segmento recente deveria permanecer")
            self.assertEqual(cleaner.deleted_count, 1)

    def test_ignores_files_with_invalid_names(self):
        with TempSegments() as ts:
            junk = ts.dir / "not_a_segment.ts"
            junk.write_bytes(b"x")
            config = make_config(
                segment_folder=str(ts.dir),
                max_segment_age_seconds=1,
            )
            cleaner = CleanerManager(config)
            cleaner._clean()
            # Arquivo deve permanecer: nome não bate com strptime
            self.assertTrue(junk.exists())
            self.assertEqual(cleaner.deleted_count, 0)

    def test_clean_is_idempotent_on_empty_folder(self):
        with TempSegments() as ts:
            config = make_config(segment_folder=str(ts.dir))
            cleaner = CleanerManager(config)
            cleaner._clean()
            cleaner._clean()
            self.assertEqual(cleaner.deleted_count, 0)

    def test_uses_default_max_age_when_missing(self):
        """Se max_segment_age_seconds não estiver no config, usa default (240)."""
        with TempSegments() as ts:
            now = datetime.now()
            ts.create_at(now - timedelta(seconds=400))  # > 240 (default)
            config = make_config(segment_folder=str(ts.dir))
            config.pop("max_segment_age_seconds")
            cleaner = CleanerManager(config)
            cleaner._clean()
            self.assertEqual(cleaner.deleted_count, 1)


class PurgeAllTests(unittest.TestCase):
    def test_purge_all_removes_every_ts(self):
        with TempSegments() as ts:
            now = datetime.now()
            ts.create_at(now - timedelta(seconds=10))     # recente
            ts.create_at(now - timedelta(seconds=5000))   # antigo
            junk = ts.dir / "not_a_segment.ts"            # nome inválido
            junk.write_bytes(b"x")

            config = make_config(segment_folder=str(ts.dir))
            cleaner = CleanerManager(config)
            removed = cleaner.purge_all()

            self.assertEqual(removed, 3)
            self.assertEqual(list(ts.dir.glob("*.ts")), [])
            # purge_all não mexe no contador de sessão
            self.assertEqual(cleaner.deleted_count, 0)

    def test_purge_all_empty_folder_is_noop(self):
        with TempSegments() as ts:
            config = make_config(segment_folder=str(ts.dir))
            cleaner = CleanerManager(config)
            self.assertEqual(cleaner.purge_all(), 0)

    def test_purge_all_ignores_non_ts_files(self):
        with TempSegments() as ts:
            cfg = ts.dir / "config.json"
            cfg.write_text("{}")
            ts.create_at(datetime.now())

            config = make_config(segment_folder=str(ts.dir))
            cleaner = CleanerManager(config)
            removed = cleaner.purge_all()

            self.assertEqual(removed, 1)
            self.assertTrue(cfg.exists())


if __name__ == "__main__":
    unittest.main()
