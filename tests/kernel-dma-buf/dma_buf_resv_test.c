#include <linux/dma-fence.h>
#include <linux/dma-fence-array.h>
#include <linux/version.h>
#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 0, 0)
#include <linux/dma-fence-merge.h>
#include <linux/reservation.h>
#define dma_resv reservation_object
#define dma_resv_init reservation_object_init
#define dma_resv_fini reservation_object_fini
#define dma_resv_lock(obj, ctx) ww_mutex_lock(&(obj)->lock, ctx)
#define dma_resv_unlock(obj) ww_mutex_unlock(&(obj)->lock)
#define dma_resv_reserve_shared(obj, count) reservation_object_reserve_shared(obj)
#define dma_resv_add_shared_fence reservation_object_add_shared_fence
#define dma_resv_add_excl_fence_preserve reservation_object_add_excl_fence_preserve
#define dma_resv_test_signaled_rcu reservation_object_test_signaled_rcu
#define dma_resv_wait_timeout_rcu reservation_object_wait_timeout_rcu
#else
#include <linux/dma-resv.h>
#endif
#include <linux/module.h>
#include <linux/of.h>
#include <linux/slab.h>
#include <linux/workqueue.h>

struct test_fence {
    struct dma_fence base;
    spinlock_t lock;
};

struct signal_work {
    struct delayed_work work;
    struct dma_fence *fence;
};

static const char *test_name(struct dma_fence *fence)
{
    return "dmabuf-reservation-test";
}

static const struct dma_fence_ops test_ops = {
    .get_driver_name = test_name,
    .get_timeline_name = test_name,
    .release = dma_fence_free,
};

static struct dma_fence *new_fence(void)
{
    struct test_fence *f = kzalloc(sizeof(*f), GFP_KERNEL);
    if (!f)
        return NULL;
    spin_lock_init(&f->lock);
    dma_fence_init(&f->base, &test_ops, &f->lock, dma_fence_context_alloc(1), 1);
    return &f->base;
}

static void signal_writer(struct work_struct *work)
{
    struct signal_work *signal = container_of(to_delayed_work(work), struct signal_work, work);
    dma_fence_signal(signal->fence);
}

static int exercise(bool wait)
{
    struct dma_fence *reader = new_fence(), *writer = new_fence();
    struct dma_resv reservation;
    struct signal_work signal;
    int ret = -ENOMEM;
    long remaining;

    if (!reader || !writer)
        goto release;
    dma_resv_init(&reservation);
    INIT_DELAYED_WORK(&signal.work, signal_writer);
    signal.fence = writer;
    dma_resv_lock(&reservation, NULL);
    ret = dma_resv_reserve_shared(&reservation, 1);
    if (!ret) {
        dma_resv_add_shared_fence(&reservation, reader);
        ret = dma_resv_add_excl_fence_preserve(&reservation, writer);
    }
    dma_resv_unlock(&reservation);
    if (ret)
        goto cleanup;
    ret = -EINVAL;
    if (wait) {
        schedule_delayed_work(&signal.work, msecs_to_jiffies(10));
        remaining = dma_resv_wait_timeout_rcu(&reservation, true, false, msecs_to_jiffies(100));
        cancel_delayed_work_sync(&signal.work);
        if (remaining != 0 || !dma_fence_is_signaled(writer) || dma_fence_is_signaled(reader))
            goto cleanup;
        dma_fence_signal(reader);
        if (dma_resv_wait_timeout_rcu(&reservation, true, false, 1) <= 0)
            goto cleanup;
        pr_info("DMA_BUF_RESV_WAIT_ALL_PASS\n");
    } else {
        dma_fence_signal(reader);
        if (dma_resv_test_signaled_rcu(&reservation, true) ||
            dma_resv_test_signaled_rcu(&reservation, false))
            goto cleanup;
        dma_fence_signal(writer);
        if (!dma_resv_test_signaled_rcu(&reservation, true))
            goto cleanup;
        pr_info("DMA_BUF_RESV_TEST_SIGNALED_PASS\n");
    }
    ret = 0;
cleanup:
    cancel_delayed_work_sync(&signal.work);
    dma_fence_signal(reader);
    dma_fence_signal(writer);
    dma_resv_fini(&reservation);
release:
    dma_fence_put(reader);
    dma_fence_put(writer);
    return ret;
}

