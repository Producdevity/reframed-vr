/* SPDX-License-Identifier: GPL-2.0-only */
/* Kernel callback excerpts and host mocks for the isolated fence route. */

#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
typedef uint64_t u64;
struct kgsl_device; struct kgsl_event_group {};
typedef void (*kgsl_event_func)(struct kgsl_device *, struct kgsl_event_group *,void *,int);
struct task_struct {int policy,prio;};
struct work_struct {void (*func)(struct work_struct *);};
struct kthread_work {void (*func)(struct kthread_work *);};
struct kthread_worker {struct task_struct *task;};
struct workqueue_struct {};
struct kgsl_context {int id, refs; void *ktimeline;};
struct kgsl_sync_fence_event_priv {struct kgsl_context *context;unsigned timestamp;};
struct kgsl_event {struct kgsl_device *device; struct kgsl_context *context; unsigned timestamp; kgsl_event_func func; void *priv; int node; unsigned created; struct work_struct work; struct kthread_work fence_work; bool rt_dispatch; u64 dispatch_marks[2]; int dispatch_policy,dispatch_prio,result; struct kgsl_event_group *group; int freed;};
struct kgsl_device {struct workqueue_struct *events_wq; struct kthread_worker *fence_worker; int fence_worker_lock; void *dev;};
struct sched_param {int sched_priority;};
struct sched_attr {int policy,prio;};
static struct task_struct task,*current=&task;
static struct kthread_worker kw={.task=&task};
static struct workqueue_struct wq;
static bool fence_rt, trace_enabled, phase_enabled;
static void *events_cache;
static unsigned jiffies;
static int create_error,policy_error,creates,destroys,calls,context_puts,frees,trace_rows,clock_calls,writes,seq,flush_seq,wq_seq,callback_policy,callback_prio,trace_policy,trace_prio,trace_result,last_result;
static u64 stamps[3];
static struct work_struct *queued[32];static int nq;
static struct kthread_work *rtqueued[32];static int nr;
static struct kgsl_event *during_destroy;
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define noinline __attribute__((noinline))
#define READ_ONCE(x) (x)
#define SCHED_FIFO 1
#define KGSL_CONTEXT_ID(p) ((p)->id)
#define INIT_WORK(w,f) ((w)->func=(f))
#define IS_ERR(p) ((intptr_t)(p)<0)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define WARN_ON_ONCE(x) assert(!(x))
#define spin_lock_init(x) (*(x)=0)
#define spin_lock_irqsave(l,f) do {f=0;assert(!*(l));*(l)=1;}while(0)
#define spin_unlock_irqrestore(l,f) do {(void)(f);assert(*(l));*(l)=0;}while(0)
#define dev_info(...) ((void)0)
static void _kgsl_event_worker(struct work_struct *);
static void queue_event(struct kgsl_device *,struct kgsl_event *);
static int task_pid_nr(struct task_struct *p) {return 12;}
static bool trace_kgsl_fence_dispatch_enabled(void) {return trace_enabled;}
static bool trace_kgsl_event_phases_enabled(void) {return phase_enabled;}
static u64 ktime_get_ns(void) {return ++clock_calls*100;}
static void trace_kgsl_fence_dispatch(void *w,unsigned id,unsigned ts,int r,const u64 *m,u64 done,int policy,int prio) {assert(id==7);assert(ts==42);trace_rows++;stamps[0]=m[0];stamps[1]=m[1];stamps[2]=done;trace_policy=policy;trace_prio=prio;trace_result=r;}
#define trace_kgsl_fire_event(id,ts,result,age,func) (last_result=(result))
#define trace_kgsl_event_phases(...) ((void)0)
static int sched_save_priority_and_promote(struct sched_attr *a) {a->policy=current->policy;a->prio=current->prio;current->policy=1;current->prio=59;return 0;}
static int sched_restore_priority(struct sched_attr *a) {current->policy=a->policy;current->prio=a->prio;return 0;}
static void kgsl_context_put(struct kgsl_context *c) {assert(c->refs>0);if(c->refs==1)assert(current->policy==0);--c->refs;context_puts++;}
static void kmem_cache_free(void *cache,struct kgsl_event *e) {assert(!e->freed);e->freed=1;frees++;}
static void list_del(int *node) {assert(*node);*node=0;}
static void kthread_init_work(struct kthread_work *w,void(*f)(struct kthread_work *)) {w->func=f;}
static bool queue_work(struct workqueue_struct *w,struct work_struct *x) {assert(nq<32);queued[nq++]=x;return true;}
static bool kthread_queue_work(struct kthread_worker *w,struct kthread_work *x) {assert(w);assert(nr<32);rtqueued[nr++]=x;return true;}
static void drain_rt(void) {while(nr){struct kthread_work *w=rtqueued[0];memmove(rtqueued,rtqueued+1,--nr*sizeof(*rtqueued));current->policy=1;current->prio=59;w->func(w);}}
static void drain_wq(void) {while(nq){struct work_struct *w=queued[0];memmove(queued,queued+1,--nq*sizeof(*queued));current->policy=0;current->prio=100;w->func(w);}}
static struct kthread_worker *kthread_create_worker(unsigned f,const char *n) {assert(f==0);assert(!strcmp(n,"kgsl-fence"));creates++;return create_error?(void *)(intptr_t)create_error:&kw;}
static int sched_setscheduler_nocheck(struct task_struct *t,int policy,struct sched_param *p) {assert(policy==1&&p->sched_priority==40);if(!policy_error){t->policy=1;t->prio=59;}return policy_error;}
static void kthread_flush_worker(struct kthread_worker *w) {flush_seq=++seq;drain_rt();}
static void flush_workqueue(struct workqueue_struct *w) {wq_seq=++seq;drain_wq();}
static void kthread_destroy_worker(struct kthread_worker *w) {destroys++;if(during_destroy){struct kgsl_event *e=during_destroy;during_destroy=NULL;assert(!e->device->fence_worker);queue_event(e->device,e);}kthread_flush_worker(w);}
static void destroy_workqueue(struct workqueue_struct *w) {flush_workqueue(w);}
static void kgsl_sync_timeline_signal(void *timeline,unsigned ts) {assert(ts==42);calls++;callback_policy=current->policy;callback_prio=current->prio;}
static void kfree(void *priv) {assert(priv);}
static void kgsl_sync_fence_event_cb(struct kgsl_device *,struct kgsl_event_group *,void *,int);
static void other_cb(struct kgsl_device *d,struct kgsl_event_group *g,void *priv,int result) {kgsl_sync_fence_event_cb(d,g,priv,result);}

