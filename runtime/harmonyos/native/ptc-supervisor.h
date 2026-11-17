#ifndef MH_PTC_SUPERVISOR_H
#define MH_PTC_SUPERVISOR_H

#include <sys/types.h>

struct PtcLaunch {
    char root[1024];
    char cwd[1024];
    int writable;
    int message_bytes;
    int heap_mb;
};

void harmony_ptc_supervise(const char *entry, int channel, pid_t parent, const struct PtcLaunch *launch);

#endif
