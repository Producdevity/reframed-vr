#include <linux/dma-fence-array.h>
#include <linux/dma-fence-chain.h>
#include <linux/dma-fence-unwrap.h>
#include <linux/file.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <drm/drm_file.h>
#include <drm/drm_drv.h>
#include <drm/drm_ioctl.h>
#include <drm/drm_syncobj.h>

struct fence_refs {
    __s32 fd;
    __u32 handle;
    __u32 refs;
};

#define TEST_REFS _IOWR('T', 0, struct fence_refs)

static struct platform_device *platform;
static struct drm_device *device;

static const struct file_operations drm_test_fops = {
    .owner = THIS_MODULE,
    .open = drm_open,
    .release = drm_release,
    .unlocked_ioctl = drm_ioctl,
    .poll = drm_poll,
    .read = drm_read,
    .llseek = noop_llseek,
};

static struct drm_driver drm_test_driver = {
    .driver_features = DRIVER_RENDER | DRIVER_SYNCOBJ | DRIVER_SYNCOBJ_TIMELINE,
    .fops = &drm_test_fops,
    .name = "reframed-syncobj-test",
    .desc = "QEMU core synchronization test node",
    .date = "20261021",
    .major = 1,
};

static long test_ioctl(struct file *file, unsigned int command, unsigned long arg)
{
    struct fence_refs request;
    struct drm_syncobj *syncobj;
    struct dma_fence *fence;
    struct fd descriptor;
    long ret = -ENOENT;

    if (command != TEST_REFS)
        return -ENOTTY;
    if (copy_from_user(&request, (void __user *)arg, sizeof(request)))
        return -EFAULT;
    descriptor = fdget(request.fd);
    if (!descriptor.file)
        return -EBADF;
    if (descriptor.file->f_op->unlocked_ioctl != drm_ioctl) {
        ret = -EBADF;
        goto out;
    }
    syncobj = drm_syncobj_find(descriptor.file->private_data, request.handle);
    if (!syncobj)
        goto out;
    fence = drm_syncobj_fence_get(syncobj);
    if (fence) {
        request.refs = kref_read(&fence->refcount);
        dma_fence_put(fence);
        ret = copy_to_user((void __user *)arg, &request, sizeof(request)) ? -EFAULT : 0;
    }
    drm_syncobj_put(syncobj);
out:
    fdput(descriptor);
    return ret;
}

static const struct file_operations test_fops = {
    .owner = THIS_MODULE,
    .unlocked_ioctl = test_ioctl,
};

static struct miscdevice test_device = {
    .minor = MISC_DYNAMIC_MINOR,
    .name = "drm-syncobj-test",
    .fops = &test_fops,
    .mode = 0600,
};

struct test_fence {
    struct dma_fence base;
    spinlock_t lock;
};

static const char *test_name(struct dma_fence *fence)
{
    return "drm-syncobj-test";
}

