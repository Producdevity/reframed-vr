// SPDX-License-Identifier: MIT
#define _GNU_SOURCE
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <dlfcn.h>
#include <errno.h>
#include <stdatomic.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

static const char prio[] = "??VDIWEF";
static atomic_int worker_marker_emitted;

static void candidate_worker(const char *msg, const void *ra)
{
	if (atomic_load_explicit(&worker_marker_emitted, memory_order_relaxed))
		return;
	const char prefix[] = "Paul_BruteMatchPoints_L:";
	const char *enabled = getenv("PICO_CONTROLLER_CANDIDATE_TID");
	if (!enabled || strcmp(enabled, "1") || !msg ||
	    strncmp(msg, prefix, sizeof(prefix) - 1))
		return;
	const char *flag = strchr(msg + sizeof(prefix) - 1, ',');
	if (!flag || flag == msg + sizeof(prefix) - 1 || flag[1] != '1' || flag[2] != ',')
		return;
	Dl_info info;
	if (!dladdr(ra, &info) || !info.dli_fname ||
	    (uintptr_t)ra - (uintptr_t)info.dli_fbase != 0xb9a08)
		return;
	const char *name = strrchr(info.dli_fname, '/');
	if (strcmp(name ? name + 1 : info.dli_fname, "libpico_controller_tracking.pxr.so"))
		return;
	struct timespec now;
	if (clock_gettime(CLOCK_MONOTONIC, &now))
		return;
	long tid = syscall(SYS_gettid);
	if (tid <= 0)
		return;
	int expected = 0;
	if (!atomic_compare_exchange_strong(&worker_marker_emitted, &expected, 1))
		return;
	fprintf(stderr, "{\"event\":\"pico_controller_candidate_worker\",\"version\":1,"
		"\"pid\":%ld,\"tid\":%ld,\"monotonic_ns\":%llu,\"sdk_base\":%llu,"
		"\"caller_pc\":%llu,\"caller_offset\":760328,\"side\":\"L\",\"flag\":1}\n",
		(long)getpid(), tid, (unsigned long long)now.tv_sec * 1000000000ULL + now.tv_nsec,
		(unsigned long long)(uintptr_t)info.dli_fbase, (unsigned long long)(uintptr_t)ra);
}

static void where(const void *ra, char *buf, size_t n)
{
	Dl_info info;
	const char *s;

	buf[0] = 0;
	if (!getenv("STUB_LOG_ADDR") || !dladdr(ra, &info) || !info.dli_fname)
		return;
	s = strrchr(info.dli_fname, '/');
	snprintf(buf, n, " [%s+%#lx]", s ? s + 1 : info.dli_fname,
		 (unsigned long)((const char *)ra - (const char *)info.dli_fbase));
}

static int log_line(int p, const char *tag, const char *msg, const void *ra)
{
	char at[128];

	where(ra, at, sizeof(at));
	int result = fprintf(stderr, "%c/%s%s: %s\n", prio[p & 7], tag ? tag : "", at, msg ? msg : "");
	int original_errno = errno;
	candidate_worker(msg, ra);
	errno = original_errno;
	return result;
}

int __android_log_write(int p, const char *tag, const char *msg)
{
	return log_line(p, tag, msg, __builtin_return_address(0));
}

int __android_log_print(int p, const char *tag, const char *fmt, ...)
{
	char buf[1024];
	va_list ap;

	va_start(ap, fmt);
	vsnprintf(buf, sizeof(buf), fmt, ap);
	va_end(ap);
	return log_line(p, tag, buf, __builtin_return_address(0));
}

int __android_log_vprint(int p, const char *tag, const char *fmt, va_list ap)
{
	char buf[1024];

	vsnprintf(buf, sizeof(buf), fmt, ap);
	return log_line(p, tag, buf, __builtin_return_address(0));
}
