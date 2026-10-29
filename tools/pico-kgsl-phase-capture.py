from pathlib import Path
import hashlib
import json
import os
import time

EVENT = 'kgsl/kgsl_event_phases'
ROOT = Path('/sys/kernel/debug/tracing')


def disabled():
    paths = [ROOT / 'events' / EVENT / 'enable']
    paths += sorted((ROOT / 'instances').glob('*/events/' + EVENT + '/enable'))
    result = {str(p.relative_to(ROOT)): p.read_text().strip() for p in paths}
    assert result and all(value == '0' for value in result.values()), result
    return result


class Phases:
    def __init__(self, out, boot, factory):
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == boot
        assert 'androidboot.serialno=c980c8d4' in Path('/proc/cmdline').read_text()
        self.out, self.boot, self.factory = Path(out), boot, factory
        self.out.mkdir(mode=0o700)
        self.instance = ROOT / 'instances/reframed-pico-callback-phases'
        self.capture = None
        self.created = False
        self.rows = []
        self.record = {'schema': 1, 'boot_id': boot, 'event': EVENT,
                       'plan': [False, True, False], 'scope': 'Diagnostic phase intervals include preemption and IRQ time; no pacing or CPU-time acceptance',
                       'rows': self.rows, 'restored': False, 'errors': [], 'initial_global_enables': disabled()}
        self.save()
        try:
            assert not self.instance.exists()
            self.instance.mkdir()
            self.created = True
            (self.instance / 'tracing_on').write_text('0')
            (self.instance / 'current_tracer').write_text('nop')
            (self.instance / 'trace_clock').write_text('mono')
            (self.instance / 'buffer_size_kb').write_text('1024')
            assert (self.instance / 'current_tracer').read_text().strip() == 'nop'
            assert '[mono]' in (self.instance / 'trace_clock').read_text()
            assert all(p.read_text().strip() == '0' for p in self.instance.glob('events/*/*/enable'))
            self.event = self.instance / 'events' / EVENT
            raw = (self.event / 'format').read_bytes()
            (self.out / 'format.txt').write_bytes(raw)
            self.record['format_sha256'] = hashlib.sha256(raw).hexdigest()
            assert b'name: kgsl_event_phases\n' in raw and b'field:unsigned int id;' in raw
            (self.event / 'filter').write_text('0')
            assert (self.event / 'filter').read_text().strip() == 'none'
            self.record['filter'] = (self.event / 'filter').read_text()
            self.record['configured_global_enables'] = disabled()
            self.save()
        except BaseException as error:
            error.callback_phases_handle = self
            try:
                self.cleanup()
            except BaseException as cleanup_error:
                cleanup_error.callback_phases_handle = self
                raise
            raise

    def save(self):
        (self.out / 'receipt.json').write_text(json.dumps(self.record, indent=2) + '\n')

    def start(self, window):
        assert window == len(self.rows) and window in (0, 1, 2)
        assert self.capture is None
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip() == self.boot
        row = {'window': window, 'enabled': window == 1, 'before_ns': time.monotonic_ns(),
               'global_before': disabled(), 'complete': False}
        self.rows.append(row)
        self.save()
        if row['enabled']:
            assert (self.instance / 'tracing_on').read_text().strip() == '0'
            assert all(p.read_text().strip() == '0' for p in self.instance.glob('events/*/*/enable'))
            (self.event / 'enable').write_text('1')
            assert (self.event / 'enable').read_text().strip() == '1'
            self.capture = self.factory(self.instance, self.out, 'pico-callback-phases', 16*1024*1024, self.boot)
            self.capture.start()
        row['ready_ns'] = time.monotonic_ns()
        self.save()

    def finish(self, window):
        assert window < len(self.rows)
        row = self.rows[window]
        if row['complete']:
            return
        row['finish_begin_ns'] = time.monotonic_ns()
        try:
            if self.capture is not None:
                state = self.capture.finish('phase-window-' + str(window))
                row['capture'] = dict(state)
                assert state['joined'] and state['error'] is None and not state['cleanup_errors'], state
                self.capture = None
            row['global_after'] = disabled()
            row['complete'] = True
        finally:
            row['finish_end_ns'] = time.monotonic_ns()
            self.save()

    def cleanup(self):
        errors = self.record['errors']
        if self.created:
            try:
                if self.capture is not None:
                    self.record['cleanup_capture'] = dict(self.capture.finish('phase-cleanup'))
                    assert self.capture.state['joined']
                    self.capture = None
                (self.instance / 'tracing_on').write_text('0')
                for path in self.instance.glob('events/*/*/enable'):
                    if path.read_text().strip() != '0':
                        path.write_text('0')
                self.record['final_global_enables'] = disabled()
                assert (self.instance / 'tracing_on').read_text().strip() == '0'
                self.record['quiesced'] = True
            except BaseException as error:
                errors.append(repr(error))
        self.save()
        assert not errors, errors

    def remove(self, *, all_readers_joined):
        assert all_readers_joined is True, 'All trace readers must join before instance removal'
        assert self.capture is None and not self.record['errors']
        if self.created:
            assert self.record.get('quiesced') is True
            assert (self.instance / 'tracing_on').read_text().strip() == '0'
            self.record['remove_global_enables'] = disabled()
            self.instance.rmdir()
            self.created = False
        self.record['removed'] = True
        self.record['restored'] = True
        self.record['remove_end_ns'] = time.monotonic_ns()
        self.save()
