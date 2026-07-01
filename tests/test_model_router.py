import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.model_router import ModelRouter


class ModelRouterTests(unittest.TestCase):
    def test_kimi_backup_route_is_networked_and_human_approved(self):
        router = ModelRouter.from_json_file(Path(__file__).resolve().parents[1] / "config" / "model-routing.json")
        route = router.route("cloud_kimi_backup")
        self.assertEqual(route.provider, "kimi_backup")
        self.assertTrue(route.requires_network)
        self.assertTrue(route.requires_human_final_approval)


if __name__ == "__main__":
    unittest.main()
