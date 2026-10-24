#define _POSIX_C_SOURCE 200809L
#define _DARWIN_C_SOURCE
#include <libusb.h>
#include <openssl/evp.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

static struct termios saved_terminal;
static int terminal_changed;

static void restore_terminal(void)
{
    if (terminal_changed) (void)tcsetattr(STDIN_FILENO, TCSANOW, &saved_terminal);
}

static int console_input(void)
{
    if (!isatty(STDIN_FILENO)) return 0;
    if (tcgetattr(STDIN_FILENO, &saved_terminal)) return -1;
    struct termios value = saved_terminal;
    value.c_iflag &= ~(IGNBRK | BRKINT | PARMRK | ISTRIP | INLCR | IGNCR | ICRNL | IXON | IXOFF);
    value.c_lflag &= ~(ECHO | ECHONL | ICANON | ISIG | IEXTEN);
    value.c_cc[VMIN] = 1;
    value.c_cc[VTIME] = 0;
    if (tcsetattr(STDIN_FILENO, TCSANOW, &value)) return -1;
    terminal_changed = 1;
    return atexit(restore_terminal);
}

static double seconds(void)
{
    struct timespec value;
    if (clock_gettime(CLOCK_MONOTONIC, &value)) exit(1);
    return value.tv_sec + value.tv_nsec / 1e9;
}

static int matches(libusb_device_handle *handle, unsigned char index, const char *text)
{
    unsigned char value[256];
    int size = libusb_get_string_descriptor_ascii(handle, index, value, sizeof(value));
    return size >= 0 && (size_t)size == strlen(text) && !memcmp(value, text, (size_t)size);
}

static int endpoints(libusb_device *device, unsigned char *input, unsigned char *output)
{
    struct libusb_config_descriptor *config = NULL;
    if (libusb_get_config_descriptor_by_value(device, 1, &config)) return 0;
    int valid = config->bConfigurationValue == 1 && config->bNumInterfaces == 1 && config->interface[0].num_altsetting == 1;
    if (valid) {
        const struct libusb_interface_descriptor *value = config->interface[0].altsetting;
        valid = value->bInterfaceNumber == 0 && value->bAlternateSetting == 0 &&
            value->bInterfaceClass == 0xff && value->bInterfaceSubClass == 0 &&
            value->bInterfaceProtocol == 0 && value->bNumEndpoints == 2;
        int inputs = 0, outputs = 0;
        for (int i = 0; valid && i < 2; ++i) {
            const struct libusb_endpoint_descriptor *ep = value->endpoint + i;
            valid = (ep->bmAttributes & LIBUSB_TRANSFER_TYPE_MASK) == LIBUSB_TRANSFER_TYPE_BULK;
            if (ep->bEndpointAddress & LIBUSB_ENDPOINT_IN) { *input = ep->bEndpointAddress; ++inputs; }
            else { *output = ep->bEndpointAddress; ++outputs; }
        }
        valid = valid && inputs == 1 && outputs == 1;
    }
    libusb_free_config_descriptor(config);
    return valid;
}

static int send_bytes(libusb_device_handle *handle, unsigned char endpoint,
                      unsigned char *data, int size, double deadline)
{
    int sent = 0;
    while (sent < size && seconds() < deadline) {
        int transferred = 0;
        int result = libusb_bulk_transfer(handle, endpoint, data + sent, size - sent, &transferred, 1000);
        if (transferred < 0 || transferred > size - sent) return -1;
        sent += transferred;
        if (result && result != LIBUSB_ERROR_TIMEOUT) {
            fprintf(stderr, "USB write endpoint 0x%02x: %s (%d/%d bytes sent)\n",
                    endpoint, libusb_error_name(result), sent, size);
            return -1;
        }
    }
    return sent == size ? 0 : -1;
}

struct stream { unsigned char data[4096]; size_t at, used; };

