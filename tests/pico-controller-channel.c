#include "pico-controller-channel.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>

static struct pico_controller_channel channel;
static int64_t clock_value;
static int64_t clock_ns(void *unused) { (void)unused; return clock_value; }

static void *writer(void *unused)
{
    (void)unused;
    for (unsigned n = 1; n <= 50000; n++) {
        struct pico_controller_sample sample = {
            .hand = 1, .trigger = n & 255, .grip = n & 255,
            .stick_x = n & 255, .stick_y = n & 255};
        assert(pico_controller_channel_publish(&channel, &sample, n));
    }
    return NULL;
}

int main(int argc, char **argv)
{
    struct pico_controller_sample sample = {.hand = 1, .buttons = PICO_BUTTON_TRIGGER, .touches = 16};
    struct pico_controller_sample out, sentinel;
    memset(&sentinel, 0xa7, sizeof(sentinel));out = sentinel;
    assert(!pico_controller_channel_init(NULL, 1));
    assert(!pico_controller_channel_init(&channel, 0));
    assert(pico_controller_channel_init(&channel, 7));
    clock_value = 100;
    assert(!pico_controller_channel_read(&channel, 7, 1, clock_ns, NULL, 50, &out));
    assert(!memcmp(&out, &sentinel, sizeof(out)));
    assert(pico_controller_channel_publish(&channel, &sample, 100));
    assert(!pico_controller_channel_publish(&channel, &sample, 100));
    assert(!pico_controller_channel_publish(&channel, &sample, 99));
    assert(!pico_controller_channel_read(&channel, 8, 1, clock_ns, NULL, 50, &out));
    assert(!pico_controller_channel_read(&channel, 7, 2, clock_ns, NULL, 50, &out));
    assert(pico_controller_channel_read(&channel, 7, 1, clock_ns, NULL, 50, &out));
    assert(!memcmp(&out, &sample, sizeof(out)));
    clock_value = 99;
    assert(!pico_controller_channel_read(&channel, 7, 1, clock_ns, NULL, 50, &out));
    clock_value = 150;
    assert(pico_controller_channel_read(&channel, 7, 1, clock_ns, NULL, 50, &out));
    clock_value = 151;
    assert(!pico_controller_channel_read(&channel, 7, 1, clock_ns, NULL, 50, &out));
    assert(pico_controller_channel_disconnect(&channel, 1));
    assert(!pico_controller_channel_read(&channel, 7, 1, clock_ns, NULL, 50, &out));
    assert(!pico_controller_channel_publish(&channel, &sample, 100));
    assert(pico_controller_channel_publish(&channel, &sample, 151));
    assert(pico_controller_channel_read(&channel, 7, 1, clock_ns, NULL, 50, &out));
    __atomic_fetch_add(&channel.sequence[0], 1, __ATOMIC_RELAXED);
    assert(pico_controller_channel_read(&channel, 7, 1, clock_ns, NULL, 50, &out));
    assert(!pico_controller_channel_publish(&channel, &sample, 152));
    assert(pico_controller_channel_init(&channel, 7));
    clock_value = 50000;
    pthread_t thread;assert(!pthread_create(&thread, NULL, writer, NULL));
    unsigned accepted = 0;
    for (unsigned n = 0; n < 50000; n++) {
        if (pico_controller_channel_read(&channel, 7, 1, clock_ns, NULL, 50000, &out)) {
            assert(out.hand == 1 && out.trigger == out.grip && out.trigger == out.stick_x && out.trigger == out.stick_y);
            accepted++;
        }
    }
    assert(!pthread_join(thread, NULL));
    assert(pico_controller_channel_read(&channel, 7, 1, clock_ns, NULL, 50000, &out));
    assert(out.trigger == (50000 & 255));
    unsigned replayed = 0, changed = 0;
    if (argc == 2) {
        FILE *file = fopen(argv[1], "rb");assert(file);
        uint8_t record[100], previous = 0;
        assert(pico_controller_channel_init(&channel, 9));
        size_t bytes;
        while ((bytes = fread(record, 1, sizeof(record), file)) != 0) {
            assert(bytes == sizeof(record));
            assert(pico_controller_decode(record, sizeof(record), 1, 2, true, &sample));
            clock_value = ++replayed;
            assert(pico_controller_channel_publish(&channel, &sample, clock_value));
            assert(pico_controller_channel_read(&channel, 9, 1, clock_ns, NULL, 50, &out));
            assert(!memcmp(&sample, &out, sizeof(out)));
            changed += out.buttons != previous;previous = out.buttons;
        }
        assert(feof(file) && !ferror(file));fclose(file);assert(replayed);
    }
    printf("PICO_CONTROLLER_CHANNEL_PASS concurrent_reads=%u replayed=%u button_changes=%u\n", accepted, replayed, changed);
}
