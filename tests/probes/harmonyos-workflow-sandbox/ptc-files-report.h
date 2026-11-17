#ifndef MH_PTC_FILES_REPORT_H
#define MH_PTC_FILES_REPORT_H

enum { ATTEMPTS = 4 };

struct WorkerReport {
    int error[ATTEMPTS];
    int read_correct;
    int write_correct;
    int direct_openat2_errno;
    int existing_thread_openat2_errno;
    int directory_verified;
    int typed_read;
};

#endif
