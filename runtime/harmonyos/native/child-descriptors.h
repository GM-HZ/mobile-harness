#ifndef MOBILE_HARNESS_CHILD_DESCRIPTORS_H
#define MOBILE_HARNESS_CHILD_DESCRIPTORS_H

#include <dirent.h>
#include <errno.h>
#include <limits.h>
#include <stdlib.h>
#include <unistd.h>

// Call in a forked child after assigning its IPC descriptors. HarmonyOS can
// terminate a HAP child on close_range, so enumerate the child's own fd table.
static inline int close_child_descriptors(int first, int keep)
{
    DIR *directory = opendir("/proc/self/fd");
    if (!directory) return errno;

    int error = 0;
    const int own = dirfd(directory);
    for (;;) {
        errno = 0;
        struct dirent *entry = readdir(directory);
        if (!entry) {
            error = errno;
            break;
        }
        char *end;
        long fd = strtol(entry->d_name, &end, 10);
        if (*end || fd < first || fd > INT_MAX || fd == own || fd == keep) continue;
        if (close((int)fd) < 0 && errno != EINTR && errno != EBADF) {
            error = errno;
            break;
        }
    }
    if (closedir(directory) < 0 && !error) error = errno;
    return error;
}

#endif
