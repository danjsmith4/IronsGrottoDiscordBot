import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import storage


class EventBanStorageTests(unittest.TestCase):
    def test_records_survive_reopening_and_remain_guild_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(storage, 'EVENTBAN_DB_PATH', str(Path(directory) / 'bans.db')):
                storage.init_eventban_db()
                storage.insert_eventban(1, 2, 3, 'Bingo', 'Test', 'One week')
                storage.init_eventban_db()
                rows = storage.get_user_eventbans(1, 2)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0][1:4], ('Bingo', 'Test', 'One week'))
                record_id = storage.get_latest_record_id(1, 2)
                self.assertEqual(storage.delete_eventban_by_id(9, record_id), 0)
                self.assertEqual(storage.get_user_eventbans(9, 2), [])
                self.assertEqual(storage.delete_eventbans_for_user(1, 2), 1)
                self.assertEqual(storage.get_user_eventbans(1, 2), [])