static const struct dma_fence_ops test_ops = {
    .get_driver_name = test_name,
    .get_timeline_name = test_name,
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

static int array_completion(bool either)
{
    struct dma_fence *a = new_fence(), *b = new_fence(), *flat = NULL;
    struct dma_fence **children;
    struct dma_fence_array *array = NULL;
    struct dma_fence_chain *chain = NULL;
    int ret = -ENOMEM;

    if (!a || !b)
        goto out;
    children = kmalloc_array(2, sizeof(*children), GFP_KERNEL);
    if (!children)
        goto out;
    children[0] = dma_fence_get(a);
    children[1] = dma_fence_get(b);
    array = dma_fence_array_create(2, children, dma_fence_context_alloc(1), 1, either);
    if (!array) {
        dma_fence_put(children[0]);
        dma_fence_put(children[1]);
        kfree(children);
        goto out;
    }
    chain = kzalloc(sizeof(*chain), GFP_KERNEL);
    if (!chain)
        goto out;
    dma_fence_chain_init(chain, NULL, dma_fence_get(&array->base), 1ULL << 40);
    flat = dma_fence_unwrap_merge(&chain->base);
    if (!flat)
        goto out;
    ret = -EINVAL;
    if (dma_fence_wait_timeout(flat, false, 1) != 0)
        goto out;
    dma_fence_signal(a);
    if (either) {
        if (dma_fence_wait_timeout(flat, false, HZ) <= 0 || dma_fence_is_signaled(b))
            goto out;
    } else {
        if (dma_fence_wait_timeout(flat, false, 1) != 0)
            goto out;
        dma_fence_signal(b);
        if (dma_fence_wait_timeout(flat, false, HZ) <= 0)
            goto out;
    }
    pr_info("DRM_SYNCOBJ_UNWRAP_%s_PASS\n", either ? "OR" : "AND");
    ret = 0;
out:
    if (a)
        dma_fence_signal(a);
    if (b)
        dma_fence_signal(b);
    dma_fence_put(flat);
    if (chain)
        dma_fence_put(&chain->base);
    if (array)
        dma_fence_put(&array->base);
    dma_fence_put(a);
    dma_fence_put(b);
    return ret;
}

static int sequence_width_and_release(void)
{
    struct dma_fence *head = NULL, *source = new_fence();
    struct dma_fence_chain *chain;
    unsigned int i;
    int ret = -ENOMEM;

    if (!source)
        return ret;
    if (!__dma_fence_is_later(1, U32_MAX, &test_ops) ||
        __dma_fence_is_later(U32_MAX, 1, &test_ops)) {
        ret = -EINVAL;
        goto out;
    }
    if (!__dma_fence_is_later(1ULL << 63, U32_MAX, &dma_fence_chain_ops) ||
        __dma_fence_is_later(1, 1ULL << 63, &dma_fence_chain_ops)) {
        ret = -EINVAL;
        goto out;
    }
    for (i = 0; i < 8192; ++i) {
        chain = kzalloc(sizeof(*chain), GFP_KERNEL);
        if (!chain)
            goto out;
        dma_fence_chain_init(chain, head, dma_fence_get(source), (1ULL << 63) + i);
        head = &chain->base;
    }
    ret = head->seqno == (1ULL << 63) + 8191 ? 0 : -EINVAL;
out:
    dma_fence_put(head);
    dma_fence_put(source);
    if (!ret)
        pr_info("DRM_SYNCOBJ_WIDTH_AND_RELEASE_PASS\n");
    return ret;
}

static int __init test_start(void)
{
    int ret;
    if (!of_machine_is_compatible("linux,dummy-virt"))
        return -ENODEV;
    ret = sequence_width_and_release();
    if (!ret)
        ret = array_completion(false);
    if (!ret)
        ret = array_completion(true);
    if (ret)
        pr_err("DRM_SYNCOBJ_KERNEL_FAIL=%d\n", ret);
    if (ret)
        return ret;
    platform = platform_device_register_simple("reframed-syncobj-test", -1, NULL, 0);
    if (IS_ERR(platform))
        return PTR_ERR(platform);
    device = drm_dev_alloc(&drm_test_driver, &platform->dev);
    if (IS_ERR(device)) {
        ret = PTR_ERR(device);
        goto remove_platform;
    }
    ret = drm_dev_register(device, 0);
    if (ret)
        goto put_device;
    ret = misc_register(&test_device);
    if (!ret)
        return 0;
    drm_dev_unregister(device);
put_device:
    drm_dev_put(device);
remove_platform:
    platform_device_unregister(platform);
    return ret;
}

static void __exit test_stop(void)
{
    misc_deregister(&test_device);
    drm_dev_unregister(device);
    drm_dev_put(device);
    platform_device_unregister(platform);
}
module_init(test_start);
module_exit(test_stop);
MODULE_LICENSE("GPL");
