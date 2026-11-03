import unittest

from aux_core.action_router import InteractionActionRouter


class ActionRouterV036Tests(unittest.TestCase):
    def setUp(self):
        self.router = InteractionActionRouter({"enabled": True, "auto_vision": True})
        self.keywords = {"en": ["what do you see", "what am i holding", "what is this"]}

    def test_normal_visual_question_uses_camera_without_slash_command(self):
        out = self.router.route("What am I holding?", language="en", visual_keywords=self.keywords)
        self.assertTrue(out.use_vision)
        self.assertIn("vision", out.actions)

    def test_scene_language_routes_vision(self):
        out = self.router.route("Describe the room around you.", language="en", visual_keywords=self.keywords)
        self.assertTrue(out.use_vision)

    def test_nonvisual_homework_chat_does_not_request_camera(self):
        out = self.router.route("I have some homework due tomorrow.", language="en", visual_keywords=self.keywords)
        self.assertFalse(out.use_vision)

    def test_force_vision_still_overrides_router(self):
        out = self.router.route("hello", force_vision=True, visual_keywords=self.keywords)
        self.assertTrue(out.use_vision)
        self.assertEqual(out.visual_reason, "forced")


if __name__ == "__main__":
    unittest.main()
