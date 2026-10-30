"""Bounded trace_pipe reader for an instance owned by the calling diagnostic."""
from pathlib import Path
import hashlib
import json
import os
import select
import threading
import time


class Capture:
    def __init__(self, instance, out, name, budget, boot):
        self.instance = Path(instance)
        self.out = Path(out)
        self.name = name
        self.budget = budget
        self.path = Path('/tmp') / (name + '.txt')
        self.stop = threading.Event()
        self.thread = None
        self.finished = False
        self.state = {'boot_id': boot, 'path': str(self.path), 'budget': budget,
                      'bytes': 0, 'error': None, 'joined': False, 'cleanup_errors': [],
                      'join_attempts': 0,
                      'scope': 'Bounded diagnostic capture; no application or scheduling setter. Added trace selection has measurement overhead.'}

    def save(self):
        try:
            (self.out / (self.name + '-capture.json')).write_text(json.dumps(self.state, indent=2))
        except Exception as error:
            self.state['cleanup_errors'].append('receipt: ' + repr(error))
            print('PICO_STEADY_TRACE_RECEIPT_ERROR', self.name, repr(error), flush=True)

    def stats(self):
        return {str(p.relative_to(self.instance)): p.read_text()
                for p in sorted((self.instance / 'per_cpu').glob('cpu*/stats'))}

    def filters(self):
        return {str(p.parent.relative_to(self.instance / 'events')):
                {'enable': p.read_text().strip(), 'filter': (p.parent / 'filter').read_text()}
                for p in sorted((self.instance / 'events').glob('*/*/enable'))
                if p.read_text().strip() == '1'}

    def start(self):
        assert self.thread is None and not self.finished
        assert (self.instance / 'tracing_on').read_text().strip() == '0'
        assert (self.instance / 'current_tracer').read_text().strip() == 'nop'
        self.state['prepare_begin_ns'] = time.monotonic_ns()
        self.state['filters_before'] = self.filters()
        self.state['stats_before_clear'] = self.stats()
        (self.instance / 'trace').write_text('')
        self.state['stats_initial'] = self.stats()
        self.state['current_tracer'] = (self.instance / 'current_tracer').read_text().strip()
        fd = os.open(self.instance / 'trace_pipe', os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        ready = threading.Event()
        def reader():
            digest = hashlib.sha256()
            self.state['reader_tid'] = threading.get_native_id()
            try:
                with self.path.open('xb') as output:
                    ready.set()
                    while True:
                        try:
                            data = os.read(fd, 1024 * 1024)
                        except BlockingIOError:
                            if self.stop.is_set():
                                break
                            select.select([fd], [], [], .1)
                            continue
                        if not data:
                            if self.stop.is_set():
                                break
                            select.select([fd], [], [], .1)
                            continue
                        if self.state['bytes'] + len(data) > self.budget:
                            raise RuntimeError('Trace capture budget exhausted')
                        output.write(data)
                        digest.update(data)
                        self.state['bytes'] += len(data)
            except Exception as error:
                self.state['error'] = repr(error)
            finally:
                self.state['reader_exit_ns'] = time.monotonic_ns()
                self.state['sha256'] = digest.hexdigest()
                os.close(fd)
                ready.set()
        self.thread = threading.Thread(target=reader, daemon=True)
        self.thread.start()
        assert ready.wait(2) and self.thread.is_alive() and self.state['error'] is None
        self.state['enable_begin_ns'] = time.monotonic_ns()
        (self.instance / 'tracing_on').write_text('1')
        self.state['enable_end_ns'] = time.monotonic_ns()
        assert (self.instance / 'tracing_on').read_text().strip() == '1'
        self.save()

    def finish(self, reason):
        if self.finished:
            return self.state
        self.state.setdefault('stop_reason', reason)
        self.state['disable_begin_ns'] = time.monotonic_ns()
        try:
            (self.instance / 'tracing_on').write_text('0')
            self.state['disable_end_ns'] = time.monotonic_ns()
            assert (self.instance / 'tracing_on').read_text().strip() == '0'
        except Exception as error:
            self.state['cleanup_errors'].append('tracing_off: ' + repr(error))
        try:
            self.state['filters_final'] = self.filters()
        except Exception as error:
            self.state['cleanup_errors'].append('filters: ' + repr(error))
        self.stop.set()
        if self.thread is not None:
            self.state['join_attempts'] += 1
            self.thread.join(timeout=5)
            self.state['joined'] = not self.thread.is_alive()
        else:
            self.state['joined'] = True
        self.state['join_end_ns'] = time.monotonic_ns()
        if not self.state['joined']:
            error = 'reader did not join within 5 seconds'
            if error not in self.state['cleanup_errors']:
                self.state['cleanup_errors'].append(error)
            task = Path('/proc/self/task') / str(self.state.get('reader_tid'))
            self.state['unjoined_reader'] = {}
            for name in ('stat', 'wchan', 'syscall', 'stack'):
                try:
                    self.state['unjoined_reader'][name] = (task / name).read_text()
                except OSError as error:
                    self.state['unjoined_reader'][name] = {'error': repr(error)}
        try:
            self.state['stats_final'] = self.stats()
        except Exception as error:
            self.state['cleanup_errors'].append('stats: ' + repr(error))
        for path in sorted((self.instance / 'events').glob('*/*/enable')):
            try:
                path.write_text('0')
            except Exception as error:
                self.state['cleanup_errors'].append(str(path) + ': ' + repr(error))
        self.finished = self.state['joined']
        self.save()
        return self.state