static int line(libusb_device_handle *handle, unsigned char endpoint, struct stream *stream,
                char *value, size_t capacity, double deadline)
{
    size_t used = 0;
    while (used + 1 < capacity && seconds() < deadline) {
        if (stream->at < stream->used) {
            unsigned char byte = stream->data[stream->at++];
            value[used++] = (char)byte;
            if (byte == '\n') { value[used] = 0; return 0; }
            continue;
        }
        int transferred = 0;
        int status = libusb_bulk_transfer(handle, endpoint, stream->data, sizeof(stream->data), &transferred, 1000);
        if (transferred < 0 || transferred > (int)sizeof(stream->data)) return -1;
        stream->at = 0;
        stream->used = (size_t)transferred;
        if (status && status != LIBUSB_ERROR_TIMEOUT) return -1;
    }
    return -1;
}

static int verified_file(const char *path, const char *expected, size_t *size)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    struct stat info;
    if (fd < 0) return -1;
    if (fstat(fd, &info) || !S_ISREG(info.st_mode) || info.st_size <= 0 || info.st_size > 3LL * 1024 * 1024 * 1024) {
        close(fd); return -1;
    }
    EVP_MD_CTX *hash = EVP_MD_CTX_new();
    unsigned char data[1024 * 1024], result[32];
    unsigned int length = 0;
    int ok = hash && EVP_DigestInit_ex(hash, EVP_sha256(), NULL);
    ssize_t count = 0;
    size_t read_bytes = 0;
    while (ok && (count = read(fd, data, sizeof(data))) > 0) {
        read_bytes += (size_t)count;
        ok = EVP_DigestUpdate(hash, data, (size_t)count);
    }
    ok = ok && count == 0 && read_bytes == (size_t)info.st_size &&
        EVP_DigestFinal_ex(hash, result, &length) && length == 32;
    EVP_MD_CTX_free(hash);
    char actual[65];
    for (size_t i = 0; ok && i < 32; ++i) snprintf(actual + 2 * i, 3, "%02x", result[i]);
    if (!ok || strcmp(actual, expected) || lseek(fd, 0, SEEK_SET) != 0) { close(fd); return -1; }
    *size = read_bytes;
    return fd;
}

static int console_session(libusb_device_handle *handle, unsigned char input,
                           unsigned char output, int input_fd, FILE *screen)
{
    unsigned char data[1024 * 1024];
    double deadline = seconds() + 1900;
    while (seconds() < deadline) {
        int transferred = 0;
        int status = libusb_bulk_transfer(handle, input, data, sizeof(data), &transferred, 100);
        if (transferred < 0 || transferred > (int)sizeof(data)) return 1;
        if (transferred && (fwrite(data, 1, (size_t)transferred, screen) != (size_t)transferred || fflush(screen))) return 1;
        if (status && status != LIBUSB_ERROR_TIMEOUT) {
            fprintf(stderr, "USB read endpoint 0x%02x: %s (%d bytes received)\n",
                    input, libusb_error_name(status), transferred);
            return 1;
        }
        struct pollfd stdin_poll = {.fd = input_fd, .events = POLLIN};
        if (poll(&stdin_poll, 1, 0) < 0 && errno != EINTR) return 1;
        if (stdin_poll.revents & POLLIN) {
            /* Drain output between input packets, including during a large paste. */
            ssize_t count = read(input_fd, data, 512);
            if (count <= 0) break;
            if (send_bytes(handle, output, data, (int)count, seconds() + 10)) {
                fputs("Console input transfer timed out or disconnected.\n", stderr);
                return 1;
            }
        }
        if (stdin_poll.revents & (POLLHUP | POLLERR | POLLNVAL)) break;
    }
    return 0;
}

