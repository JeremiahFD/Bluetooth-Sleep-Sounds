import unittest
from audio_output import sink_id_for_speaker, normalize_selected_bluetooth_volume

STATUS="""Audio
 ├─ Sinks:
 │      56. alsa_output.stereo [vol: 1.00]
 │  *   88. bluez_output.02_00_00_00_00_01.1 [vol: 0.40]
 ├─ Sources:
 │      95. bluez_source.02_00_00_00_00_01 [vol: 1.00]
"""

class OutputVolumeTests(unittest.TestCase):
    def test_find_only_exact_bluetooth_sink_not_source(self):
        self.assertEqual(sink_id_for_speaker(STATUS,"02:00:00:00:00:01"),"88")
        self.assertIsNone(sink_id_for_speaker(STATUS,"02:00:00:00:00:02"))
    def test_selected_sink_unity_no_unrelated_changes(self):
        calls=[]
        def runner(args,timeout=15):
            calls.append(args)
            return STATUS if args[:2]==["wpctl","status"] else ""
        self.assertTrue(normalize_selected_bluetooth_volume(
            "02:00:00:00:00:01","pulse/bluez_output.02_00_00_00_00_01.1",runner))
        self.assertEqual(calls,[["wpctl","status","-n"],["wpctl","set-volume","-l","1.0","88","1.0"]])
    def test_manually_selected_bluetooth_output_without_saved_speaker(self):
        calls=[]
        def runner(args,timeout=15):
            calls.append(args)
            return STATUS if args[:2]==["wpctl","status"] else ""
        self.assertTrue(normalize_selected_bluetooth_volume(None,"pulse/bluez_output.02_00_00_00_00_01.1",runner))
        self.assertEqual(calls[-1],["wpctl","set-volume","-l","1.0","88","1.0"])

    def test_non_bluetooth_does_not_touch_sink(self):
        calls=[]
        def runner(*args,**kwargs):
            calls.append(args);return STATUS
        self.assertFalse(normalize_selected_bluetooth_volume("02:00:00:00:00:01","alsa/other",runner))
        self.assertFalse(calls)
if __name__=="__main__":unittest.main()
