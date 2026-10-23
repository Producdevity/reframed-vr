import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pico_controller_session', ROOT / 'tools/pico-controller-session.py')
session_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(session_module)

WORKER = r'''
import argparse,os,signal,struct,time
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
path.write_bytes(struct.pack('<QQ',0x5256504943430001,instance)+bytes(112));path.chmod(0o644)
if a.motion_channel:
 mask=int(bool(a.left_motion_config))|int(bool(a.right_motion_config))<<1
 now=time.monotonic_ns()-1000000
 if mode=='motion-stale':now-=200000000
 empty=mode=='motion-empty'
 header=[0x525650434d430001,instance,int(a.motion_generation,16),0 if empty else 2,1,
         now if mask&1 and not empty else 0,now if mask&2 and not empty else 0,now]
 if mode=='motion-wrong-generation':header[2]+=1
 Path(a.motion_channel).write_bytes(struct.pack('<8Q',*header)+bytes(32768));Path(a.motion_channel).chmod(0o644)
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
while not stopping and not rc:time.sleep(.01)
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


if __name__ == '__main__':
    unittest.main()
