# 验证时长解析、断点续跑和输入保护；用模拟 ffprobe 结果和临时文件，避免依赖真实媒体。
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.tinytv import probe_durations as tool


class ProbeTests(unittest.TestCase):
    def test_duration_parser_and_safe_failure(self):
        with patch.object(tool.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{"format":{"duration":"10.12345678"}}')):
            self.assertEqual(tool.probe_duration('https://private.example'), 10.123457)
        with patch.object(tool.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, [], stderr='private URL')):
            with self.assertRaisesRegex(ValueError, 'exit 1') as caught:
                tool.probe_duration('https://private.example')
            self.assertNotIn('private', str(caught.exception))
        with patch.object(tool.subprocess, 'run', side_effect=subprocess.TimeoutExpired([], 1)):
            with self.assertRaisesRegex(ValueError, 'timed out'):
                tool.probe_duration('https://private.example')

    def test_changed_paths_are_not_resumed(self):
        original = {'title':'show', 'season':1, 'episode':1, 'path':'/new.mp4'}
        old = {**original, 'path':'/old.mp4', 'duration':10}
        self.assertNotIn('duration', tool.prepare_records([original], [old])[0])
        same = {**original, 'duration':20}
        self.assertEqual(tool.prepare_records([original], [same])[0]['duration'], 20)
        self.assertNotIn('duration', original)

    def test_batch_preserves_input_and_retries_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source, output = folder/'sources.json', folder/'sources.probed.json'
            data = [{'title':'show', 'season':1, 'episode':number, 'path':f'/show/{number}.mp4'}
                    for number in (1, 2, 3)]
            data[0]['duration'] = 5.5
            source.write_text(json.dumps(data), encoding='utf-8')
            original = source.read_bytes()
            args = ['--input',str(source),'--output',str(output),'--base-url','https://alist.example','--root','/影视']
            with (patch.object(tool.shutil, 'which', return_value='ffprobe'),
                  patch.object(tool, 'probe_duration', side_effect=[ValueError('timeout'), 12.5]) as probe,
                  contextlib.redirect_stdout(io.StringIO())):
                self.assertEqual(tool.main(args), 1)
                self.assertEqual(probe.call_count, 2)
                self.assertIn('/d/%E5%BD%B1%E8%A7%86/', probe.call_args.args[0])
            first = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(first[2]['duration'], 12.5)
            self.assertNotIn('duration', first[1])
            self.assertEqual(source.read_bytes(), original)
            with (patch.object(tool.shutil, 'which', return_value='ffprobe'),
                  patch.object(tool, 'probe_duration', return_value=11.25) as probe,
                  contextlib.redirect_stdout(io.StringIO())):
                self.assertEqual(tool.main(args), 0)
                self.assertEqual(probe.call_count, 1)
            self.assertEqual(json.loads(output.read_text(encoding='utf-8'))[1]['duration'], 11.25)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(json.loads(output.with_name('sources.probed.errors.json').read_text()), [])
            self.assertFalse(output.with_name(output.name+'.tmp').exists())

    def test_same_input_output_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            tool.main(['--input','same.json','--output','same.json'])

    def test_limit_and_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, output = Path(temporary)/'sources.json', Path(temporary)/'result.json'
            data = [{'title':'show', 'season':1, 'episode':number, 'path':f'/{number}.mp4'} for number in (1, 2)]
            source.write_text(json.dumps(data), encoding='utf-8')
            args = ['--input',str(source),'--output',str(output),'--limit','1']
            with (patch.object(tool.shutil, 'which', return_value='ffprobe'),
                  patch.object(tool, 'probe_duration', return_value=10) as probe,
                  contextlib.redirect_stdout(io.StringIO())):
                self.assertEqual(tool.main(args), 0)
                self.assertEqual(probe.call_count, 1)
                self.assertEqual(tool.main(args), 0)
                self.assertEqual(probe.call_count, 2)
            self.assertTrue(all(item['duration'] == 10 for item in json.loads(output.read_text())))