static void kgsl_sync_fence_event_cb(struct kgsl_device *device,
		struct kgsl_event_group *group, void *priv, int result)
{
	struct kgsl_sync_fence_event_priv *ev = priv;

	kgsl_sync_timeline_signal(ev->context->ktimeline, ev->timestamp);
	kgsl_context_put(ev->context);
	kfree(ev);
}
bool kgsl_sync_is_fence_event(kgsl_event_func func)
{
	return func == kgsl_sync_fence_event_cb;
}
int kgsl_fence_worker_init(struct kgsl_device *device)
{
	struct kthread_worker *worker;
	struct sched_param param = { .sched_priority = 40 };
	int ret;

	spin_lock_init(&device->fence_worker_lock);
	device->fence_worker = NULL;
	if (!fence_rt)
		return 0;

	worker = kthread_create_worker(0, "kgsl-fence");
	if (IS_ERR(worker))
		return PTR_ERR(worker);

	ret = sched_setscheduler_nocheck(worker->task, SCHED_FIFO, &param);
	if (ret) {
		kthread_destroy_worker(worker);
		return ret;
	}

	device->fence_worker = worker;
	dev_info(device->dev, "experimental fence dispatch: FIFO40 pid=%d\n",
		task_pid_nr(worker->task));
	return 0;
}

void kgsl_event_workers_flush(struct kgsl_device *device)
{
	if (device->fence_worker)
		kthread_flush_worker(device->fence_worker);
	flush_workqueue(device->events_wq);
}

void kgsl_event_workers_close(struct kgsl_device *device)
{
	struct kthread_worker *worker;
	unsigned long flags;

	/* Close RT submission before draining either execution domain. */
	spin_lock_irqsave(&device->fence_worker_lock, flags);
	worker = device->fence_worker;
	device->fence_worker = NULL;
	spin_unlock_irqrestore(&device->fence_worker_lock, flags);
	if (worker)
		kthread_destroy_worker(worker);
	destroy_workqueue(device->events_wq);
}

static void _kgsl_event_cleanup(struct work_struct *work)
{
	struct kgsl_event *event = container_of(work, struct kgsl_event, work);

	kgsl_context_put(event->context);
	kmem_cache_free(events_cache, event);
}

static void _kgsl_fence_worker(struct kthread_work *work)
{
	struct kgsl_event *event = container_of(work, struct kgsl_event,
		fence_work);

	if (event->dispatch_marks[0]) {
		if (trace_kgsl_fence_dispatch_enabled()) {
			event->dispatch_marks[1] = ktime_get_ns();
			event->dispatch_policy = READ_ONCE(current->policy);
			event->dispatch_prio = READ_ONCE(current->prio);
		} else {
			event->dispatch_marks[0] = 0;
		}
	}
	_kgsl_event_worker(&event->work);
}