#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 0, 0)
static int exercise_merge(void)
{
    struct dma_fence *sources[3] = {NULL}, *heads[2], *merged = NULL;
    struct dma_fence **children;
    struct dma_fence_array *either = NULL, *array;
    unsigned int i;
    int ret = -ENOMEM;

    for (i = 0; i < 3; ++i) {
        sources[i] = new_fence();
        if (!sources[i])
            goto cleanup;
    }
    children = kmalloc_array(2, sizeof(*children), GFP_KERNEL);
    if (!children)
        goto cleanup;
    children[0] = dma_fence_get(sources[0]);
    children[1] = dma_fence_get(sources[1]);
    either = dma_fence_array_create(2, children, dma_fence_context_alloc(1), 1, true);
    if (!either) {
        dma_fence_put(children[0]);
        dma_fence_put(children[1]);
        kfree(children);
        goto cleanup;
    }
    heads[0] = &either->base;
    heads[1] = sources[2];
    merged = dma_fence_merge_all(2, heads);
    if (!merged)
        goto cleanup;
    ret = -EINVAL;
    array = to_dma_fence_array(merged);
    if (!array || array->num_fences != 2 || array->signal_on_any)
        goto cleanup;
    if (dma_fence_wait_timeout(merged, false, 1) != 0)
        goto cleanup;
    dma_fence_signal(sources[2]);
    if (dma_fence_wait_timeout(merged, false, 1) != 0)
        goto cleanup;
    dma_fence_signal(sources[0]);
    if (dma_fence_wait_timeout(merged, false, msecs_to_jiffies(100)) <= 0 ||
        dma_fence_is_signaled(sources[1]))
        goto cleanup;
    pr_info("DMA_BUF_RESV_MERGE_OR_PASS\n");
    ret = 0;
cleanup:
    for (i = 0; i < 3; ++i)
        if (sources[i])
            dma_fence_signal(sources[i]);
    dma_fence_put(merged);
    if (either)
        dma_fence_put(&either->base);
    for (i = 0; i < 3; ++i)
        dma_fence_put(sources[i]);
    return ret;
}

static int exercise_repeated_merge(void)
{
    struct dma_fence **sources, *merged = NULL, *next, *heads[2];
    struct dma_fence_array *array;
    unsigned int i;
    int ret = -ENOMEM;

    sources = kcalloc(1024, sizeof(*sources), GFP_KERNEL);
    if (!sources)
        return ret;
    for (i = 0; i < 1024; ++i) {
        sources[i] = new_fence();
        if (!sources[i])
            goto cleanup;
        heads[0] = merged;
        heads[1] = sources[i];
        next = dma_fence_merge_all(2, heads);
        if (!next)
            goto cleanup;
        dma_fence_put(merged);
        merged = next;
    }
    ret = -EINVAL;
    array = to_dma_fence_array(merged);
    if (!array || array->num_fences != 1024 || array->signal_on_any)
        goto cleanup;
    for (i = 0; i < array->num_fences; ++i)
        if (dma_fence_is_array(array->fences[i]))
            goto cleanup;
    if (dma_fence_wait_timeout(merged, false, 1) != 0)
        goto cleanup;
    for (i = 0; i < 1023; ++i)
        dma_fence_signal(sources[i]);
    if (dma_fence_wait_timeout(merged, false, 1) != 0)
        goto cleanup;
    dma_fence_signal(sources[1023]);
    if (dma_fence_wait_timeout(merged, false, msecs_to_jiffies(100)) <= 0)
        goto cleanup;
    pr_info("DMA_BUF_RESV_MERGE_1024_FLAT_PASS\n");
    ret = 0;
cleanup:
    for (i = 0; i < 1024; ++i)
        if (sources[i])
            dma_fence_signal(sources[i]);
    dma_fence_put(merged);
    for (i = 0; i < 1024; ++i)
        dma_fence_put(sources[i]);
    kfree(sources);
    return ret;
}
#endif

static int __init test_start(void)
{
    int ret;
    if (!of_machine_is_compatible("linux,dummy-virt"))
        return -ENODEV;
    ret = exercise(false);
    if (!ret)
        ret = exercise(true);
#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 0, 0)
    if (!ret)
        ret = exercise_merge();
    if (!ret)
        ret = exercise_repeated_merge();
#endif
    if (ret)
        pr_err("DMA_BUF_RESV_FAIL=%d\n", ret);
    return ret;
}

static void __exit test_stop(void) {}
module_init(test_start);
module_exit(test_stop);
MODULE_LICENSE("GPL");
