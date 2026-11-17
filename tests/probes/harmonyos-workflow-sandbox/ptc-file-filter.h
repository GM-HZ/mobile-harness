#ifndef MH_PTC_FILE_FILTER_H
#define MH_PTC_FILE_FILTER_H

#include <sys/types.h>
#include <unistd.h>

enum { CONTROL = STDIN_FILENO, ATTEMPTS = 4 };

struct WorkerReport {
    int error[ATTEMPTS];
    int read_correct;
    int write_correct;
    int direct_openat2_errno;
    int existing_thread_openat2_errno;
    int directory_verified;
    int typed_read;
};

int ptc_transfer_listener(int socket, int fd, int receiving);
int ptc_install_file_filter(int synchronize, int node);
int ptc_deny_io_uring(void);

#endif
