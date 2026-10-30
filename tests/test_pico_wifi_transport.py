import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wifi_transport', ROOT / 'tools/pico-wifi-transport.py')
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


class WifiTransportTests(unittest.TestCase):
    def exercise(self, fault=None, original='0\n'):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls, report, ready = [], {}, []
            fallback = root / 'fallback'
            fallback.write_text(original)
            stopping = False
            class Backend:
                module = None
                loads = 0
                def preflight(self):
                    calls.append('preflight')
                    if fault in ('existing', 'policy', 'firmware', 'module', 'manager'):
                        raise ValueError(fault)
                def module_identity(self):
                    return self.module
                def policy(self):
                    if fallback.read_text().strip() != '1':
                        raise RuntimeError('fallback changed')
                def load(self):
                    nonlocal stopping
                    self.loads += 1
                    calls.append('load')
                    self.policy()
                    if fault == 'load':
                        raise RuntimeError('module load failed')
                    self.module = (1, 99)
                    if fault == 'load-uncertain':
                        raise TimeoutError('module command timed out')
                    if fault == 'cancel-start':
                        stopping = True
                def unload(self):
                    calls.append('unload')
                    if fault == 'unload':
                        raise RuntimeError('module busy')
                    self.module = None
                def interface(self):
                    calls.append('interface')
                    if fault in ('wrong-device', 'up', 'connected', 'udev'):
                        raise ValueError(fault)
                    if fault == 'timeout':
                        return None
                    return {'ifindex': 7, 'device': '/sys/pci/qca6390', 'driver': '/sys/pci/cnss_pci'}
                def same_interface(self, expected):
                    return fault != 'replacement-interface'
            backend = Backend()
            backend.fallback = fallback
            def check():
                if backend.loads and fault == 'boot':
                    raise ValueError('boot changed')
            def notify():
                nonlocal stopping
                ready.append(True)
                if fault == 'notify':
                    raise OSError('notification failed')
                if fault == 'replacement-module':
                    backend.module = (1, 100)
                elif fault == 'external-policy':
                    fallback.write_text('0\n')
                elif fault != 'replacement-interface':
                    stopping = True
            error = None
            with patch.object(transport.time, 'sleep'):
                try:
                    transport.own_transport(backend, check, lambda: stopping, report, notify, seconds=0)
                except BaseException as value:
                    error = value
            return error, report, calls, ready, fallback.read_text(), backend.module

    def test_normal_stop_unloads_before_restoring_fallback(self):
        for original in ('0\n', '1\n'):
            error, report, calls, ready, policy, module = self.exercise(original=original)
            self.assertIsNone(error)
            self.assertEqual(ready, [True])
            self.assertEqual(calls, ['preflight', 'load', 'interface', 'unload'])
            self.assertEqual(policy, original)
            self.assertIsNone(module)
            self.assertTrue(report['module_unloaded'])
            self.assertTrue(report['fallback_restored'])

    def test_preflight_rejections_do_not_change_state(self):
        for fault in ('existing', 'policy', 'firmware', 'module', 'manager'):
            with self.subTest(fault=fault):
                error, report, calls, ready, policy, module = self.exercise(fault)
                self.assertIsInstance(error, ValueError)
                self.assertEqual(calls, ['preflight'])
                self.assertFalse(ready)
                self.assertEqual(policy, '0\n')
                self.assertFalse(report)

    def test_known_startup_failures_restore_and_never_signal_ready(self):
        for fault in ('load', 'timeout', 'wrong-device', 'up', 'connected', 'udev'):
            with self.subTest(fault=fault):
                error, report, calls, ready, policy, module = self.exercise(fault)
                self.assertIsNotNone(error)
                self.assertFalse(ready)
                self.assertEqual(policy, '0\n')
                self.assertIsNone(module)
                self.assertTrue(report['fallback_restored'])

    def test_cancellation_during_load_waits_for_owned_unload(self):
        error, report, calls, ready, policy, module = self.exercise('cancel-start')
        self.assertIsNone(error)
        self.assertEqual(calls, ['preflight', 'load', 'unload'])
        self.assertFalse(ready)
        self.assertEqual(policy, '0\n')
        self.assertIsNone(module)

    def test_notification_failure_also_cleans_up(self):
        error, report, calls, ready, policy, module = self.exercise('notify')
        self.assertIsInstance(error, OSError)
        self.assertTrue(report['module_unloaded'])
        self.assertEqual(policy, '0\n')

    def test_uncertain_or_changed_ownership_never_unloads_an_adopted_module(self):
        for fault in ('load-uncertain', 'replacement-module', 'boot'):
            with self.subTest(fault=fault):
                error, report, calls, ready, policy, module = self.exercise(fault)
                self.assertRegex(str(error), 'cleanup incomplete')
                self.assertNotIn('unload', calls)
                self.assertIsNotNone(module)
                self.assertEqual(policy, '1\n')
                self.assertNotIn('fallback_restored', report)

    def test_failed_unload_keeps_required_policy_and_reports_incomplete(self):
        error, report, calls, ready, policy, module = self.exercise('unload')
        self.assertRegex(str(error), 'cleanup incomplete')
        self.assertIsNotNone(module)
        self.assertEqual(policy, '1\n')
        self.assertNotIn('fallback_restored', report)

    def test_runtime_interface_or_policy_change_fails_and_cleans_owned_module(self):
        for fault in ('replacement-interface', 'external-policy'):
            error, report, calls, ready, policy, module = self.exercise(fault)
            self.assertIsNotNone(error)
            self.assertEqual(ready, [True])
            self.assertIsNone(module)
            self.assertEqual(policy, '0\n')

    def test_firmware_search_checks_first_effective_copy_and_never_creates_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            firmware = {'qca6390/amss20.bin': hashlib.sha256(b'firmware').hexdigest()}
            target = root / 'qca6390/amss20.bin'
            target.parent.mkdir()
            target.write_bytes(b'firmware')
            actual = transport.file_pin
            with patch.object(transport, 'FIRMWARE', firmware), \
                    patch.object(transport, 'file_pin', side_effect=lambda path: actual(path, uid=os.getuid())):
                found = transport.firmware_files('', 'kernel', root)
                self.assertEqual(found['qca6390/amss20.bin']['path'], str(target))
                higher = root / 'updates/kernel/qca6390/amss20.bin'
                higher.parent.mkdir(parents=True)
                higher.write_bytes(b'wrong')
                with self.assertRaisesRegex(ValueError, 'different'):
                    transport.firmware_files('', 'kernel', root)
                higher.unlink()
                custom = root / 'custom'
                (custom / 'qca6390').mkdir(parents=True)
                (custom / 'qca6390/amss20.bin').write_bytes(b'wrong')
                with self.assertRaisesRegex(ValueError, 'different'):
                    transport.firmware_files(str(custom), 'kernel', root)
                target.unlink()
                with self.assertRaisesRegex(ValueError, 'Missing'):
                    transport.firmware_files('', 'kernel', root)
                self.assertFalse(target.exists())

    def test_firmware_pin_rejects_writable_or_symlink_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'firmware'
            path.write_bytes(b'authentic')
            self.assertEqual(transport.file_pin(path, uid=os.getuid()), hashlib.sha256(b'authentic').hexdigest())
            path.chmod(0o666)
            with self.assertRaises(ValueError):
                transport.file_pin(path, uid=os.getuid())
            path.chmod(0o644)
            link = path.with_name('link')
            link.symlink_to(path)
            with self.assertRaises(OSError):
                transport.file_pin(link, uid=os.getuid())

    def test_startup_dependency_has_no_netdevice_cycle(self):
        owner = (ROOT / 'system/pico/reframed-pico-wifi-transport.service.in').read_text()
        dependency = (ROOT / 'system/pico/10-wifi-transport.conf').read_text()
        self.assertNotIn('.device', owner)
        self.assertIn('StopWhenUnneeded=yes', owner)
        self.assertIn('After=reframed-pico-wifi-transport.service', dependency)
        self.assertIn('BindsTo=reframed-pico-wifi-transport.service', dependency)
        self.assertIn('PartOf=NetworkManager.service', owner)
        self.assertNotIn('CAP_SYS_ADMIN', owner)

    def test_actual_preflight_refuses_preloaded_policy_device_manager_and_module_errors(self):
        for fault in (None, 'preloaded', 'wireless', 'policy', 'pci', 'manager', 'module'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                net = root / 'class/net'
                net.mkdir(parents=True)
                policy = root / 'module/cnss2/parameters/daemon_support'
                policy.parent.mkdir(parents=True)
                policy.write_text('Y\n' if fault == 'policy' else 'N\n')
                firmware_path = root / 'module/firmware_class/parameters/path'
                firmware_path.parent.mkdir(parents=True)
                firmware_path.write_text('\n')
                pci = root / 'bus/pci/devices/0000:01:00.0'
                pci.mkdir(parents=True)
                (pci / 'vendor').write_text('0x17cb')
                (pci / 'device').write_text('0x1234' if fault == 'pci' else '0x1101')
                driver = root / 'bus/pci/drivers/cnss_pci'
                driver.mkdir(parents=True)
                (pci / 'driver').symlink_to(driver)
                if fault == 'preloaded':
                    (root / 'module/wlan').mkdir()
                if fault == 'wireless':
                    (net / 'unrelated/phy80211').mkdir(parents=True)
                backend = transport.Backend({}, sysfs=root)
                backend.command = lambda command: '/installed/wlan.ko' if '-n' in command else (
                    'wrong-kernel SMP' if fault == 'module' else os.uname().release + ' SMP')
                manager = 'ActiveState=active\nMainPID=81\n' if fault == 'manager' else 'ActiveState=inactive\nMainPID=0\n'
                with patch.object(transport.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=manager)), \
                        patch.object(transport, 'firmware_files', return_value={'verified': True}), \
                        patch.object(transport, 'file_pin', return_value='a' * 64):
                    if fault is None:
                        backend.preflight()
                        self.assertEqual(backend.report['module']['sha256'], 'a' * 64)
                    else:
                        with self.assertRaises(ValueError):
                            backend.preflight()

    @unittest.skipUnless(shutil.which('cmake'), 'CMake is required for component installation')
    def test_component_installation_and_opt_in_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / 'project'
            project.mkdir()
            cmake = (ROOT / 'CMakeLists.txt').read_text()
            block = cmake[cmake.index('option(REFRAMED_PICO_WIFI_IDENTITY '):
                          cmake.index('option(REFRAMED_PICO_BLUETOOTH_IDENTITY ')]
            (project / 'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.22)\nproject(wifi-components NONE)\n' + block)
            files = ['tools/pico-wifi-identity.py', 'tools/pico-wireless-config.py', 'tools/pico-wifi-transport.py',
                     'system/pico/reframed-pico-wifi-identity.in', 'system/pico/reframed-pico-wifi-identity@.service.in',
                     'system/pico/10-reframed-pico-wifi.link', 'system/pico/reframed-pico-wifi-transport.in',
                     'system/pico/reframed-pico-wifi-transport.service.in', 'system/pico/10-wifi-transport.conf',
                     'system/pico/10-wifi-supplicant-lifecycle.conf']
            for name in files:
                target = project / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            def run(args, okay=True):
                result = subprocess.run(args, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode == 0, okay, result.stdout + result.stderr)
                return result
            common = ['cmake', '-S', str(project)]
            bad = run(common + ['-B', str(base / 'missing-identity'), '-DCMAKE_SYSTEM_NAME=Linux',
                                '-DREFRAMED_PICO_WIFI_TRANSPORT=ON'], okay=False)
            self.assertIn('requires Pico Wi-Fi identity', bad.stderr)
            run(common + ['-B', str(base / 'not-linux'), '-DCMAKE_SYSTEM_NAME=Darwin',
                          '-DREFRAMED_PICO_WIFI_IDENTITY=ON', '-DREFRAMED_PICO_WIFI_TRANSPORT=ON'], okay=False)
            off = base / 'default-off'
            run(common + ['-B', str(off), '-DCMAKE_SYSTEM_NAME=Linux'])
            run(['cmake', '--install', str(off), '--component', 'PicoWifiTransport', '--prefix', str(base / 'off')])
            self.assertFalse((base / 'off').exists())
            build, stage = base / 'build', base / 'stage'
            run(common + ['-B', str(build), '-DCMAKE_SYSTEM_NAME=Linux', '-DCMAKE_INSTALL_PREFIX=/usr',
                          '-DREFRAMED_PICO_WIFI_IDENTITY=ON', '-DREFRAMED_PICO_WIFI_TRANSPORT=ON'])
            for component in ('PicoWifiIdentity', 'PicoWifiTransport'):
                run(['cmake', '--install', str(build), '--component', component, '--prefix', str(stage / 'usr')])
            installed = {str(p.relative_to(stage)) for p in stage.rglob('*') if p.is_file()}
            self.assertEqual(len(installed), 10)
            supplicant = stage / 'usr/lib/systemd/system/wpa_supplicant.service.d/10-wifi-supplicant-lifecycle.conf'
            self.assertEqual(supplicant.read_text(), '[Unit]\nPartOf=NetworkManager.service\n')
            self.assertFalse(any('wants' in name or '.requires/' in name for name in installed))
            for name in ('pico-wifi-identity.py', 'pico-wireless-config.py', 'pico-wifi-transport.py'):
                self.assertEqual((stage / 'usr/libexec/reframed-vr' / name).read_bytes(), (ROOT / 'tools' / name).read_bytes())
            launcher = stage / 'usr/libexec/reframed-vr/reframed-pico-wifi-transport'
            self.assertEqual(subprocess.run([str(launcher)], timeout=5).returncode, 64)
            output = base / 'must-not-exist.json'
            refused = subprocess.run(['python3', '-B', str(stage / 'usr/libexec/reframed-vr/pico-wifi-transport.py'),
                '--boot-serial', 'fixture', '--boot-id', '00000000-0000-0000-0000-000000000000', '--output', str(output)],
                capture_output=True, text=True, timeout=10)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('native Linux Pico Neo3', refused.stderr)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
