from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class KgslDrmSyncTests(unittest.TestCase):
    def test_binary_provider_never_requires_timeline_ioctls(self):
        root = Path(__file__).resolve().parents[1]
        patch = (root / 'patches/mesa/turnip/0003-kgsl-drm-syncobj.patch').read_text()
        section = patch.split('+++ b/src/freedreno/vulkan/tu_kgsl_drm_sync.h\n', 1)[1]
        header = '\n'.join(line[1:] for line in section.splitlines() if line.startswith('+')) + '\n'
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / 'tu_kgsl_drm_sync.h').write_text(header)
            (work / 'xf86drm.h').write_text('''#include <stdint.h>
#define DRM_SYNCOBJ_CREATE_SIGNALED 1
int drmSyncobjCreate(int, uint32_t, uint32_t *);
int drmSyncobjDestroy(int, uint32_t);
int drmSyncobjTransfer(int, uint32_t, uint64_t, uint32_t, uint64_t, uint32_t);
int drmSyncobjExportSyncFile(int, uint32_t, int *);
int drmSyncobjImportSyncFile(int, uint32_t, int);
int drmSyncobjSignal(int, const uint32_t *, uint32_t);
''')
            binary = work / 'test'
            subprocess.run([shutil.which('cc'), '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-I', str(work), str(root / 'tests/kgsl-drm-binary.c'), '-o', str(binary)],
                           check=True, capture_output=True, text=True, timeout=30)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=15)
            self.assertIn('KGSL_DRM_BINARY_PASS', result.stdout)
