from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FenceUnwrapTests(unittest.TestCase):
    def test_empty_containers_release_references_and_do_not_hide_later_fences(self):
        patch = (ROOT / 'patches/kernel/pico-neo3-linux/0013-drm-transfer-unwrap.patch').read_text()
        source = '\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
        begin = source.index('/* Internal helper to start new array iteration')
        end = source.index('EXPORT_SYMBOL_GPL(dma_fence_unwrap_next);')
        functions = source[begin:end] + '\n'
        shim = r'''
#include <assert.h>
#include <stddef.h>
#define EXPORT_SYMBOL_GPL(name)
struct dma_fence { unsigned refs, count; struct dma_fence *next, *child; int array; };
struct dma_fence_unwrap { struct dma_fence *chain, *array; unsigned index; };
static struct dma_fence *dma_fence_get(struct dma_fence *f) { if(f)++f->refs;return f; }
static struct dma_fence *dma_fence_chain_contained(struct dma_fence *f) { return f; }
static struct dma_fence *dma_fence_chain_walk(struct dma_fence *f) {
    if(!f)return NULL;assert(f->refs);--f->refs;return dma_fence_get(f->next);
}
static struct dma_fence *dma_fence_array_first(struct dma_fence *f) {
    return !f?NULL:!f->array?f:f->count?f->child:NULL;
}
static struct dma_fence *dma_fence_array_next(struct dma_fence *f,unsigned index) {
    return f&&f->array&&index<f->count?f->child:NULL;
}
'''
        check = r'''
int main(void) {
    struct dma_fence_unwrap cursor;
    struct dma_fence empty={.refs=1,.array=1}, other={.refs=1,.array=1}, real={.refs=1};
    assert(!dma_fence_unwrap_first(&empty,&cursor));assert(empty.refs==1&&!cursor.chain);
    empty.next=&other;other.next=&real;
    assert(dma_fence_unwrap_first(&empty,&cursor)==&real);
    assert(empty.refs==1&&other.refs==1&&real.refs==2);
    assert(!dma_fence_unwrap_next(&cursor));assert(real.refs==1&&!cursor.chain);
    assert(!dma_fence_unwrap_first(NULL,&cursor));
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'unwrap'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                            '-x', 'c', '-', '-o', str(binary)], input=shim+functions+check,
                           text=True, capture_output=True, check=True, timeout=30)
            subprocess.run([str(binary)], check=True, capture_output=True, timeout=10)
