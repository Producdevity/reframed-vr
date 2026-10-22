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
p.add_argument('--companion-accel',action='store_true');a=p.parse_args()
mode=os.environ.get('FIXTURE_MODE','normal');stopping=False
def stop(*args):
 global stopping
 stopping=True
signal.signal(signal.SIGTERM,stop)
if mode=='exit':raise SystemExit(3)
path=Path(a.channel);instance=int(a.instance,16)
path.write_bytes(struct.pack('<QQ',0x5256504943430001,instance)+bytes(112));path.chmod(0o644)
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

    def make(self, mode='normal', companion=False):
        worker = session_module.ControllerSession(
            self.build, self.root / ('session with spaces ' + str(len(self.sessions))),
            'a014287d-2c4f-4869-bd16-ac24b4b1e752', seconds=120,
            environment=os.environ | {'FIXTURE_MODE': mode, 'FIXTURE_DSP_OFFLINE': str(self.offline)},
            companion_accel=companion)
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


if __name__ == '__main__':
    unittest.main()