static void finish_event(struct kgsl_event *event)
{
	if (event->dispatch_marks[0] && trace_kgsl_fence_dispatch_enabled())
		trace_kgsl_fence_dispatch(&event->work,
			KGSL_CONTEXT_ID(event->context), event->timestamp,
			event->result, event->dispatch_marks, ktime_get_ns(),
			event->dispatch_policy, event->dispatch_prio);

	/* Final context destruction stays in the reclaim-capable CFS queue. */
	if (event->rt_dispatch)
		queue_work(event->device->events_wq, &event->work);
	else
		_kgsl_event_cleanup(&event->work);
}

static void queue_event(struct kgsl_device *device, struct kgsl_event *event)
{
	unsigned long flags;

	if (!kgsl_sync_is_fence_event(event->func) ||
		!READ_ONCE(device->fence_worker)) {
		queue_work(device->events_wq, &event->work);
		return;
	}

	spin_lock_irqsave(&device->fence_worker_lock, flags);
	if (device->fence_worker) {
		event->rt_dispatch = true;
		INIT_WORK(&event->work, _kgsl_event_cleanup);
		kthread_init_work(&event->fence_work, _kgsl_fence_worker);
		if (trace_kgsl_fence_dispatch_enabled())
			event->dispatch_marks[0] = ktime_get_ns();
		WARN_ON_ONCE(!kthread_queue_work(device->fence_worker,
			&event->fence_work));
	} else {
		queue_work(device->events_wq, &event->work);
	}
	spin_unlock_irqrestore(&device->fence_worker_lock, flags);
}

static inline void signal_event(struct kgsl_device *device,
		struct kgsl_event *event, int result)
{
	list_del(&event->node);
	event->result = result;
	queue_event(device, event);
}

static noinline void _kgsl_event_worker_phases(struct work_struct *work,
		u64 entry_ns)
{
	struct kgsl_event *event = container_of(work, struct kgsl_event, work);
	struct sched_attr sched_attr;
	u64 marks[6];
	int policies[6], results[2];
	int id = KGSL_CONTEXT_ID(event->context);
	unsigned int timestamp = event->timestamp;
	int result = event->result;

	marks[0] = entry_ns;
	policies[0] = READ_ONCE(current->policy);
	policies[1] = READ_ONCE(current->prio);
	memset(&sched_attr, 0, sizeof(struct sched_attr));
	marks[1] = ktime_get_ns();
	trace_kgsl_fire_event(id, event->timestamp, event->result,
		jiffies - event->created, event->func);
	marks[2] = ktime_get_ns();

	results[0] = sched_save_priority_and_promote(&sched_attr);
	marks[3] = ktime_get_ns();
	policies[2] = READ_ONCE(current->policy);
	policies[3] = READ_ONCE(current->prio);
	event->func(event->device, event->group, event->priv, event->result);
	marks[4] = ktime_get_ns();
	results[1] = sched_restore_priority(&sched_attr);
	marks[5] = ktime_get_ns();
	policies[4] = READ_ONCE(current->policy);
	policies[5] = READ_ONCE(current->prio);

	trace_kgsl_event_phases(work, id, timestamp, result, marks,
		policies, results);
	finish_event(event);
}

