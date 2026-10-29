import tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from core import VN, DEFAULT, validate, next_boundary, is_due, Ledger, save_config
class CoreTests(unittest.TestCase):
    def test_timezone_next_day(self):
        now=datetime(2026,10,30,17,16,tzinfo=timezone.utc)
        self.assertEqual(next_boundary('00:17',now),'2026-10-31T00:17:00+07:00')
        self.assertEqual(next_boundary('00:17',datetime(2026,10,31,0,17,tzinfo=VN)),'2026-11-01T00:17:00+07:00')
    def test_due_window_and_skip_late(self):
        self.assertTrue(is_due('00:17',datetime(2026,10,30,17,17,tzinfo=timezone.utc)))
        self.assertTrue(is_due('00:17',datetime(2026,10,31,0,18,59,tzinfo=VN)))
        self.assertFalse(is_due('00:17',datetime(2026,10,31,0,19,tzinfo=VN)))
        self.assertFalse(is_due('00:17',datetime(2026,10,31,0,16,59,tzinfo=VN)))
    def test_config_editable_recipients_time(self):
        config={**DEFAULT,'time':'12:10','recipients':['example_user_1','example_user_2']}
        validate(config)
        for key,value in [('time','24:17'),('time','0:17'),('recipients',[]),('recipients',['duplicate','duplicate'])]:
            with self.assertRaises(ValueError):validate({**config,key:value})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json';save_config(path,config)
            import json
            self.assertEqual(json.loads(path.read_text()),config)
    def test_durable_duplicate_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'ledger.sqlite';first=Ledger(path)
            self.assertTrue(first.reserve('2026-10-31','contact_a','report.pdf'))
            second=Ledger(path)
            self.assertFalse(second.reserve('2026-10-31','contact_a','other.pdf'))
            self.assertTrue(second.reserve('2026-10-31','contact_b','report.pdf'))
            self.assertTrue(second.reserve('2026-11-01','contact_a','report.pdf'))
            first.finish('2026-10-31','contact_a','needs_manual_check')
            self.assertFalse(second.reserve('2026-10-31','contact_a','retry.pdf'))
            first.conn.close();second.conn.close()
if __name__=='__main__':unittest.main()
