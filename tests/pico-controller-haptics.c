#include "pico-controller-haptics.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int main(void)
{
    struct pico_controller_haptic r, before;
    assert(pico_controller_haptic_from_openvr(1, .2f, 128 / 255.f, &r));
    assert(r.hand == 1 && r.level == 128 && r.duration_ms == 200 && pico_controller_haptic_valid(&r));
    uint8_t frame[40];
    assert(pico_controller_haptic_frame(&r, PICO_CONTROLLER_HAPTIC_STOCK_SCALE, frame));
    static const uint8_t golden[8] = {0xaa, 0x02, 0x01, 0x01, 0x60, 0xc8, 0x00, 0x00};
    assert(!memcmp(frame, golden, sizeof(golden)) && frame[39] == 0x2e);

    assert(pico_controller_haptic_from_openvr(2, 0, 1, &r) && r.level == 255 &&
           r.duration_ms == PICO_CONTROLLER_HAPTIC_MIN_MS);
    assert(pico_controller_haptic_from_openvr(2, 60, 3, &r) && r.level == 255 &&
           r.duration_ms == PICO_CONTROLLER_HAPTIC_MAX_MS);
    assert(pico_controller_haptic_from_openvr(1, .05f, 0, &r) && r.level == 0);
    assert(pico_controller_haptic_frame(&r, 75, frame) && frame[3] == 0 && frame[4] == 0 && frame[5] == 0);

    memset(&r, 0x5a, sizeof(r)); before = r;
    assert(!pico_controller_haptic_from_openvr(0, .1f, .5f, &r));
    assert(!pico_controller_haptic_from_openvr(3, .1f, .5f, &r));
    assert(!pico_controller_haptic_from_openvr(1, -.1f, .5f, &r));
    assert(!pico_controller_haptic_from_openvr(1, .1f, -.5f, &r));
    assert(!pico_controller_haptic_from_openvr(1, NAN, .5f, &r));
    assert(!pico_controller_haptic_from_openvr(1, .1f, INFINITY, &r));
    assert(!memcmp(&r, &before, sizeof(r)));
    assert(!pico_controller_haptic_from_openvr(1, .1f, .5f, NULL));

    assert(pico_controller_haptic_from_openvr(1, .1f, .5f, &r));
    struct pico_controller_haptic bad = r; bad.magic ^= 1; assert(!pico_controller_haptic_valid(&bad));
    bad = r; bad.version = 2; assert(!pico_controller_haptic_valid(&bad));
    bad = r; bad.reserved = 1; assert(!pico_controller_haptic_valid(&bad));
    bad = r; bad.duration_ms = 9; assert(!pico_controller_haptic_valid(&bad));
    bad = r; bad.duration_ms = 5001; assert(!pico_controller_haptic_valid(&bad));
    bad = r; bad.hand = 0; assert(!pico_controller_haptic_valid(&bad) && !pico_controller_haptic_frame(&bad, 75, frame));
    assert(!pico_controller_haptic_frame(&r, 101, frame));

    int pipefd[2];
    assert(!pipe(pipefd));
    assert(!fcntl(pipefd[1], F_SETFL, O_NONBLOCK));
    assert(pico_controller_haptic_send(pipefd[1], &r) == 0);
    struct pico_controller_haptic received;
    assert(read(pipefd[0], &received, sizeof(received)) == sizeof(received));
    assert(!memcmp(&received, &r, sizeof(r)) && pico_controller_haptic_valid(&received));
    assert(pico_controller_haptic_send(pipefd[1], &bad) == -EINVAL);
    assert(pico_controller_haptic_send(-1, &r) == -EINVAL);
    int sent = 0, error = 0;
    while (!(error = pico_controller_haptic_send(pipefd[1], &r))) ++sent;
    assert(error == -EAGAIN && sent > 0);
    close(pipefd[0]);
    assert(pico_controller_haptic_send(pipefd[1], &r) == -EPIPE);
    close(pipefd[1]);
    int fifo[2], mcu[2];
    assert(!pipe(fifo) && !pipe(mcu));
    assert(!fcntl(fifo[0], F_SETFL, O_NONBLOCK) && !fcntl(fifo[1], F_SETFL, O_NONBLOCK));
    unsigned rejected = 0;
    assert(pico_controller_haptic_forward(fifo[0], mcu[1], 75, 8, &rejected) == 0 && !rejected);
    assert(pico_controller_haptic_from_openvr(1, .2f, 128 / 255.f, &r));
    assert(!pico_controller_haptic_send(fifo[1], &r));
    bad = r; bad.magic = 0;
    assert(write(fifo[1], &bad, sizeof(bad)) == sizeof(bad));
    assert(pico_controller_haptic_from_openvr(2, 1, 1, &r) && !pico_controller_haptic_send(fifo[1], &r));
    assert(pico_controller_haptic_forward(fifo[0], mcu[1], 75, 8, &rejected) == 2 && rejected == 1);
    uint8_t out[80];
    assert(read(mcu[0], out, sizeof(out)) == 80);
    assert(!memcmp(out, golden, sizeof(golden)) && out[39] == 0x2e);
    assert(out[40] == 0xaa && out[41] == 3 && out[42] == 1 && out[43] == 1 && out[44] == 191 &&
           out[45] == 0xe8 && out[46] == 0x03);
    for (unsigned i = 0; i < 5; ++i) assert(!pico_controller_haptic_send(fifo[1], &r));
    assert(pico_controller_haptic_forward(fifo[0], mcu[1], 75, 3, NULL) == 3);
    assert(pico_controller_haptic_forward(fifo[0], mcu[1], 75, 8, NULL) == 2);
    assert(pico_controller_haptic_forward(fifo[0], mcu[1], 101, 8, NULL) == -EINVAL);
    close(fifo[1]);
    assert(pico_controller_haptic_forward(fifo[0], mcu[1], 75, 8, NULL) == 0);
    close(fifo[0]); close(mcu[0]); close(mcu[1]);
    puts("PICO_CONTROLLER_HAPTICS_PASS");
}
