#include "pico-steamvr-probe-gate.h"
#include <cerrno>
#include <cstddef>
#include <cstring>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/un.h>
#include <unistd.h>

int pico_steamvr_probe_gate(const char *path, unsigned timeout_ms)
{
    if (!path) return 0;
    sockaddr_un address{};
    if (!*path || *path != '/' || std::strlen(path) >= sizeof(address.sun_path) ||
        !timeout_ms || timeout_ms > 5000) return EINVAL;
    address.sun_family = AF_UNIX;
    std::memcpy(address.sun_path, path, std::strlen(path) + 1);
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return errno;
    int error = 0;
    timeval timeout{static_cast<time_t>(timeout_ms / 1000),
                    static_cast<suseconds_t>((timeout_ms % 1000) * 1000)};
    if (fcntl(fd, F_SETFD, FD_CLOEXEC) ||
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout)) ||
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout)) ||
        connect(fd, reinterpret_cast<sockaddr *>(&address), sizeof(address))) {
        error = errno;
    } else {
        char permission = 0;
        ssize_t size;
        do { size = recv(fd, &permission, 1, 0); } while (size < 0 && errno == EINTR);
        if (size < 0) error = errno;
        else if (size != 1 || permission != 'G') error = EPROTO;
    }
    close(fd);
    return error;
}
