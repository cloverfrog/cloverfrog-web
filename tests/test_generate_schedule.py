import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from tools.tinytv.generate_schedule import continuation_starts, generate, main


class GenerateScheduleTests(unittest.TestCase):
    @staticmethod
    def sources(title, episodes):
        return [
            {'title': title, 'season': 1, 'episode': episode, 'path': f'/{title}-{episode}.mp4', 'duration': 10}
            for episode in episodes
        ]

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

    def test_priority_is_optional_and_validated(self):
        sources = self.sources('a', [1]) + self.sources('b', [1])
        default, _ = generate(sources, min_run=1, max_run=1, seed=2)
        explicit, _ = generate(sources, min_run=1, max_run=1, priorities={'a': 1, 'b': 1}, seed=2)
        self.assertEqual(default, explicit)
        with self.assertRaisesRegex(ValueError, '未知作品'):
            generate(sources, priorities={'missing': 2})
        with self.assertRaisesRegex(ValueError, '大于 0'):
            generate(sources, priorities={'a': 0})

    def test_priority_changes_weighted_selection(self):
        sources = self.sources('a', [1]) + self.sources('b', [1])
        normal, _ = generate(sources, min_run=1, max_run=1, priorities={'a': 1, 'b': 1}, seed=5)
        preferred, _ = generate(sources, min_run=1, max_run=1, priorities={'a': 1000, 'b': 1}, seed=5)
        self.assertEqual(normal[0]['title'], 'b')
        self.assertEqual(preferred[0]['title'], 'a')

    def test_continue_counts_current_episode_as_played(self):
        sources = self.sources('show', [1, 2, 3])
        old = {'startTime': '2026-01-01T00:00:00+00:00', 'programs': [
            {'title': 'show', 'season': 1, 'episode': 1, 'duration': 10},
            {'title': 'show', 'season': 1, 'episode': 2, 'duration': 10},
            {'title': 'show', 'season': 1, 'episode': 3, 'duration': 10},
        ]}
        starts = continuation_starts(old, sources, datetime.fromisoformat('2026-01-01T00:00:15+00:00'))
        self.assertEqual(starts, {'show': (1, 3)})

    def test_continue_uses_next_episode_at_exact_boundary(self):
        sources = self.sources('show', [1, 2, 3])
        old = {'startTime': '2026-01-01T00:00:00+00:00', 'programs': [
            {'title': 'show', 'season': 1, 'episode': 1, 'duration': 10},
            {'title': 'show', 'season': 1, 'episode': 2, 'duration': 10},
        ]}
        starts = continuation_starts(old, sources, datetime.fromisoformat('2026-01-01T00:00:10+00:00'))
        self.assertEqual(starts, {'show': (1, 3)})

    def test_continue_does_not_loop_expired_schedule(self):
        sources = self.sources('show', [1, 2, 3])
        old = {'startTime': '2026-01-01T00:00:00+00:00', 'programs': [
            {'title': 'show', 'season': 1, 'episode': 1, 'duration': 10},
            {'title': 'show', 'season': 1, 'episode': 2, 'duration': 10},
        ]}
        starts = continuation_starts(old, sources, datetime.fromisoformat('2026-01-02T00:00:00+00:00'))
        self.assertEqual(starts, {'show': (1, 3)})

    def test_continue_handles_changed_sources_and_new_title(self):
        sources = self.sources('show', [1, 3, 4]) + self.sources('new', [1])
        old = {'startTime': '2026-01-01T00:00:00+00:00', 'programs': [
            {'title': 'show', 'season': 1, 'episode': 2, 'duration': 10},
            {'title': 'removed', 'season': 1, 'episode': 1, 'duration': 10},
        ]}
        starts = continuation_starts(old, sources, datetime.fromisoformat('2026-01-01T00:00:05+00:00'))
        self.assertEqual(starts, {'show': (1, 3)})

    def test_future_old_schedule_preserves_unplayed_start(self):
        old = {'startTime': '2026-01-02T00:00:00+00:00', 'programs': [
            {'title': 'show', 'season': 1, 'episode': 1, 'duration': 10},
        ]}
        starts = continuation_starts(old, self.sources('show', [1, 2]), datetime.fromisoformat('2026-01-01T00:00:00+00:00'))
        self.assertEqual(starts, {'show': (1, 1)})

    def test_continue_can_read_and_replace_same_file(self):
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            sources_path = root / 'sources.json'
            output_path = root / 'schedule.json'
            sources_path.write_text(json.dumps(self.sources('show', [1, 2])), encoding='utf-8')
            output_path.write_text(json.dumps({
                'channel': 'tiny',
                'startTime': '2026-01-01T00:00:00+00:00',
                'programs': [{'title': 'show', 'season': 1, 'episode': 1, 'duration': 10}],
            }), encoding='utf-8')
            main(['--sources', str(sources_path), '--output', str(output_path), '--mode', 'continue',
                  '--start', '2026-01-01T00:00:05+00:00', '--min-run', '1', '--max-run', '1', '--seed', '1'])
            schedule = json.loads(output_path.read_text(encoding='utf-8'))
            self.assertEqual(schedule['programs'][0]['episode'], 2)

    def test_invalid_old_schedule_is_not_overwritten(self):
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            sources_path = root / 'sources.json'
            output_path = root / 'schedule.json'
            sources_path.write_text(json.dumps(self.sources('show', [1])), encoding='utf-8')
            original = '{"invalid": true}\n'
            output_path.write_text(original, encoding='utf-8')
            with self.assertRaises(SystemExit):
                main([
                    '--sources', str(sources_path), '--output', str(output_path),
                    '--mode', 'continue', '--start', '2026-01-01T00:00:05+00:00',
                ])
            self.assertEqual(output_path.read_text(encoding='utf-8'), original)


if __name__ == '__main__':
    unittest.main()
