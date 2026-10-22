import importlib.util
import ctypes
import errno
import os
from pathlib import Path
import tempfile
import signal
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('audio_route', ROOT / 'tools/pico-audio-route.py')
audio = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audio)


class Mixer:
    def __init__(self, fail=None, restore_fail=None):
        self.state = {1: 10, 2: 20, 3: 30}
        self.fail, self.restore_fail = fail, restore_fail
        self.restored = []

    def value(self, control, new=None):
        key = control['numid']
        if new is None:
            return self.state[key]
        self.state[key] = new
        if new == control['target'] and key == self.fail:
            raise OSError('Partial write failure')
        if new == key * 10:
            self.restored.append(key)
            if key == self.restore_fail:
                raise OSError('Restore failure')


class AudioRouteTests(unittest.TestCase):
    def setUp(self):
        self.controls = [{'numid': i, 'name': 'fixture-' + str(i), 'target': 1} for i in [1, 2, 3]]

    def test_playback_observes_route_then_every_control_is_restored(self):
        mixer, report = Mixer(), {}
        def play(result):
            self.assertEqual(mixer.state, {1: 1, 2: 1, 3: 1})
            result['played'] = True
        audio.transaction(mixer, self.controls, play, report)
        self.assertTrue(report['played'])
        self.assertEqual(mixer.state, {1: 10, 2: 20, 3: 30})
        self.assertEqual(mixer.restored, [3, 2, 1])

    def test_partial_failed_write_is_included_in_rollback(self):
        for key in [1, 2, 3]:
            with self.subTest(key=key):
                mixer, report = Mixer(fail=key), {}
                with self.assertRaisesRegex(OSError, 'Partial write'):
                    audio.transaction(mixer, self.controls, lambda _: self.fail('Playback started'), report)
                self.assertEqual(mixer.state, {1: 10, 2: 20, 3: 30})
                self.assertEqual(mixer.restored, list(range(key, 0, -1)))

    def test_interrupt_and_pcm_failure_both_restore_the_route(self):
        for error in [KeyboardInterrupt(), TimeoutError('PCM deadline')]:
            with self.subTest(error=type(error).__name__):
                mixer, report = Mixer(), {}
                def play(_):
                    raise error
                with self.assertRaises(type(error)):
                    audio.transaction(mixer, self.controls, play, report)
                self.assertEqual(mixer.state, {1: 10, 2: 20, 3: 30})

    def test_rollback_failure_does_not_skip_remaining_controls(self):
        mixer, report = Mixer(restore_fail=3), {}
        with self.assertRaisesRegex(RuntimeError, 'rollback incomplete'):
            audio.transaction(mixer, self.controls, lambda _: None, report)
        self.assertEqual(mixer.restored, [3, 2, 1])
        self.assertEqual([r['restored'] for r in report['rollback']], [False, True, True])

    def test_termination_during_rollback_is_deferred_until_restoration(self):
        class SignallingMixer(Mixer):
            def value(self, control, new=None):
                result = super().value(control, new)
                if control['numid'] == 3 and new == 30:
                    os.kill(os.getpid(), signal.SIGTERM)
                return result
        def interrupted(number, frame):
            raise KeyboardInterrupt()
        previous = signal.signal(signal.SIGTERM, interrupted)
        mixer, report = SignallingMixer(), {}
        try:
            with self.assertRaises(KeyboardInterrupt):
                audio.transaction(mixer, self.controls, lambda _: None, report)
        finally:
            signal.signal(signal.SIGTERM, previous)
        self.assertEqual(mixer.restored, [3, 2, 1])
        self.assertTrue(all(item['restored'] for item in report['rollback']))

    def test_unverified_mixer_xml_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'mixer.xml'
            path.write_text('<mixer/>')
            with self.assertRaisesRegex(ValueError, 'hash-pinned'):
                audio.speaker_route(path)

    def test_pcm_geometry_bounds_and_period_alignment(self):
        self.assertEqual(audio.pcm_geometry(8192, 1024), 48128)
        self.assertEqual(audio.pcm_geometry(2400, 600), 48000)
        for buffer, period in [(0, 0), (2400, 601), (100000, 1000), (24000, 24000)]:
            with self.subTest(buffer=buffer, period=period), self.assertRaises(ValueError):
                audio.pcm_geometry(buffer, period)

    def test_silence_writes_complete_negotiated_periods_and_closes(self):
        class Pcm:
            def __init__(self, terminal_state):
                self.transferred, self.closed, self.dropped = 0, False, False
                self.terminal_state, self.drain_calls = terminal_state, 0
                self.waited = False
            def snd_pcm_open(self, output, *args):
                output._obj.value = 1
                return 0
            def snd_pcm_format_value(self, text): return 2
            def snd_pcm_set_params(self, *args): return 0
            def snd_pcm_get_params(self, pcm, buffer, period):
                buffer._obj.value, period._obj.value = 2400, 600
                return 0
            def snd_pcm_writei(self, pcm, data, frames):
                if frames != 600:
                    return -110
                if ctypes.string_at(data, frames * 4) != bytes(frames * 4):
                    raise AssertionError('Non-silent PCM')
                self.transferred += frames
                return frames
            def snd_strerror(self, value): return b'fixture error'
            def snd_pcm_drain(self, pcm):
                self.drain_calls += 1
                return -errno.EAGAIN
            def snd_pcm_wait(self, pcm, milliseconds):
                self.waited = True
                return -errno.EIO
            def snd_pcm_state(self, pcm):
                if not self.drain_calls:
                    return 3
                return self.terminal_state if self.waited else 5
            def snd_pcm_drop(self, pcm):
                self.dropped = True
                return 0
            def snd_pcm_close(self, pcm):
                self.closed = True
                return 0
        for state in [1, 4]:
            with self.subTest(terminal_state=state):
                alsa = object.__new__(audio.Alsa)
                alsa.lib, report = Pcm(state), {}
                status = 'state: SETUP\ndelay: 0\nhw_ptr: 48000\nappl_ptr: 48000\n'
                with patch.object(Path, 'read_text', return_value=status):
                    if state == 4:
                        with self.assertRaises(OSError):
                            alsa.silence(report)
                    else:
                        alsa.silence(report)
                self.assertEqual(alsa.lib.transferred, 48000)
                self.assertEqual(report['pcm']['period_frames'], 600)
                self.assertTrue(alsa.lib.dropped and alsa.lib.closed)
                self.assertEqual(alsa.lib.drain_calls, 1)

    def test_drain_requires_complete_hardware_progress_and_no_queued_frames(self):
        status = 'state: SETUP\ndelay: 0\nhw_ptr: 48000\nappl_ptr: 48000\n'
        self.assertEqual(audio.verify_drained(status, 48000)['hw_ptr'], '48000')
        invalid = [status.replace('SETUP', 'XRUN'), status.replace('delay: 0', 'delay: 600'),
                   status.replace('hw_ptr: 48000', 'hw_ptr: 47400'),
                   status.replace('appl_ptr: 48000', 'appl_ptr: 48600'),
                   status.replace('hw_ptr: 48000\n', ''), status + 'state: SETUP\n']
        for text in invalid:
            with self.subTest(status=text), self.assertRaises(ValueError):
                audio.verify_drained(text, 48000)


if __name__ == '__main__':
    unittest.main()
