#!/usr/bin/env python3
"""Decode the Neo3 vendor kernel's selected SDE event bodies.

Callers must separately qualify source identity, complete trace coverage, loss,
clock, encoder identity and handler-local DRM associations. These records do
not contain a CRTC ID, DRM sequence or physical display timestamp.
"""
import re


FILTER = ('evtlog_tag == "sde_encoder_phys_vid_vblank_irq" || '
          'evtlog_tag == "_sde_encoder_trigger_flush"')
COUNTS = {('sde_encoder_phys_vid_vblank_irq', 548): 9,
          ('_sde_encoder_trigger_flush', 4371): 5,
          ('_sde_encoder_trigger_flush', 4375): 4}
LAYOUT = {
    'unsigned short common_type': (0, 2, 0),
    'unsigned char common_flags': (2, 1, 0),
    'unsigned char common_preempt_count': (3, 1, 0),
    'int common_pid': (4, 4, 1),
    'int pid': (8, 4, 1),
    '__data_loc char[] evtlog_tag': (12, 4, 0),
    'u32 tag_id': (16, 4, 0),
    'u32 data[15]': (20, 60, 0),
}
BODY = re.compile(r'(0|[1-9][0-9]*)\|([a-z_]+):(0|[1-9][0-9]*)'
                  r'((?:\|0x[0-9a-f]{1,8}){15})')


def validate_format(text):
    if not isinstance(text, str) or len(text) > 16384:
        raise ValueError('Expected bounded SDE trace format')
    names = re.findall(r'^name: (\w+)$', text, re.M)
    if names != ['sde_evtlog']:
        raise ValueError('Unexpected SDE event name')
    fields = re.findall(r'^\s*field:([^;]+);\s*offset:(\d+);\s*size:(\d+);'
                        r'\s*signed:(\d+);\s*$', text, re.M)
    selected = {}
    for field, offset, size, signed in fields:
        if field in selected:
            raise ValueError('Duplicate SDE trace field')
        selected[field] = tuple(map(int, (offset, size, signed)))
    expected_print = 'print fmt: "%d|%s:%d' + '|0x%x' * 15 + '"'
    expected_print += ', REC->pid, __get_str(evtlog_tag), REC->tag_id'
    expected_print += ''.join(', REC->data[' + str(i) + ']' for i in range(15))
    prints = re.findall(r'^print fmt:.*$', text, re.M)
    if (selected != LAYOUT or len(prints) != 1 or
            ''.join(prints[0].split()) != ''.join(expected_print.split())):
        raise ValueError('Unsupported SDE event layout')
    return dict(selected)


def decode_body(body):
    match = BODY.fullmatch(body) if isinstance(body, str) and len(body) <= 1024 else None
    if match is None:
        raise ValueError('Malformed SDE event body')
    tgid, tag, line, words = match.groups()
    tgid, line = int(tgid), int(line)
    count = COUNTS.get((tag, line))
    data = [int(word, 16) for word in words.split('|')[1:]]
    if tgid > 2147483647 or count is None or any(data[count:]):
        raise ValueError('Unsupported SDE source line or nonzero padding')
    result = {'tgid': tgid, 'tag': tag, 'source_line': line,
              'encoder': data[0], 'interface': data[1]}
    if tag == 'sde_encoder_phys_vid_vblank_irq':
        result.update(pending_before=data[2], pending_at_log=data[3],
                      reset_error=data[4], flush_register=data[5],
                      completion_event=data[6], retire_at_log=data[7],
                      hardware_frame_count=data[8],
                      flush_sample_known=data[5] != 0xffffffff)
    else:
        result.update(control=data[2], retire_at_log=data[count - 1])
        if count == 5:
            result['software_flush_mask'] = data[3]
    return result
