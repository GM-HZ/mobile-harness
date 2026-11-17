#ifndef MOBILE_HARNESS_WORKFLOW_BROKER_H
#define MOBILE_HARNESS_WORKFLOW_BROKER_H

#include <stdint.h>
#include <sys/types.h>
#include "ptc-supervisor.h"

struct WorkflowChild {
    int fd;
    uint32_t id;
    pid_t pid;
};

int harmony_workflow_broker_start(const char *entry);
int harmony_workflow_spawn(struct WorkflowChild *child);
int harmony_office_spawn(struct WorkflowChild *child);
int harmony_ptc_spawn(const struct PtcLaunch *launch, struct WorkflowChild *child);
int harmony_workflow_stop(uint32_t id);
int harmony_workflow_status(uint32_t id, int *finished, int *wait_status);
void harmony_workflow_broker_close(void);

#endif
