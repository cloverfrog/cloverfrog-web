import unittest
from unittest.mock import Mock

from tools.tinytv import build_sources as tool


class BuildSourcesTests(unittest.TestCase):
    def test_authenticates_with_token_or_login(self):
        client = Mock()
        client.headers = {}
        tool.authenticate(client, 'https://alist.example', {'ALIST_TOKEN': 'token-value'})
        self.assertEqual(client.headers['Authorization'], 'token-value')

        client = Mock()
        client.headers = {}
        client.post.return_value = Mock(
            raise_for_status=Mock(),
            json=Mock(return_value={'code': 200, 'data': {'token': 'login-token'}}),
        )
        tool.authenticate(client, 'https://alist.example', {
            'ALIST_USERNAME': 'user', 'ALIST_PASSWORD': 'password'
        })
        self.assertEqual(client.post.call_args.args[0], 'https://alist.example/api/auth/login')
        self.assertEqual(client.headers['Authorization'], 'login-token')

    def test_collects_alist_files_relative_to_root(self):
        client = Mock()
        client.post.side_effect = [
            Mock(
                raise_for_status=Mock(),
                json=Mock(return_value={'code': 200, 'data': {'content': [
                    {'name': 'Show', 'is_dir': True},
                    {'name': 'note.txt', 'is_dir': False},
                ]}}),
            ),
            Mock(
                raise_for_status=Mock(),
                json=Mock(return_value={'code': 200, 'data': {'content': [
                    {'name': 'S01E01.mp4', 'is_dir': False},
                ]}}),
            ),
        ]
        self.assertEqual(
            tool.collect_files(client, 'https://alist.example', '/media'),
            ['Show/S01E01.mp4'],
        )
        self.assertEqual(client.post.call_args_list[0].kwargs['json']['path'], '/media')

    def test_builds_records_without_duration_or_root(self):
        config = [{'title': 'Show', 'seasons': [
            {'season': 1, 'episodes': 2, 'pattern': 'Show/S{season:02d}E{episode:02d}.*'}
        ]}]
        records, errors = tool.build_records(
            config, ['Show/S01E01.mp4', 'Show/S01E02.mkv']
        )
        self.assertFalse(errors)
        self.assertEqual(records[0], {
            'title': 'Show', 'season': 1, 'episode': 1, 'path': '/Show/S01E01.mp4'
        })
        self.assertNotIn('duration', records[0])

    def test_rejects_wrapped_shows_object(self):
        with self.assertRaisesRegex(ValueError, 'JSON array'):
            tool.build_records({'shows': []}, [])

    def test_builds_explicit_multipart_episode(self):
        config = [{'title': 'Show', 'seasons': [{
            'season': 1,
            'episodes': 2,
            'pattern': 'Show/S{season:02d}E{episode:02d}.mp4',
            'episodeParts': {
                '2': [
                    'Show/S{season:02d}E{episode:02d}a.mp4',
                    'Show/S{season:02d}E{episode:02d}b.mp4',
                ]
            },
        }]}]
        records, errors = tool.build_records(config, [
            'Show/S01E01.mp4', 'Show/S01E02a.mp4', 'Show/S01E02b.mp4'
        ])
        self.assertFalse(errors)
        self.assertEqual(records[1]['parts'], [
            {'path': '/Show/S01E02a.mp4'}, {'path': '/Show/S01E02b.mp4'}
        ])
        self.assertNotIn('path', records[1])

    def test_multipart_patterns_must_each_match_one_distinct_file(self):
        config = [{'title': 'Show', 'seasons': [{
            'season': 1, 'episodes': 1, 'pattern': 'unused',
            'episodeParts': {'1': ['Show/*.mp4', 'Show/missing.mp4']},
        }]}]
        records, errors = tool.build_records(config, ['Show/a.mp4', 'Show/b.mp4'])
        self.assertFalse(records)
        self.assertEqual(len(errors), 2)


if __name__ == '__main__':
    unittest.main()
