# 验证开播前、节目边界、循环和资源时长优先级；样例来自本地 data/tinytv 节目表与资源清单。
import unittest
from datetime import datetime
from modules.tinytv.timeline import read_json, timeline


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.schedule = read_json('schedule.json')
        self.sources = read_json('sources.json')
        self.start = datetime.fromisoformat(self.schedule['startTime']).timestamp()

    def locate(self, elapsed):
        return timeline(self.schedule, self.sources, self.start + elapsed)

    def test_before_start(self):
        self.assertEqual(self.locate(-1)['status'], 'waiting')

    def test_first_start(self):
        result = self.locate(0)
        self.assertEqual(result['episode'], 1)
        self.assertEqual(result['offset'], 0)

    def test_boundary_and_offset(self):
        duration = self.schedule['programs'][0]['duration']
        self.assertEqual(self.locate(duration - .01)['episode'], 1)
        result = self.locate(duration + .01)
        self.assertEqual(result['episode'], 2)
        self.assertAlmostEqual(result['offset'], .01, places=5)

    def test_loop(self):
        total = sum(p['duration'] for p in self.schedule['programs'])
        result = self.locate(total * 100 + 120)
        self.assertEqual(result['episode'], 1)
        self.assertAlmostEqual(result['offset'], 120, places=4)
        self.assertIn('S01E01', result['path'])

    def test_invalid_duration(self):
        self.schedule['programs'][0]['duration'] = 0
        with self.assertRaises(ValueError):
            self.locate(0)

    def test_source_duration_overrides_legacy_schedule(self):
        source = next(item for item in self.sources if item['title'] == self.schedule['programs'][0]['title']
                      and item['season'] == self.schedule['programs'][0]['season']
                      and item['episode'] == self.schedule['programs'][0]['episode'])
        source['duration'] = 100.25
        result = self.locate(100.5)
        self.assertEqual(result['episode'], 2)
        self.assertAlmostEqual(result['offset'], .25, places=5)
        self.assertEqual(result['programs'][0]['duration'], 100.25)

    def test_schedule_without_durations(self):
        for program in self.schedule['programs']:
            source = next(item for item in self.sources if all(item[key] == program[key]
                          for key in ('title', 'season', 'episode')))
            source['duration'] = program.pop('duration')
        result = self.locate(0)
        self.assertEqual(result['duration'], result['programs'][0]['duration'])
        self.assertIn('duration', result['next'])
        self.assertTrue(all('duration' not in p for p in self.schedule['programs']))

    def test_invalid_source_duration_is_not_hidden_by_legacy(self):
        program = self.schedule['programs'][0]
        source = next(item for item in self.sources if all(item[key] == program[key]
                      for key in ('title', 'season', 'episode')))
        for value in (None, False, 0, -1, float('nan'), '10'):
            with self.subTest(value=value):
                source['duration'] = value
                with self.assertRaises(ValueError):
                    self.locate(0)


if __name__ == '__main__':
    unittest.main()
