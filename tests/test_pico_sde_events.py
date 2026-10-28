import importlib.util
from pathlib import Path
import unittest


SPEC = importlib.util.spec_from_file_location(
    'sde_events', Path(__file__).resolve().parents[1] / 'tools/pico-sde-events.py')
SDE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SDE)


def body(tag='sde_encoder_phys_vid_vblank_irq', line=548, data=None):
    data = data if data is not None else [28, 1, 1, 0, 0, 0, 25, 0, 10]
    return f'527|{tag}:{line}' + ''.join(f'|0x{x:x}' for x in data + [0] * (15 - len(data)))


class PicoSdeEventsTests(unittest.TestCase):
    def test_irq_preserves_sampled_and_later_fields_without_inventing_a_sequence(self):
        row = SDE.decode_body(body(data=[28, 1, 0, 1, 0, 0, 0, 1, 10]))
        self.assertEqual((row['pending_before'], row['pending_at_log']), (0, 1))
        self.assertTrue(row['flush_sample_known'])
        self.assertEqual(row['completion_event'], 0)
        self.assertNotIn('sequence', row)
        self.assertNotIn('consumed_present', row)
        self.assertNotIn('crtc', row)
        sentinel = SDE.decode_body(body(data=[28, 1, 1, 1, 0, 0xffffffff, 0, 1, 10]))
        self.assertFalse(sentinel['flush_sample_known'])
        self.assertEqual(sentinel['flush_register'], 0xffffffff)

    def test_both_flush_branches_use_the_source_specific_count(self):
        row = SDE.decode_body(body('_sde_encoder_trigger_flush', 4371, [28, 1, 0, 123, 1]))
        self.assertEqual(row['software_flush_mask'], 123)
        self.assertEqual(row['retire_at_log'], 1)
        fallback = SDE.decode_body(body('_sde_encoder_trigger_flush', 4375, [28, 1, 0, 1]))
        self.assertEqual(fallback['retire_at_log'], 1)
        self.assertNotIn('software_flush_mask', fallback)

    def test_rejects_truncation_unknown_sources_and_padding(self):
        good = body()
        bad = [good.rsplit('|', 1)[0], good + '|0x0', good + '\n',
               good.replace(':548', ':549'), good.replace('0x1c', '0x100000000'),
               good.replace('0x1c', '0x1C'), good.replace('527|', '-1|'),
               good.replace('527|', '2147483648|'),
               body(data=[28, 1, 1, 0, 0, 0, 25, 0, 10, 1]),
               body('_sde_encoder_trigger_flush', 4375, [28, 1, 0, 1, 1])]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                SDE.decode_body(value)

    def test_format_requires_exact_data_layout(self):
        text = 'name: sde_evtlog\n'
        for name, (offset, size, signed) in SDE.LAYOUT.items():
            text += f'\tfield:{name};\toffset:{offset};\tsize:{size};\tsigned:{signed};\n'
        text += 'print fmt: "%d|%s:%d' + '|0x%x' * 15 + '", REC->pid, __get_str(evtlog_tag), REC->tag_id'
        text += ', '.join([''] + [f'REC->data[{i}]' for i in range(15)]) + '\n'
        self.assertEqual(SDE.validate_format(text), SDE.LAYOUT)
        for bad in [text.replace('size:60', 'size:56'), text.replace('offset:20', 'offset:24'),
                    text.replace('u32 data[15]', 'u32 data[14]'),
                    text.replace('REC->data[5]', 'REC->data[6]'),
                    text.replace('REC->data[5]', 'TEMP').replace('REC->data[6]', 'REC->data[5]').replace('TEMP', 'REC->data[6]'),
                    text.replace('REC->pid,', 'REC->tag_id,'),
                    text.replace('field:int common_pid;\toffset:4;', 'field:int common_pid;\toffset:8;'),
                    text.replace('name: sde_evtlog', 'name: other'),
                    text + '\tfield:int pid; offset:8; size:4; signed:1;\n']:
            with self.subTest(text=bad), self.assertRaises(ValueError):
                SDE.validate_format(bad)
