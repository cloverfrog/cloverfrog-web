import unittest

from tools.tinytv.generate_schedule import generate


class GenerateScheduleTests(unittest.TestCase):
    def test_multipart_episode_counts_once_and_sums_duration(self):
        sources = [
            {'title': 'show', 'season': 1, 'episode': 1, 'parts': [
                {'path': '/a.mp4', 'duration': 10},
                {'path': '/b.mp4', 'duration': 20},
            ]},
            {'title': 'show', 'season': 1, 'episode': 2, 'path': '/c.mp4', 'duration': 5},
        ]
        programs, total = generate(sources, min_run=1, max_run=1, seed=1)
        self.assertEqual(len(programs), 2)
        self.assertEqual({program['episode'] for program in programs}, {1, 2})
        self.assertEqual(next(p['duration'] for p in programs if p['episode'] == 1), 30)
        self.assertEqual(total, 35)

    def test_rejects_invalid_multipart_duration(self):
        source = {'title': 'show', 'season': 1, 'episode': 1, 'parts': [
            {'path': '/a.mp4', 'duration': 10}, {'path': '/b.mp4'}
        ]}
        with self.assertRaises(ValueError):
            generate([source])


if __name__ == '__main__':
    unittest.main()
