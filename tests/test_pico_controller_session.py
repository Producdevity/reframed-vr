import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pico_controller_session', ROOT / 'tools/pico-controller-session.py')
session_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session_module)

WORKER = r'''
import argparse,os,select,signal,struct,sys,time
from pathlib import Path
p=argparse.ArgumentParser()
for name in ['boot-id','channel','instance','seconds']:p.add_argument('--'+name,required=True)
p.add_argument('--companion-accel',action='store_true')
for name in ['motion-channel','motion-generation','left-motion-config','right-motion-config']:p.add_argument('--'+name)
a=p.parse_args()
mode=os.environ.get('FIXTURE_MODE','normal');stopping=False
def stop(*args):
 global stopping
 stopping=True
signal.signal(signal.SIGTERM,stop)
if mode=='exit':raise SystemExit(3)
path=Path(a.channel);instance=int(a.instance,16)
with path.open('xb') as output:output.write(struct.pack('<QQ',0x5256504943430001,instance)+bytes(112))
path.chmod(0o644)
def refresh_motion(path,generation,initialize=False):
 now=time.monotonic_ns()-1000000
 if mode=='motion-stale':now-=200000000
 empty=mode=='motion-empty'
 header=[0x525650434d430001,instance,int(generation,16),0 if empty else 2,1,
         now if mask&1 and not empty else 0,now if mask&2 and not empty else 0,now]
 if mode=='motion-wrong-generation':header[2]+=1
 with Path(path).open('r+b') as output:
  if initialize:output.write(struct.pack('<8Q',*header))
  else:
   output.seek(24);output.write(struct.pack('<Q',header[3]))
   output.seek(40);output.write(struct.pack('<3Q',*header[5:]))
def motion_channel(path,generation):
 with Path(path).open('xb') as output:output.write(bytes(32832))
 Path(path).chmod(0o644);refresh_motion(path,generation,initialize=True)
if a.motion_channel:
 mask=int(bool(a.left_motion_config))|int(bool(a.right_motion_config))<<1
 motion_channel(a.motion_channel,a.motion_generation)
 print(f'PICO_CONTROLLER_MOTION_READY instance={a.instance} generation={a.motion_generation} mask={mask} rc=0',flush=True)
if mode=='delay':time.sleep(.3)
if mode=='flood':
 for _ in range(300):print('LOG '+('x'*1000),flush=True)
rc=-5 if mode=='init-failure' else 0
ready=f'PICO_CONTROLLER_READY instance={a.instance if mode!="wrong-instance" else "0000000000000000"} companion_accel={int(a.companion_accel)} rc={rc}\n'
if mode=='partial':
 os.write(1,ready[:30].encode());time.sleep(.05);os.write(1,ready[30:].encode())
elif mode=='premature-release':
 os.write(1,(ready+'PICO_CONTROLLER_RELEASED_DSP_OFFLINE\n').encode())
else:print(ready,end='',flush=True)
generation=a.motion_generation;current=a.motion_channel
if mode.startswith('auto-'):
 with open(current,'r+b') as file:file.seek(32);file.write(bytes(8))
 error=-71 if mode=='auto-protocol' else -110
 print(f'PICO_CONTROLLER_MOTION_STOP rc={error} samples=2',flush=True)
 if mode not in ['auto-silence','auto-protocol']:
  now=time.monotonic_ns()
  if mode=='auto-stale':now-=200000000
  if mode=='auto-future':now+=1000000000
  generation_text='0000000000000001' if mode=='auto-wrong-generation' else generation
  print(f'PICO_CONTROLLER_MOTION_RESUMED instance={a.instance} generation={generation_text} received_ns={now} deadline_ns={now+90000000}',flush=True)
  if mode=='auto-failed-probe':print(f'PICO_CONTROLLER_MOTION_RESUME_FAILED generation={generation} rc=-71',flush=True)
while not stopping and not rc:
 if a.motion_channel and mode not in ['motion-stale','motion-empty','motion-wrong-generation']:
  with Path(current).open('rb') as source:active=struct.unpack('<8Q',source.read(64))[4]
  if active:refresh_motion(current,generation)
 if a.motion_channel and select.select([sys.stdin],[],[],.01)[0]:
  command=sys.stdin.readline().split()
  if not command:continue
  _,previous,next_generation=command
  if mode in ['restart-delay','auto-delay']:time.sleep(.2)
  if mode in ['restart-failure','auto-restart-failure']:
   print(f'PICO_CONTROLLER_MOTION_RESTART previous={previous} generation={next_generation} rc=-1',flush=True)
   continue
  with open(current,'r+b') as file:file.seek(32);file.write(bytes(8))
  if not mode.startswith('auto-') and mode!='restart-no-stop':print('PICO_CONTROLLER_MOTION_STOP rc=-108 samples=2',flush=True)
  current=a.motion_channel+'.'+next_generation;generation=next_generation
  motion_channel(current,generation)
  ack='0000000000000000' if mode=='restart-wrong-ack' else previous
  print(f'PICO_CONTROLLER_MOTION_RESTART previous={ack} generation={generation} rc=0',flush=True)
  print(f'PICO_CONTROLLER_MOTION_READY instance={a.instance} generation={generation} mask={mask} rc=0',flush=True)
 else:time.sleep(.01)
if a.motion_channel:print('PICO_CONTROLLER_MOTION_STOP rc=0 samples=2',flush=True)
print(f'PICO_CONTROLLER_STOP rc={rc} controller_rc=0 accel_rc=0 left=123 right=0',flush=True)
print('PICO_CONTROLLER_WAIT_DSP_OFFLINE',flush=True)
while not Path(os.environ['FIXTURE_DSP_OFFLINE']).exists():time.sleep(.01)
print('PICO_CONTROLLER_RELEASED_DSP_OFFLINE',flush=True)
raise SystemExit(1 if rc else 0)
'''


class PicoControllerSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.build = self.root / 'build'
        self.build.mkdir()
        self.binary = self.build / 'pico-controller-input'
        self.binary.write_text('#!' + sys.executable + '\n' + WORKER)
        self.binary.chmod(0o755)
        (self.build / 'build.json').write_text(json.dumps({
            'status': 'compiled', 'binary_sha256': hashlib.sha256(self.binary.read_bytes()).hexdigest()}))
        self.offline = self.root / 'dsp-offline'
        self.sessions = []

    def tearDown(self):
        self.offline.touch()
        for worker in self.sessions:
            if worker.process is not None:
                if worker.process.poll() is None:
                    worker.process.terminate()
                worker.process.wait(timeout=3)
            if worker.reader is not None:
                worker.reader.close()
            if worker.process is not None and worker.process.stdin is not None:
                worker.process.stdin.close()
        self.temp.cleanup()

    def make(self, mode='normal', companion=False, motion=None):
        worker = session_module.ControllerSession(
            self.build, self.root / ('session with spaces ' + str(len(self.sessions))),
            'a014287d-2c4f-4869-bd16-ac24b4b1e752', seconds=120,
            environment=os.environ | {'FIXTURE_MODE': mode, 'FIXTURE_DSP_OFFLINE': str(self.offline)},
            companion_accel=companion, motion=motion)
        self.sessions.append(worker)
        return worker

    def stop(self, worker, expected=0):
        worker.request_stop()
        result = worker.wait_rpc_stopped(2)
        self.assertEqual(result['left'], 123)
        with self.assertRaises(TimeoutError):
            worker.finish(.02)
        self.assertIsNone(worker.process.poll())
        self.offline.touch()
        self.assertEqual(worker.finish(2), expected)

    def test_two_phase_stop_retains_process_until_dsp_release(self):
        worker = self.make(companion=True)
        with self.assertRaises(RuntimeError):
            worker.steamvr_environment()
        worker.start()
        worker.wait_ready(2)
        self.assertEqual(worker.steamvr_environment(), {
            'PICO_STEAMVR_CONTROLLER_CHANNEL': str(worker.channel),
            'PICO_STEAMVR_CONTROLLER_INSTANCE': worker.instance})
        for name in ['stdout.log', 'stderr.log', 'session.json']:
            self.assertEqual(stat.S_IMODE((worker.directory / name).stat().st_mode), 0o600)
        with self.assertRaises(RuntimeError):
            worker.start()
        with self.assertRaises(RuntimeError):
            worker.finish(.01)
        self.stop(worker)
        with self.assertRaises(RuntimeError):
            worker.steamvr_environment()

    def test_changed_binary_and_existing_session_refuse_before_spawn(self):
        worker = self.make()
        self.binary.write_text(self.binary.read_text() + '\n')
        with self.assertRaises(ValueError):
            worker.start()
        self.assertIsNone(worker.process)
        self.assertFalse(worker.directory.exists())
        self.binary.write_text(self.binary.read_text()[:-1])
        worker.directory.mkdir()
        with self.assertRaises(FileExistsError):
            worker.start()
        self.assertIsNone(worker.process)

    def test_startup_failure_still_requires_shared_dsp_teardown(self):
        worker = self.make('init-failure')
        worker.start()
        with self.assertRaises(RuntimeError):
            worker.wait_ready(2)
        self.assertIsNone(worker.process.poll())
        self.stop(worker, expected=1)
        self.assertEqual(worker.stop_result['rc'], -5)

    def test_readiness_timeout_retains_worker(self):
        worker = self.make('delay')
        worker.start()
        with self.assertRaises(TimeoutError):
            worker.wait_ready(.01)
        self.assertIsNone(worker.process.poll())
        worker.wait_ready(2)
        self.stop(worker)

    def test_nonfinite_timeout_refuses_without_stopping_or_restarting_worker(self):
        worker = self.make(motion=self.motion())
        worker.start();worker.wait_motion_ready(2)
        for timeout in (float('nan'), float('inf'), -float('inf')):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):worker.wait_ready(timeout)
                with self.assertRaises(ValueError):worker.recover_motion(timeout)
                with self.assertRaises(ValueError):worker.restart_motion('1123456789abcdef', timeout)
        self.assertIsNone(worker.motion_restart)
        self.assertIsNone(worker.process.poll())
        self.stop(worker)

    def test_recovery_reports_unexpected_worker_exit(self):
        worker = self.make(motion=self.motion())
        worker.start();worker.wait_motion_ready(2)
        worker.process.kill();worker.process.wait(timeout=2)
        with self.assertRaisesRegex(RuntimeError, 'Worker exited'):
            worker.recover_motion(0)

    def test_restart_generation_collision_preserves_existing_mapping(self):
        worker = self.make(motion=self.motion())
        worker.start();worker.wait_motion_ready(2)
        generation='1123456789abcdef'
        collision=Path(str(worker.motion_base)+'.'+generation)
        collision.write_bytes(b'owned by another generation')
        with self.assertRaises(RuntimeError):worker.restart_motion(generation, 2)
        self.assertEqual(collision.read_bytes(), b'owned by another generation')

    def test_partial_status_and_large_logs_do_not_block_child(self):
        for mode in ['partial', 'flood']:
            self.offline.unlink(missing_ok=True)
            worker = self.make(mode)
            worker.start()
            worker.wait_ready(2)
            self.stop(worker)
            if mode == 'flood':
                self.assertGreater((worker.directory / 'stdout.log').stat().st_size, 262144)

    def test_wrong_instance_and_early_release_are_rejected_without_killing(self):
        for mode in ['wrong-instance', 'premature-release']:
            worker = self.make(mode)
            worker.start()
            with self.assertRaises(RuntimeError):
                worker.wait_ready(2)
            self.assertIsNone(worker.process.poll())

    def test_replaced_channel_and_writable_channel_are_rejected(self):
        worker = self.make()
        worker.start()
        worker.wait_ready(2)
        worker.channel.chmod(0o666)
        with self.assertRaises(RuntimeError):
            worker.steamvr_environment()
        worker.channel.chmod(0o644)
        replacement = worker.directory / 'replacement'
        replacement.write_bytes(worker.channel.read_bytes())
        replacement.chmod(0o644)
        replacement.replace(worker.channel)
        with self.assertRaises(RuntimeError):
            worker.steamvr_environment()
        self.stop(worker)

    def test_exit_without_release_is_not_success(self):
        worker = self.make('exit')
        worker.start()
        with self.assertRaises(RuntimeError):
            worker.wait_ready(2)
        self.assertEqual(worker.process.returncode, 3)
        self.assertFalse(worker.released)

    @staticmethod
    def motion():
        return {'generation': '0123456789abcdef', 'left': {
            'connected': True, 'revision_byte': 53, 'double_scale_byte': 0,
            'axis_reversal_bypass_byte': 0}}

    def test_motion_binding_preserves_stock_settings_and_shared_dsp_lifetime(self):
        options = self.motion()
        worker = self.make(motion=options)
        self.assertEqual(worker.motion_endpoint()['generation'], '0123456789abcdef')
        self.assertFalse(worker.motion_channel.exists())
        with self.assertRaises(RuntimeError):worker.motion_binding()
        options['left']['revision_byte'] = 0
        worker.start(); worker.wait_motion_ready(2)
        self.assertEqual(worker.motion_binding(), {'path': str(worker.motion_channel),
            'instance': worker.instance, 'generation': '0123456789abcdef'})
        command = json.loads((worker.directory / 'session.json').read_text())['command']
        self.assertEqual(command[command.index('--left-motion-config') + 1], '35:00:00')
        self.assertNotIn('--right-motion-config', command)
        self.assertNotIn('MOTION', ' '.join(worker.steamvr_environment()))
        self.stop(worker)
        self.assertEqual(worker.motion_stop_result, {'rc': 0, 'samples': 2})
        with self.assertRaises(RuntimeError):worker.motion_binding()

    def test_disconnected_or_defaulted_motion_settings_are_refused_before_spawn(self):
        for value in [None, 1, '', '0000000000000000']:
            options = self.motion(); options['generation'] = value
            with self.assertRaises(ValueError):self.make(motion=options)
        for field, value in [('connected', False), ('revision_byte', True),
                             ('double_scale_byte', -1), ('axis_reversal_bypass_byte', 256)]:
            options = self.motion(); options['left'][field] = value
            with self.assertRaises(ValueError):self.make(motion=options)
        options = self.motion(); del options['left']['revision_byte']
        with self.assertRaises(ValueError):self.make(motion=options)

    def test_motion_stale_wrong_generation_and_replacement_fail_without_killing(self):
        for mode in ['motion-stale', 'motion-wrong-generation']:
            worker = self.make(mode, motion=self.motion()); worker.start()
            with self.assertRaises(RuntimeError):worker.wait_motion_ready(2)
            self.assertIsNone(worker.process.poll())
        worker = self.make(motion=self.motion()); worker.start(); worker.wait_motion_ready(2)
        replacement = worker.directory / 'motion-replacement'
        replacement.write_bytes(worker.motion_channel.read_bytes());replacement.chmod(0o644)
        replacement.replace(worker.motion_channel)
        with self.assertRaises(RuntimeError):worker.motion_binding()
        self.assertIsNone(worker.process.poll())

    def test_motion_empty_timeout_and_stopped_channel_do_not_revive(self):
        worker = self.make('motion-empty', motion=self.motion());worker.start();worker.wait_ready(2)
        with self.assertRaises(TimeoutError):worker.wait_motion_ready(.02)
        self.assertIsNone(worker.process.poll())
        worker = self.make(motion=self.motion());worker.start();worker.wait_motion_ready(2)
        with worker.motion_channel.open('r+b') as file:
            file.seek(32);file.write((0).to_bytes(8, 'little'))
        with self.assertRaises(RuntimeError):worker.motion_binding()
        self.assertIsNone(worker.process.poll())

    def test_explicit_restart_uses_new_file_and_preserves_process_and_digital_channel(self):
        worker = self.make(motion=self.motion());worker.start();worker.wait_motion_ready(2)
        old = worker.motion_binding();pid = worker.process.pid
        digital = worker.steamvr_environment()
        worker.restart_motion('0123456789abcdf0', 2)
        worker.wait_motion_ready(2)
        new = worker.motion_binding()
        self.assertEqual(new['generation'], '0123456789abcdf0')
        self.assertNotEqual(new['path'], old['path'])
        self.assertEqual(new['instance'], old['instance'])
        self.assertEqual(worker.process.pid, pid)
        self.assertIsNone(worker.process.poll())
        self.assertEqual(worker.steamvr_environment(), digital)
        self.assertEqual(struct.unpack('<Q', Path(old['path']).read_bytes()[32:40]), (0,))
        self.assertEqual(worker.motion_history, [{'generation': old['generation'], 'rc': -108, 'samples': 2}])
        with self.assertRaises(ValueError):worker.restart_motion(old['generation'], 2)
        self.stop(worker)
        self.assertEqual(worker.motion_history[-1]['generation'], new['generation'])

    def test_restart_timeout_does_not_kill_or_roll_back_request(self):
        worker = self.make('restart-delay', motion=self.motion());worker.start();worker.wait_motion_ready(2)
        with self.assertRaises(TimeoutError):worker.restart_motion('0123456789abcdf0', .01)
        self.assertIsNone(worker.process.poll())
        with self.assertRaises(RuntimeError):worker.motion_endpoint()
        with self.assertRaises(RuntimeError):worker.restart_motion('0123456789abcdf1', 2)
        worker.wait_motion_restart(2)
        worker.wait_motion_ready(2)
        self.assertEqual(worker.motion_binding()['generation'], '0123456789abcdf0')
        self.stop(worker)

    def test_failed_or_mismatched_restart_is_not_readiness(self):
        for mode in ['restart-failure', 'restart-wrong-ack', 'restart-no-stop']:
            worker = self.make(mode, motion=self.motion());worker.start();worker.wait_motion_ready(2)
            with self.assertRaises(RuntimeError):worker.restart_motion('0123456789abcdf0', 2)
            self.assertIsNone(worker.process.poll())

    def test_automatic_recovery_requires_fresh_post_timeout_imu_notification(self):
        worker = self.make('auto-resume', motion=self.motion());worker.start()
        worker.wait_ready(2);worker._wait(lambda: worker.motion_resumed is not None, 2)
        pid = worker.process.pid
        endpoint = worker.recover_motion(2)
        self.assertEqual(endpoint['generation'], '0123456789abcdf0')
        self.assertEqual(endpoint, worker.motion_binding())
        self.assertEqual(worker.process.pid, pid)
        self.assertIsNone(worker.recover_motion(0))
        self.assertEqual(worker.motion_history[0]['rc'], -110)
        self.stop(worker)

    def test_silence_stale_notification_and_protocol_failure_do_not_restart(self):
        for mode in ['auto-silence', 'auto-stale', 'auto-protocol', 'auto-failed-probe']:
            worker = self.make(mode, motion=self.motion());worker.start();worker.wait_ready(2)
            worker._wait(lambda: worker.motion_stop_result is not None, 2)
            if mode in ['auto-stale','auto-failed-probe']:
                worker._wait(lambda: worker.motion_resumed is not None, 2)
            if mode=='auto-failed-probe':worker._wait(lambda: worker.motion_resume_error is not None, 2)
            self.assertIsNone(worker.recover_motion(0))
            self.assertIsNone(worker.motion_restart)
            self.assertIsNone(worker.process.poll())

    def test_automatic_recovery_pending_timeout_completes_without_resending(self):
        worker = self.make('auto-delay', motion=self.motion());worker.start();worker.wait_ready(2)
        worker._wait(lambda: worker.motion_resumed is not None, 2)
        with self.assertRaises(TimeoutError):worker.recover_motion(.01)
        self.assertTrue(worker.motion_recovery_pending)
        endpoint = worker.recover_motion(2)
        self.assertEqual(endpoint['generation'], '0123456789abcdf0')
        self.assertEqual(len(worker.motion_history),1)
        self.assertFalse(worker.motion_recovery_pending)
        self.stop(worker)

    def test_rejected_automatic_restart_does_not_loop_or_kill_worker(self):
        worker = self.make('auto-restart-failure', motion=self.motion());worker.start();worker.wait_ready(2)
        worker._wait(lambda: worker.motion_resumed is not None, 2)
        with self.assertRaises(RuntimeError):worker.recover_motion(2)
        request = dict(worker.motion_restart)
        self.assertIsNone(worker.recover_motion(2))
        self.assertEqual(worker.motion_restart, request)
        self.assertFalse(worker.motion_recovery_pending)
        self.assertIsNone(worker.process.poll())

    def test_wrong_resume_generation_future_clock_and_replaced_file_are_refused(self):
        worker = self.make('auto-wrong-generation', motion=self.motion());worker.start()
        with self.assertRaises(RuntimeError):worker._wait(lambda: worker.motion_resumed is not None, 2)
        worker = self.make('auto-future', motion=self.motion());worker.start();worker.wait_ready(2)
        worker._wait(lambda: worker.motion_resumed is not None, 2)
        with self.assertRaises(RuntimeError):worker.recover_motion(2)
        worker = self.make('auto-resume', motion=self.motion());worker.start();worker.wait_ready(2)
        worker._wait(lambda: worker.motion_resumed is not None, 2)
        # Establish inode identity before replacing the stopped channel.
        worker._motion_header()
        replacement=worker.directory/'replaced-motion'
        replacement.write_bytes(worker.motion_channel.read_bytes());replacement.chmod(0o644)
        replacement.replace(worker.motion_channel)
        with self.assertRaises(RuntimeError):worker.recover_motion(2)
        self.assertIsNone(worker.motion_restart)

    def consumer_fixture(self, *, capture=1090000000, received=1110000000):
        worker = self.make(motion=self.motion())
        worker.directory.mkdir()
        worker.ready = worker.motion_ready = 0
        worker.process = Mock()
        worker.process.poll.return_value = None
        worker._read_status = Mock()
        header = [0x525650434d430001, int(worker.instance, 16),
                  int(worker.motion['generation'], 16), 2, 1, capture, 0, received]
        worker.motion_channel.write_bytes(struct.pack('<8Q', *header) + bytes(32832 - 64))
        worker.motion_channel.chmod(0o644)
        report = {'generation': worker.motion['generation'], 'observed_ns': 1101000000}
        return worker, report, header

    def test_consumer_timeout_waits_for_fresh_input_received_after_failure(self):
        worker, report, header = self.consumer_fixture(capture=1000000000, received=1020000000)
        worker.restart_motion = Mock(side_effect=TimeoutError)
        with patch.object(session_module.time, 'monotonic_ns', return_value=1101000000):
            self.assertIsNone(worker.recover_motion(0, consumer_timeout=report))
            with self.assertRaisesRegex(RuntimeError, 'fresh capture'):worker.motion_binding()
        worker.restart_motion.assert_not_called()
        header[5], header[7] = 1090000000, 1110000000
        with worker.motion_channel.open('r+b') as output:
            output.write(struct.pack('<8Q', *header))
        with patch.object(session_module.time, 'monotonic_ns', return_value=1110000000):
            with self.assertRaises(TimeoutError):
                worker.recover_motion(0, consumer_timeout=report)
        worker.restart_motion.assert_called_once_with('0123456789abcdf0', 0)
        self.assertTrue(worker.motion_recovery_pending)
        self.assertEqual(report['observed_ns'], 1101000000)

    def test_latched_gap_and_expiration_require_a_new_motion_epoch(self):
        for error, reason in [(-71, 5), (-110, 6)]:
            with self.subTest(error=error, reason=reason):
                worker, report, _ = self.consumer_fixture()
                worker.restart_motion = Mock(side_effect=TimeoutError)
                failure = report | {'error': error, 'reason': reason}
                with patch.object(session_module.time, 'monotonic_ns', return_value=1110000000):
                    with self.assertRaises(TimeoutError):
                        worker.recover_motion(0, consumer_failure=failure)
                worker.restart_motion.assert_called_once_with('0123456789abcdf0', 0)
                self.assertTrue(worker.motion_recovery_pending)
                self.assertEqual(failure, report | {'error': error, 'reason': reason})

    def test_other_consumer_failures_cannot_restart_the_estimator(self):
        worker, report, _ = self.consumer_fixture()
        worker.restart_motion = Mock()
        failure = report | {'error': -71, 'reason': 5}
        invalid = [False, [], {}, report, failure | {'extra': 1}]
        invalid += [failure | {'error': error, 'reason': reason}
                    for error, reason in [(-71, 1), (-71, 4), (-71, 6), (-110, 5),
                                          (-5, 8), (-62, 2), (-110, True), ('-71', 5)]]
        with patch.object(session_module.time, 'monotonic_ns', return_value=1110000000):
            for value in invalid:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    worker.recover_motion(0, consumer_failure=value)
            with self.assertRaises(ValueError):
                worker.recover_motion(0, consumer_timeout=report, consumer_failure=failure)
        worker.restart_motion.assert_not_called()

    def test_gap_recovery_keeps_freshness_and_generation_gates(self):
        worker, report, _ = self.consumer_fixture(capture=1000000000, received=1020000000)
        worker.restart_motion = Mock()
        failure = report | {'error': -71, 'reason': 5}
        with patch.object(session_module.time, 'monotonic_ns', return_value=1110000000):
            self.assertIsNone(worker.recover_motion(0, consumer_failure=failure))
            with self.assertRaises(ValueError):
                worker.recover_motion(0, consumer_failure=failure | {'observed_ns': 1110000001})
        worker.restart_motion.assert_not_called()

    def test_consumer_report_validation_and_stale_generation_never_restart(self):
        worker, report, _ = self.consumer_fixture()
        worker.restart_motion = Mock()
        invalid = [False, [], {}, report | {'extra': 1}, report | {'generation': 4},
                   report | {'generation': '0123456789ABCDEF'}, report | {'generation': '1'}]
        invalid += [report | {'observed_ns': value}
                    for value in (True, None, '1101000000', 1.0, 0, -1, 1110000001)]
        with patch.object(session_module.time, 'monotonic_ns', return_value=1110000000):
            for value in invalid:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    worker.recover_motion(0, consumer_timeout=value)
            for generation in ('0123456789abcdee', '0123456789abcdf0'):
                self.assertIsNone(worker.recover_motion(0, consumer_timeout=report | {'generation': generation}))
        worker.restart_motion.assert_not_called()

    def test_consumer_recovery_requires_active_fresh_post_failure_header(self):
        cases = [(3, 0, None), (5, 0, None), (7, 1101000000, None),
                 (7, 1100000000, None), (7, 1110000001, RuntimeError),
                 (5, 1000000000, None), (4, 0, None), (5, 1110000001, RuntimeError),
                 (2, 1, RuntimeError)]
        for field, value, error in cases:
            with self.subTest(field=field, value=value):
                worker, report, header = self.consumer_fixture()
                header[field] = value
                with worker.motion_channel.open('r+b') as output:
                    output.write(struct.pack('<8Q', *header))
                worker.restart_motion = Mock()
                with patch.object(session_module.time, 'monotonic_ns', return_value=1110000000):
                    if error:
                        with self.assertRaises(error):worker.recover_motion(0, consumer_timeout=report)
                    else:
                        self.assertIsNone(worker.recover_motion(0, consumer_timeout=report))
                worker.restart_motion.assert_not_called()

    def test_consumer_report_cannot_bypass_producer_errors_or_other_restart(self):
        cases = [('motion_stop_result', {'rc': -71}), ('motion_stop_result', {'rc': -110}),
                 ('motion_resume_error', -71), ('motion_resumed', {'received_ns': 1110000000}),
                 ('motion_restart', {'rc': -1}), ('motion_restart', {'rc': None}),
                 ('waiting', True), ('ready', -5)]
        for attribute, value in cases:
            with self.subTest(attribute=attribute, value=value):
                worker, report, _ = self.consumer_fixture()
                setattr(worker, attribute, value)
                worker.restart_motion = Mock()
                with patch.object(session_module.time, 'monotonic_ns', return_value=1110000000):
                    self.assertIsNone(worker.recover_motion(0, consumer_timeout=report))
                worker.restart_motion.assert_not_called()

    def test_consumer_recovery_refuses_generation_exhaustion(self):
        worker, report, header = self.consumer_fixture()
        worker.motion['generation'] = report['generation'] = 'ffffffffffffffff'
        header[2] = (1 << 64) - 1
        with worker.motion_channel.open('r+b') as output:
            output.write(struct.pack('<8Q', *header))
        worker.restart_motion = Mock()
        with patch.object(session_module.time, 'monotonic_ns', return_value=1110000000):
            with self.assertRaisesRegex(RuntimeError, 'exhausted'):
                worker.recover_motion(0, consumer_timeout=report)
        worker.restart_motion.assert_not_called()

    def test_stale_consumer_report_does_not_suppress_producer_resumption(self):
        worker = self.make('auto-resume', motion=self.motion());worker.start();worker.wait_ready(2)
        worker._wait(lambda: worker.motion_resumed is not None, 2)
        report = {'generation': '0000000000000001', 'observed_ns': 1}
        self.assertEqual(worker.recover_motion(2, consumer_timeout=report)['generation'], '0123456789abcdf0')
        self.stop(worker)

    def test_rejected_consumer_restart_is_not_retried(self):
        worker = self.make('restart-failure', motion=self.motion());worker.start();worker.wait_motion_ready(2)
        report = {'generation': worker.motion['generation'], 'observed_ns': 1}
        with self.assertRaises(RuntimeError):worker.recover_motion(2, consumer_timeout=report)
        request = dict(worker.motion_restart)
        self.assertFalse(worker.motion_recovery_pending)
        self.assertIsNone(worker.recover_motion(0, consumer_timeout=report))
        self.assertEqual(worker.motion_restart, request)
        self.assertIsNone(worker.process.poll())

    def test_consumer_recovery_pending_completes_after_generation_changes(self):
        worker, report, _ = self.consumer_fixture()
        worker.restart_motion = Mock(side_effect=TimeoutError)
        with patch.object(session_module.time, 'monotonic_ns', return_value=1110000000):
            with self.assertRaises(TimeoutError):worker.recover_motion(0, consumer_timeout=report)
            worker.motion['generation'] = '0123456789abcdf0'
            worker.wait_motion_restart = Mock()
            worker.wait_motion_ready = Mock()
            worker.motion_binding = Mock(return_value=worker.motion_endpoint())
            self.assertEqual(worker.recover_motion(0, consumer_timeout=report)['generation'], '0123456789abcdf0')
            self.assertIsNone(worker.recover_motion(0, consumer_timeout=report))
        worker.restart_motion.assert_called_once()
        worker.wait_motion_restart.assert_called_once_with(0)
        self.assertFalse(worker.motion_recovery_pending)

    def test_consumer_recovery_retires_healthy_mapping_without_restarting_rpc(self):
        worker = self.make('restart-delay', motion=self.motion());worker.start();worker.wait_motion_ready(2)
        old = worker.motion_binding();pid = worker.process.pid
        digital = worker.steamvr_environment()
        report = {'generation': old['generation'], 'observed_ns': session_module.time.monotonic_ns()}
        worker._wait(lambda: worker._motion_header()[4] > report['observed_ns'], 2)
        with self.assertRaises(TimeoutError):worker.recover_motion(.01, consumer_timeout=report)
        self.assertTrue(worker.motion_recovery_pending)
        endpoint = worker.recover_motion(2, consumer_timeout=report)
        self.assertEqual(endpoint['generation'], '0123456789abcdf0')
        self.assertNotEqual(endpoint['path'], old['path'])
        self.assertEqual(worker.process.pid, pid)
        self.assertEqual(worker.steamvr_environment(), digital)
        self.assertEqual(struct.unpack('<Q', Path(old['path']).read_bytes()[32:40]), (0,))
        self.assertEqual(worker.motion_history, [{'generation': old['generation'], 'rc': -108, 'samples': 2}])
        self.assertIsNone(worker.recover_motion(0, consumer_timeout=report))
        self.stop(worker)


if __name__ == '__main__':
    unittest.main()
