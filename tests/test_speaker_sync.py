import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from audio_output import COMBINED_WIRED, COMBINED_BT
from speaker_sync import offsets, validate_ms, save_sync, read_sync, apply_sync


class SpeakerSyncTests(unittest.TestCase):
    def test_signed_offsets_use_only_nonnegative_latency(self):
        for value in (-500, -3, 0, 1, 500):
            plan = offsets(value)
            self.assertEqual(plan[COMBINED_WIRED.split('/',1)[1]], max(value,0)*1000000)
            self.assertEqual(plan[COMBINED_BT.split('/',1)[1]], max(-value,0)*1000000)

    def test_validation(self):
        for value in (True, 1.5, '10', None, -501, 501):
            with self.assertRaises(ValueError): validate_ms(value)

    def test_persistence_and_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Mock(return_value='[]')
            save_sync(directory, 3, run)
            self.assertEqual(read_sync(directory), 3)
            run.side_effect = RuntimeError('Unavailable')
            with self.assertRaises(RuntimeError): save_sync(directory, 10, run)
            self.assertEqual(read_sync(directory), 3)

    def test_zero_does_not_mutate_existing_zero_nodes(self):
        rows = [{'id':52,'info':{'props':{'node.name':COMBINED_WIRED.split('/',1)[1]},'params':{'Props':[{'latencyOffsetNsec':0}]}}}]
        run = Mock(return_value=json.dumps(rows)); apply_sync(0, run)
        self.assertEqual(run.call_count, 1)

    def test_only_exact_speakers_are_changed(self):
        rows = [{'id':n,'info':{'props':{'node.name':name},'params':{'Props':[{'latencyOffsetNsec':0}]}}} for n,name in [(52,COMBINED_WIRED.split('/',1)[1]),(99,'unrelated')]]
        run=Mock(return_value=json.dumps(rows));apply_sync(10,run)
        self.assertEqual(run.call_count,2)
        self.assertEqual(run.call_args.args[0][2], '52')
        self.assertIn('10000000', run.call_args.args[0][-1])
