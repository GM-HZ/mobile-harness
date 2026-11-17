#define _GNU_SOURCE
#include "ptc-file-filter.h"
#include <errno.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/syscall.h>

int ptc_transfer_listener(int channel, int fd, int receiving)
{
    union { struct cmsghdr align; char bytes[CMSG_SPACE(sizeof(fd))]; } control = {{0}};
    char marker_byte = 'F';
    struct iovec data = {.iov_base = &marker_byte, .iov_len = 1};
    struct msghdr message = {
        .msg_iov = &data, .msg_iovlen = 1,
        .msg_control = control.bytes, .msg_controllen = sizeof(control.bytes),
    };
    struct cmsghdr *header = CMSG_FIRSTHDR(&message);
    if (receiving) {
        if (recvmsg(channel, &message, MSG_CMSG_CLOEXEC) != 1 ||
            (message.msg_flags & MSG_CTRUNC) || marker_byte != 'F') return -1;
        header = CMSG_FIRSTHDR(&message);
        if (!header || header->cmsg_level != SOL_SOCKET || header->cmsg_type != SCM_RIGHTS ||
            header->cmsg_len != CMSG_LEN(sizeof(fd))) return -1;
        memcpy(&fd, CMSG_DATA(header), sizeof(fd));
        return fd;
    }
    header->cmsg_level = SOL_SOCKET;
    header->cmsg_type = SCM_RIGHTS;
    header->cmsg_len = CMSG_LEN(sizeof(fd));
    memcpy(CMSG_DATA(header), &fd, sizeof(fd));
    return sendmsg(channel, &message, MSG_NOSIGNAL) == 1 ? 0 : -1;
}

#define RETURN(value) BPF_STMT(BPF_RET | BPF_K, value)
#define ACTION(number, value) BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, number, 0, 1), RETURN(value)
#define ALLOW(number) ACTION(number, SECCOMP_RET_ALLOW)

int ptc_install_file_filter(int synchronize, int node)
{
    struct sock_filter broker_rules[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_AARCH64, 1, 0),
        RETURN(SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        ACTION(SYS_openat, SECCOMP_RET_USER_NOTIF),
        ALLOW(SYS_seccomp),
        ALLOW(SYS_sendmsg),
        ALLOW(SYS_read),
        ALLOW(SYS_write),
        ALLOW(SYS_close),
        ALLOW(SYS_exit),
        ALLOW(SYS_exit_group),
        ALLOW(SYS_rt_sigreturn),
    };
    struct sock_filter node_rules[] = {
        ALLOW(SYS_futex),
        ALLOW(SYS_clock_gettime),
        ALLOW(SYS_getpid),
        ALLOW(SYS_gettid),
        ALLOW(SYS_sched_yield),
        ALLOW(SYS_rt_sigprocmask),
        ALLOW(SYS_epoll_ctl),
        ALLOW(SYS_epoll_pwait),
#ifdef SYS_epoll_pwait2
        ALLOW(SYS_epoll_pwait2),
#endif
        ALLOW(SYS_fstat),
        ALLOW(SYS_lseek),
        ALLOW(SYS_readv),
        ALLOW(SYS_writev),
        ALLOW(SYS_getdents64),
        ALLOW(SYS_pread64),
        ALLOW(SYS_pwrite64),
        ALLOW(SYS_brk),
        ALLOW(SYS_munmap),
        ALLOW(SYS_madvise),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_mprotect, 0, 4),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[2])),
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, PROT_EXEC, 1, 0),
        RETURN(SECCOMP_RET_ALLOW),
        RETURN(SECCOMP_RET_ERRNO | EPERM),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_mmap, 0, 6),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[2])),
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, PROT_EXEC, 2, 0),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[3])),
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, MAP_ANONYMOUS, 1, 0),
        RETURN(SECCOMP_RET_ERRNO | EPERM),
        RETURN(SECCOMP_RET_ALLOW),
    };
    struct sock_filter instructions[sizeof(broker_rules) / sizeof(*broker_rules)
                                  + sizeof(node_rules) / sizeof(*node_rules) + 1];
    memcpy(instructions, broker_rules, sizeof(broker_rules));
    size_t count = sizeof(broker_rules) / sizeof(*broker_rules);
    if (node) {
        memcpy(instructions + count, node_rules, sizeof(node_rules));
        count += sizeof(node_rules) / sizeof(*node_rules);
    }
    instructions[count++] = (struct sock_filter)RETURN(SECCOMP_RET_ERRNO | EPERM);
    const struct sock_fprog broker_filter = {
        .len = count, .filter = instructions,
    };
    int listener = (int)syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER,
                                SECCOMP_FILTER_FLAG_NEW_LISTENER, &broker_filter);
    if (listener < 0) return errno;
    int sent = ptc_transfer_listener(CONTROL, listener, 0);
    close(listener);
    if (sent) return EIO;
    struct sock_filter startup_only[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        ACTION(SYS_sendmsg, SECCOMP_RET_ERRNO | EPERM),
        ACTION(SYS_seccomp, SECCOMP_RET_ERRNO | EPERM),
        RETURN(SECCOMP_RET_ALLOW),
    };
    const struct sock_fprog sealed = {
        .len = sizeof(startup_only) / sizeof(startup_only[0]), .filter = startup_only,
    };
    const unsigned flags = synchronize ? SECCOMP_FILTER_FLAG_TSYNC : 0;
    long status = syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, flags, &sealed);
    return status < 0 ? errno : status > 0 ? EBUSY : 0;

}

int ptc_deny_io_uring(void)
{
    struct sock_filter instructions[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        ACTION(SYS_io_uring_setup, SECCOMP_RET_ERRNO | ENOSYS),
        RETURN(SECCOMP_RET_ALLOW),
    };
    const struct sock_fprog filter = {
        .len = sizeof(instructions) / sizeof(instructions[0]), .filter = instructions,
    };
    return prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) ||
        syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, 0, &filter);
}
