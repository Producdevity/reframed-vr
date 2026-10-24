#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE
#include <libusb.h>
#include <assert.h>
#include <stdint.h>
#include <time.h>

static __typeof__(libusb_bulk_transfer) mock_bulk;
static __typeof__(clock_gettime) mock_time;
#define libusb_bulk_transfer mock_bulk
#define clock_gettime mock_time
#define main live_usb_main
#include "../tools/pico-live-usb.c"
#undef main
#undef libusb_bulk_transfer
#undef clock_gettime

static const char *incoming;
static size_t at, chunk, calls;
static int fail_bulk;
static time_t elapsed;
static int feedback_mode;
static unsigned char feedback[1024];
static size_t feedback_used, feedback_written;
static int mock_time(clockid_t id, struct timespec *value)
{
    (void)id; value->tv_sec = elapsed++; value->tv_nsec = 0; return 0;
}
static int mock_bulk(libusb_device_handle *handle, unsigned char endpoint,
                     unsigned char *data, int length, int *count, unsigned int timeout)
{
    (void)handle; (void)timeout; ++calls;
    if (fail_bulk) { *count = 0; return LIBUSB_ERROR_NO_DEVICE; }
    if (feedback_mode) {
        if (endpoint & 0x80) {
            size_t size = feedback_used < (size_t)length ? feedback_used : (size_t)length;
            memcpy(data, feedback, size);
            memmove(feedback, feedback + size, feedback_used - size);
            feedback_used -= size;
            *count = (int)size;
            return size ? 0 : LIBUSB_ERROR_TIMEOUT;
        }
        size_t size = sizeof(feedback) - feedback_used;
        if (size > (size_t)length) size = (size_t)length;
        memcpy(feedback + feedback_used, data, size);
        feedback_used += size;
        feedback_written += size;
        *count = (int)size;
        return size == (size_t)length ? 0 : LIBUSB_ERROR_TIMEOUT;
    }
    size_t available = endpoint & 0x80 ? strlen(incoming) - at : (size_t)length;
    size_t size = available < (size_t)length ? available : (size_t)length;
    if (size > chunk) size = chunk;
    if (endpoint & 0x80) memcpy(data, incoming + at, size);
    at += size; *count = (int)size;
    return size ? 0 : LIBUSB_ERROR_TIMEOUT;
}
int main(void)
{
    char output[64];
    for (chunk = 1; chunk <= 64; ++chunk) {
        incoming = "ready\nconsole\nprompt"; at = calls = 0; elapsed = 0;
        struct stream stream = {0};
        assert(!line(NULL, 0x81, &stream, output, sizeof(output), 1000));
        assert(!strcmp(output, "ready\n"));
        assert(!line(NULL, 0x81, &stream, output, sizeof(output), 1000));
        assert(!strcmp(output, "console\n"));
        assert(!memcmp(stream.data + stream.at, "prompt", stream.used - stream.at));
    }
    incoming = "unterminated"; at = elapsed = 0; chunk = 64;
    struct stream stream = {0};
    assert(line(NULL, 0x81, &stream, output, sizeof(output), 20));
    incoming = "too long\n"; at = elapsed = 0; stream = (struct stream){0};
    assert(line(NULL, 0x81, &stream, output, 4, 1000));
    unsigned char bytes[17] = {0}; at = elapsed = calls = 0; chunk = 3;
    assert(!send_bytes(NULL, 0x01, bytes, sizeof(bytes), 1000));
    assert(at == sizeof(bytes) && calls == 6);
    fail_bulk = 1; assert(send_bytes(NULL, 0x01, bytes, sizeof(bytes), 1000));
    fail_bulk = 0;
    unsigned char paste[37469], echoed[sizeof(paste)];
    for (size_t i = 0; i < sizeof(paste); ++i) paste[i] = 'a' + i % 26;
    feedback_mode = 1; feedback_used = feedback_written = elapsed = 0;
    assert(send_bytes(NULL, 0x01, paste, sizeof(paste), 10));
    assert(feedback_written == sizeof(feedback));
    feedback_used = feedback_written = elapsed = 0;
    FILE *typed = tmpfile(), *screen = tmpfile();
    assert(typed && screen);
    assert(fwrite(paste, 1, sizeof(paste), typed) == sizeof(paste));
    rewind(typed);
    assert(!console_session(NULL, 0x81, 0x01, fileno(typed), screen));
    assert(feedback_written == sizeof(paste) && !feedback_used);
    rewind(screen);
    assert(fread(echoed, 1, sizeof(echoed), screen) == sizeof(echoed));
    assert(!memcmp(paste, echoed, sizeof(paste)) && fgetc(screen) == EOF);
    fclose(typed); fclose(screen); feedback_mode = 0;

    char *invalid_resume[] = {"pico-live-usb", "--serial", "c980c8d4", "--console", "--invalid"};
    assert(live_usb_main(5, invalid_resume) == 2);

    char path[] = "/tmp/reframed-live-test.XXXXXX";
    int fd = mkstemp(path); assert(fd >= 0);
    assert(write(fd, "abc", 3) == 3); close(fd);
    size_t size = 0;
    fd = verified_file(path, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", &size);
    assert(fd >= 0 && size == 3); close(fd);
    assert(verified_file(path, "ca7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", &size) < 0);
    char link[128]; snprintf(link, sizeof(link), "%s.link", path);
    assert(!symlink(path, link));
    assert(verified_file(link, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", &size) < 0);
    unlink(link); unlink(path);
    puts("Pico live USB: fragmented records, duplex backpressure, partial writes, timeout, disconnect, arguments, SHA and symlink rejection passed");
    return 0;
}
