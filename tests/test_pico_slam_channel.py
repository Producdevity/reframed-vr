from pathlib import Path
import subprocess
import select
import tempfile
import unittest


class PicoSlamChannelTests(unittest.TestCase):
    def test_concurrent_pose_transport_and_lifecycle(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            binary = Path(temp) / 'pico-slam-channel'
            subprocess.run([
                'cc', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I', str(root / 'src'),
                str(root / 'tests/pico-slam-channel.c'), str(root / 'src/pico-slam-channel.c'),
                str(root / 'src/pico-slam-pose.c'),
                '-pthread', '-lm', '-o', str(binary),
            ], check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=30)
            self.assertIn('PICO_SLAM_CHANNEL_PASS', result.stdout)
            mapping=Path(temp)/'poses.channel'
            subprocess.run([str(binary),'--init',str(mapping)],check=True,timeout=5)
            producer=subprocess.Popen([str(binary),'--produce',str(mapping)],
                                      stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
            consumer=subprocess.Popen([str(binary),'--consume',str(mapping)],
                                      stdout=subprocess.PIPE,text=True)
            try:
                for child,marker in [(producer,'PRODUCER_READY'),(consumer,'CONSUMER_READY')]:
                    self.assertTrue(select.select([child.stdout],[],[],5)[0])
                    self.assertEqual(child.stdout.readline().strip(),marker)
                producer.stdin.write('G');producer.stdin.flush()
                output=consumer.communicate(timeout=15)[0]
                self.assertEqual(consumer.returncode,0)
                self.assertIn('PICO_SLAM_PROCESS_PASS',output)
                self.assertTrue(select.select([producer.stdout],[],[],5)[0])
                self.assertEqual(producer.stdout.readline().strip(),'PRODUCER_COMPLETE')
                producer.stdin.write('F');producer.stdin.flush()
                self.assertEqual(producer.wait(timeout=5),0)
            finally:
                for child in (producer,consumer):
                    if child.poll() is None:child.kill()
                    child.wait(timeout=5)
                    if child.stdin:child.stdin.close()
                    child.stdout.close()