int main(int argc, char **argv)
{
    int console = (argc == 4 || argc == 5) && !strcmp(argv[3], "--console");
    int resume = console && argc == 5 && !strcmp(argv[4], "--resume");
    if ((argc != 7 && !console) || (console && argc == 5 && !resume) || strcmp(argv[1], "--serial") ||
        (!console && (strcmp(argv[3], "--root") || strcmp(argv[5], "--sha256"))) ||
        !strlen(argv[2]) || strlen(argv[2]) > 64 || !strcmp(argv[2], "qemu") ||
        strspn(argv[2], "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-") != strlen(argv[2]) ||
        (!console && (strlen(argv[6]) != 64 || strspn(argv[6], "0123456789abcdef") != 64))) {
        fputs("Usage: pico-live-usb --serial SERIAL (--console [--resume] | --root ROOT.SQUASHFS --sha256 EXPECTED)\n", stderr);
        return 2;
    }
    size_t bytes = 0;
    int file = console ? -1 : verified_file(argv[4], argv[6], &bytes);
    if (!console && file < 0) { fputs("Root file size, type or SHA-256 verification failed.\n", stderr); return 1; }
    libusb_context *context = NULL;
    libusb_device_handle *handle = NULL;
    unsigned char input = 0, output = 0;
    int claimed = 0, result = 1;
    if (libusb_init(&context)) { if (file >= 0) close(file); return 1; }
    double deadline = seconds() + 90;
    do {
        libusb_device **devices = NULL;
        ssize_t count = libusb_get_device_list(context, &devices);
        int found = 0;
        if (count < 0) goto done;
        for (ssize_t i = 0; i < count; ++i) {
            struct libusb_device_descriptor d;
            if (libusb_get_device_descriptor(devices[i], &d) || d.idVendor != 0x1d6b || d.idProduct != 0x0104) continue;
            libusb_device_handle *candidate = NULL;
            if (libusb_open(devices[i], &candidate)) continue;
            if (matches(candidate, d.iManufacturer, "Reframed VR") &&
                matches(candidate, d.iProduct, "Reframed VR Pico diagnostic") && matches(candidate, d.iSerialNumber, argv[2])) {
                ++found;
                if (!handle && endpoints(devices[i], &input, &output)) { handle = candidate; continue; }
            }
            libusb_close(candidate);
        }
        libusb_free_device_list(devices, 1);
        if (found > 1) goto done;
        if (handle) break;
        const struct timespec delay = {.tv_nsec = 250000000};
        nanosleep(&delay, NULL);
    } while (seconds() < deadline);
    if (!handle) { fputs("No unique available Pico interface; no driver detached.\n", stderr); goto done; }
    int configuration = -1;
    if (libusb_get_configuration(handle, &configuration) ||
        (configuration == 0 && libusb_set_configuration(handle, 1)) ||
        (configuration != 0 && configuration != 1) || libusb_claim_interface(handle, 0)) goto done;
    claimed = 1;
    char expected[256], value[4096];
    struct stream stream = {0};
    unsigned char data[1024 * 1024];
    if (!console) {
        snprintf(expected, sizeof(expected), "REFRAMED_LIVE_READY serial=%s bytes=%zu sha256=%s\n", argv[2], bytes, argv[6]);
        int handshake = line(handle, input, &stream, value, sizeof(value), seconds() + 90);
        if (handshake || strcmp(value, expected)) {
            fputs("Wrong or missing root-transfer handshake; nothing sent.\n", stderr);
            if (!handshake) fprintf(stderr, "Received: %.256s\n", value);
            goto done;
        }
        fputs(value, stdout); fflush(stdout);
        size_t sent = 0;
        deadline = seconds() + 2100;
        double transfer_start = seconds();
        while (sent < bytes) {
            size_t want = bytes - sent < sizeof(data) ? bytes - sent : sizeof(data);
            ssize_t count = read(file, data, want);
            if (count <= 0 || send_bytes(handle, output, data, (int)count, deadline)) goto done;
            sent += (size_t)count;
            if (!(sent % (8 * 1024 * 1024)) || sent == bytes)
                fprintf(stderr, "Root transfer %zu/%zu bytes, %.2f MiB/s\n", sent, bytes,
                        sent / (1024.0 * 1024.0 * (seconds() - transfer_start)));
        }
        fprintf(stderr, "Transfer complete; waiting for verified root and Linux console.\n");
    }
    deadline = seconds() + 240;
    snprintf(expected, sizeof(expected), "REFRAMED_LIVE_CONSOLE serial=%s\n", argv[2]);
    if (!resume) {
        do {
            if (line(handle, input, &stream, value, sizeof(value), deadline)) goto done;
            fputs(value, stdout); fflush(stdout);
        } while (strcmp(value, expected));
    }
    if (fwrite(stream.data + stream.at, 1, stream.used - stream.at, stdout) != stream.used - stream.at || fflush(stdout)) goto done;
    if (console_input()) goto done;
    result = console_session(handle, input, output, STDIN_FILENO, stdout);
done:
    if (claimed) libusb_release_interface(handle, 0);
    if (handle) libusb_close(handle);
    libusb_exit(context);
    if (file >= 0) close(file);
    return result;
}
