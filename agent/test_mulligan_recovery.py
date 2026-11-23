"""Recognition failures must not permanently discard a live mulligan."""
import unittest

from agent.menu import Regions, CONTINUE
from agent.test_agent import Harness, MenuTests, game_lines, line, bracket, ME


class MulliganRecoveryTests(unittest.TestCase):
    def test_timeout_keeps_choice_pending_and_recognition_can_recover(self):
        rows = [line('DebugPrintEntityChoices', f'id=1 Player={ME} TaskList=1 ChoiceType=MULLIGAN CountMin=0 CountMax=3')]
        rows += [line('DebugPrintEntityChoices', f'  Entities[{i}]={bracket(e, "HAND")}')
                 for i, e in enumerate((60, 61, 62))]
        harness = Harness(game_lines() + rows)
        agent = harness.agent
        agent.recover = True
        agent.mulligan_ready = lambda: False
        agent.mulligan_timeout = 1
        self.assertEqual(harness.settled_step(), 'animating')
        harness.clock.sleep(2)
        self.assertEqual(agent.step(), 'animating')
        self.assertIsNone(agent.handled_choice)
        self.assertEqual(harness.inputs.gestures, [])
        agent.mulligan_ready = lambda: True
        agent._act_on_choice = lambda game: 'recognized_again'
        self.assertEqual(agent.step(), 'recognized_again')

    def test_glow_shift_preserves_pattern_but_flat_patch_does_not(self):
        reference = [v for _ in range(30) for v in (30, 60, 90, 210, 220, 230)]
        shifted = [v + 20 for v in reference]
        self.assertLess(Regions._glow_difference(shifted, reference), 1)
        self.assertGreater(Regions._glow_difference([100] * len(reference), reference), 14)

    def test_recognition_needs_two_consecutive_frames(self):
        regions = object.__new__(Regions)
        regions.refresh = lambda: None
        scores = iter([0, 0, 100, 0, 0])
        regions.mulligan_scores = lambda: {'mulligan_title': next(scores), 'mulligan_confirm': 0}
        self.assertEqual([regions.mulligan_ready() for _ in range(5)], [False, True, False, False, True])


class HubPopupTests(unittest.TestCase):
    def test_modal_requires_dimmed_hub_and_bright_center(self):
        from agent.menu import signature
        width, height = 1920, 1080
        pixels = bytearray(bytes((100, 120, 140, 255)) * width * height)
        box = (600, 990, 1310, 1014)
        regions = Regions(None, refs={'hub_bar': {'box': box, 'signature': signature(pixels, width, box)}})
        regions.screen = type('Screen', (), {'width': width})()
        regions.pixels = pixels
        self.assertFalse(regions.hub_modal())
        for y in range(box[1], box[3]):
            for x in range(box[0], box[2]):
                at = (y * width + x) * 4
                pixels[at:at + 3] = bytes((50, 60, 70))
        self.assertTrue(regions.hub_modal())
        regions.pixels = bytes((0, 0, 0, 255)) * width * height
        self.assertFalse(regions.hub_modal())

    def test_popup_is_dismissed_before_hub_navigation(self):
        shown = {'hub_buttons', 'hub_bar'}
        clicks = []
        modal = [True]

        def clicked(point):
            clicks.append(point)
            if point == CONTINUE:
                modal[0] = False
            else:
                walker.lines.append('OnSceneLoaded() - prevMode=HUB currMode=GAMEPLAY')

        walker, inputs = MenuTests().walker('HUB', shown, clicked)
        walker.regions.hub_modal = lambda: modal[0]
        walker.to_game()
        self.assertEqual(clicks, [CONTINUE, (963, 560)])

    def test_persistent_modal_stops_after_three_attempts(self):
        from agent.loop import Stop
        walker, inputs = MenuTests().walker('HUB', set())
        walker.regions.hub_modal = lambda: True
        with self.assertRaisesRegex(Stop, 'popup persisted'):
            walker.to_game()
        self.assertEqual(MenuTests().clicks(inputs), [CONTINUE] * 3)