static void _kgsl_event_worker(struct work_struct *work)
{
	struct kgsl_event *event;
	int id;
	struct sched_attr sched_attr;

	if (trace_kgsl_event_phases_enabled()) {
		_kgsl_event_worker_phases(work, ktime_get_ns());
		return;
	}

	event = container_of(work, struct kgsl_event, work);
	id = KGSL_CONTEXT_ID(event->context);
	memset(&sched_attr, 0, sizeof(struct sched_attr));

	trace_kgsl_fire_event(id, event->timestamp, event->result,
		jiffies - event->created, event->func);

	sched_save_priority_and_promote(&sched_attr);
	event->func(event->device, event->group, event->priv, event->result);
	sched_restore_priority(&sched_attr);

	finish_event(event);
}
static struct kgsl_device d;static struct kgsl_context c,c2;static struct kgsl_event e,e2;static struct kgsl_sync_fence_event_priv priv,priv2;
static void reset(void) {memset(&d,0,sizeof(d));memset(&e,0,sizeof(e));memset(&e2,0,sizeof(e2));memset(&c,0,sizeof(c));memset(&c2,0,sizeof(c2));d.events_wq=&wq;c.id=c2.id=7;c.refs=c2.refs=2;priv.context=&c;priv2.context=&c2;priv.timestamp=priv2.timestamp=42;e.priv=&priv;e2.priv=&priv2;e.device=e2.device=&d;e.context=&c;e2.context=&c2;e.timestamp=e2.timestamp=42;e.func=e2.func=kgsl_sync_fence_event_cb;e.node=e2.node=1;e.result=e2.result=1;INIT_WORK(&e.work,_kgsl_event_worker);INIT_WORK(&e2.work,_kgsl_event_worker);fence_rt=trace_enabled=phase_enabled=false;create_error=policy_error=creates=destroys=calls=context_puts=frees=trace_rows=clock_calls=writes=seq=flush_seq=wq_seq=nq=nr=0;during_destroy=NULL;task.policy=0;task.prio=100;}
int main(void) {
 int tests=0;
 reset(); assert(kgsl_fence_worker_init(&d)==0&&!d.fence_worker&&creates==0);queue_event(&d,&e);assert(nq==1&&nr==0&&!e.rt_dispatch);drain_wq();assert(calls==1&&frees==1&&clock_calls==0);tests++;
 reset();fence_rt=true;create_error=-ENOMEM;assert(kgsl_fence_worker_init(&d)==-ENOMEM&&!d.fence_worker&&destroys==0);tests++;
 reset();fence_rt=true;policy_error=-EPERM;assert(kgsl_fence_worker_init(&d)==-EPERM&&!d.fence_worker&&destroys==1);tests++;
 reset();fence_rt=true;assert(!kgsl_fence_worker_init(&d));assert(d.fence_worker&&task.policy==1&&task.prio==59);tests++;
 reset();fence_rt=true;assert(!kgsl_fence_worker_init(&d));e.func=other_cb;queue_event(&d,&e);assert(nq==1&&nr==0&&!e.rt_dispatch);drain_wq();assert(calls==1&&frees==1);tests++;
 reset();fence_rt=true;assert(!kgsl_fence_worker_init(&d));queue_event(&d,&e);assert(nr==1&&nq==0&&e.rt_dispatch);drain_rt();assert(calls==1&&!frees&&nq==1&&callback_policy==1&&callback_prio==59&&clock_calls==0);drain_wq();assert(frees==1&&context_puts==2);tests++;
 reset();fence_rt=true;assert(!kgsl_fence_worker_init(&d));signal_event(&d,&e,2);assert(!e.node&&e.result==2&&nr==1);drain_rt();drain_wq();assert(calls==1&&last_result==2&&frees==1);tests++;
 reset();fence_rt=true;assert(!kgsl_fence_worker_init(&d));queue_event(&d,&e);kgsl_event_workers_flush(&d);assert(calls==1&&frees==1&&flush_seq<wq_seq);tests++;
 reset();fence_rt=true;assert(!kgsl_fence_worker_init(&d));queue_event(&d,&e);during_destroy=&e2;kgsl_event_workers_close(&d);assert(!d.fence_worker&&destroys==1&&calls==2&&frees==2&&nr==0&&nq==0&&!e2.rt_dispatch&&flush_seq<wq_seq);tests++;
 reset();assert(!kgsl_fence_worker_init(&d));queue_event(&d,&e);kgsl_event_workers_close(&d);assert(destroys==0&&frees==1);tests++;
 reset();fence_rt=trace_enabled=true;assert(!kgsl_fence_worker_init(&d));queue_event(&d,&e);assert(clock_calls==1);drain_rt();assert(trace_rows==1&&clock_calls==3&&stamps[0]<stamps[1]&&stamps[1]<stamps[2]&&trace_policy==1&&trace_prio==59&&trace_result==1&&!frees);drain_wq();assert(frees==1);tests++;
 reset();fence_rt=true;assert(!kgsl_fence_worker_init(&d));queue_event(&d,&e);trace_enabled=true;drain_rt();assert(!trace_rows&&!clock_calls);drain_wq();tests++;
 reset();fence_rt=trace_enabled=true;assert(!kgsl_fence_worker_init(&d));queue_event(&d,&e);trace_enabled=false;drain_rt();assert(!trace_rows&&clock_calls==1);drain_wq();tests++;
 reset();fence_rt=phase_enabled=true;assert(!kgsl_fence_worker_init(&d));queue_event(&d,&e);drain_rt();assert(calls==1&&!frees&&nq==1);drain_wq();assert(frees==1);tests++;
 printf("%d source-extracted C lifecycle cases passed\n",tests);
}
