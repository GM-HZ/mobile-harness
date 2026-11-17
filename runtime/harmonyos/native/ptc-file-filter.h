#ifndef MH_PTC_FILE_FILTER_H
#define MH_PTC_FILE_FILTER_H

#include <sys/types.h>
#include <unistd.h>

enum { CONTROL = STDIN_FILENO };

int ptc_transfer_listener(int socket, int fd, int receiving);
int ptc_install_file_filter(int synchronize, int node);
int ptc_deny_io_uring(void);

#endif
