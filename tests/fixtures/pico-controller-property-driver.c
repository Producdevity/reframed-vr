#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

int __system_property_get(const char *, char *);

static void *read_many(void *unused)
{
    (void)unused;
    for (unsigned i = 0; i < 100; ++i) {
        char buffer[92];
        memset(buffer, 0x55, sizeof(buffer));
        assert(__system_property_get("persist.pxr.picoController.log", buffer) == 1);
        assert((buffer[0] == '1' || buffer[0] == '0') && buffer[1] == 0 && buffer[2] == 0x55);
    }
    return NULL;
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    char buffer[92];
    memset(buffer, 0x55, sizeof(buffer));
    int enabled = !strcmp(argv[1], "on");
    int count = __system_property_get("persist.pxr.picoController.log", buffer);
    assert(count == (enabled ? 1 : 8));
    assert(!strcmp(buffer, enabled ? "1" : "original"));
    assert(__system_property_get("fallback", buffer) == 14);
    assert(!strcmp(buffer, "fallback-value"));
    memset(buffer, 0x55, sizeof(buffer));
    assert(__system_property_get("failure", buffer) == -7 && buffer[0] == 0x55);

    if (enabled) {
        pthread_t threads[16];
        for (unsigned i = 0; i < 16; ++i)
            assert(!pthread_create(&threads[i], NULL, read_many, NULL));
        for (unsigned i = 0; i < 16; ++i)
            assert(!pthread_join(threads[i], NULL));
        struct timespec delay = {6, 100000000};
        while (nanosleep(&delay, &delay)) {}
        assert(__system_property_get("persist.pxr.picoController.log", buffer) == 1);
        assert(!strcmp(buffer, "0"));
    }

    uint64_t (*exact)(void) = dlsym(RTLD_DEFAULT, "pico_controller_verbose_exact_key_reads");
    uint64_t (*delegated)(void) = dlsym(RTLD_DEFAULT, "pico_controller_verbose_delegated_reads");
    assert(exact && delegated);
    assert(exact() == (enabled ? 1602u : 0u));
    assert(delegated() == (enabled ? 2u : 3u));
    puts("PASS property delegation, return/buffer ABI, exact opt-in, concurrent queries and expiry");
    return 0;
}
