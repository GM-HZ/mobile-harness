#ifndef MH_PTC_SUPERVISOR_H
#define MH_PTC_SUPERVISOR_H

#include <sys/types.h>

#define MH_PTC_EXTRA_ROOTS 16

struct PtcLaunch {
    char root[1024];
    char cwd[1024];
    char extra_roots[MH_PTC_EXTRA_ROOTS][1024];
    int extra_count;
    int writable;
    int message_bytes;
    int heap_mb;
};

void harmony_ptc_supervise(const char *entry, int channel, pid_t parent, const struct PtcLaunch *launch);

#endif
