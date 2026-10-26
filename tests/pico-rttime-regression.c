#define _GNU_SOURCE
#include <errno.h>
#include <sched.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

static uint64_t now(clockid_t clock)
{
    struct timespec ts;
    if (clock_gettime(clock, &ts)) _exit(2);
    return (uint64_t)ts.tv_sec * 1000000000 + ts.tv_nsec;
}

static void burn(uint64_t duration)
{
    uint64_t start = now(CLOCK_THREAD_CPUTIME_ID);
    while (now(CLOCK_THREAD_CPUTIME_ID) - start < duration) {}
}

static void policy(int value)
{
    struct sched_param param = { .sched_priority = value == SCHED_FIFO ? 2 : 0 };
    if (sched_setscheduler(0, value, &param)) _exit(2);
}

static void pause_briefly(long ns)
{
    struct timespec ts = { .tv_nsec = ns };
    while (nanosleep(&ts, &ts)) if (errno != EINTR) _exit(2);
}

enum Mode { BLOCKING, POLICY_ONLY, CONTINUOUS_RT, ORDINARY };

static int check(const char *name, enum Mode mode, int expected_signal)
{
    _Atomic unsigned *rounds = mmap(NULL, sizeof(*rounds), PROT_READ | PROT_WRITE,
                                    MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (rounds == MAP_FAILED) return 1;
    atomic_init(rounds, 0);
    pid_t child = fork();
    if (child < 0) { munmap(rounds, sizeof(*rounds)); return 1; }
    if (!child) {
        struct rlimit realtime = { 80000, 80000 }, cpu = { 2, 2 };
        if (setrlimit(RLIMIT_RTTIME, &realtime) || setrlimit(RLIMIT_CPU, &cpu)) _exit(2);
        for (unsigned i = 0; i < 8; ++i) {
            if (mode != ORDINARY) policy(SCHED_FIFO);
            burn(30000000);
            if (mode == BLOCKING || mode == POLICY_ONLY) policy(SCHED_OTHER);
            if (mode == BLOCKING) pause_briefly(20000000);
            atomic_store(rounds, i + 1);
        }
        _exit(0);
    }
    uint64_t deadline = now(CLOCK_MONOTONIC) + 5000000000;
    int status = 0, timed_out = 0;
    struct rusage usage = { 0 };
    for (;;) {
        pid_t result = wait4(child, &status, WNOHANG, &usage);
        if (result == child) break;
        if (result < 0 && errno != EINTR) {
            kill(child, SIGKILL);
            while (wait4(child, &status, 0, &usage) < 0 && errno == EINTR) {}
            munmap(rounds, sizeof(*rounds));
            return 1;
        }
        if (now(CLOCK_MONOTONIC) >= deadline) {
            timed_out = 1;
            kill(child, SIGKILL);
            while (wait4(child, &status, 0, &usage) < 0 && errno == EINTR) {}
            break;
        }
        pause_briefly(10000000);
    }
    int signal = WIFSIGNALED(status) ? WTERMSIG(status) : 0;
    int exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    unsigned complete = atomic_load(rounds);
    long cpu_us = (usage.ru_utime.tv_sec + usage.ru_stime.tv_sec) * 1000000 +
                  usage.ru_utime.tv_usec + usage.ru_stime.tv_usec;
    int passed = !timed_out && (expected_signal ? signal == expected_signal && complete < 8 &&
                               cpu_us >= 60000 && cpu_us <= 120000 :
                               !signal && exit_code == 0 && complete == 8);
    printf("{\"case\":\"%s\",\"completed_rounds\":%u,\"signal\":%d,\"exit\":%d,"
           "\"cpu_us\":%ld,\"parent_timeout\":%d,\"expected_signal\":%d,\"passed\":%d}\n",
           name, complete, signal, exit_code, cpu_us, timed_out, expected_signal, passed);
    fflush(stdout);
    munmap(rounds, sizeof(*rounds));
    return !passed;
}

int main(int argc, char **argv)
{
    if (argc != 2 || (strcmp(argv[1], "--expect-fixed") && strcmp(argv[1], "--expect-legacy")) ||
        geteuid() != 0 || sched_getscheduler(0) != SCHED_OTHER) {
        fprintf(stderr, "Run as root with ordinary scheduling and --expect-fixed or --expect-legacy\n");
        return 2;
    }
    int failed = check("ordinary", ORDINARY, 0);
    failed |= check("blocking_after_rt", BLOCKING, !strcmp(argv[1], "--expect-legacy") ? SIGKILL : 0);
    failed |= check("policy_change_without_blocking", POLICY_ONLY, SIGKILL);
    failed |= check("continuous_rt", CONTINUOUS_RT, SIGKILL);
    return failed;
}
