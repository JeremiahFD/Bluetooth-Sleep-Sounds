"""Browsing preferences are isolated Pi profile data, not global player settings."""
import tempfile
import unittest
from pathlib import Path
from profiles import ProfileStore

class BrowseProfileTests(unittest.TestCase):
    def test_saved_navigation_differs_per_profile_and_survives_reopen(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"profiles.json"
            store=ProfileStore(path)
            p1=store.change("add",name="Person A")["profiles"][1]["id"]
            p2=store.change("add",name="Person B")["profiles"][2]["id"]
            store.change("enabled",enabled=True)
            store.update_preferences(p1,{"open_now_playing_on_select":True,"show_mini_player":False})
            store.update_preferences(p2,{"open_now_playing_on_select":False,"show_mini_player":True})
            store.update_preferences("none",{"show_mini_player":True})
            reopened=ProfileStore(path)
            self.assertEqual(reopened.data(p1)["preferences"]["open_now_playing_on_select"],True)
            self.assertEqual(reopened.data(p2)["preferences"]["open_now_playing_on_select"],False)
            self.assertEqual(reopened.data(p1)["preferences"]["show_mini_player"],False)
            self.assertEqual(reopened.data(p2)["preferences"]["show_mini_player"],True)
            self.assertNotIn("open_now_playing_on_select",reopened.data("none")["preferences"])
            reopened.change("enabled",enabled=False)
            self.assertEqual(reopened.resolve(p1),"none")
            self.assertEqual(reopened.data("none")["preferences"]["show_mini_player"],True)

if __name__=="__main__":unittest.main()
