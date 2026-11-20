/* mh-exec-shim.c - transparent exec of unsigned ELF files (self builds only).
 *
 * LD_PRELOADed into the packaged PRoot guest shell. It interposes execve():
 *
 *  - ELF files whose file-backed executable mapping is allowed (signed HAP
 *    bindings such as /bin/bash, /bin/node, /usr/bin/git) go straight through;
 *  - unsigned ELF files (downloaded tools) are redirected to
 *    /usr/bin/python3 /usr/bin/mh-exec <path> <args...>, which loads the image
 *    into anonymous executable memory (HarmonyOS allows that) and runs it.
 *  - scripts and non-ELF files pass through unchanged.
 *
 * The shim is compiled freestanding (-nostdlib) with raw syscalls and no NEEDED
 * libraries, so it loads in any aarch64 musl guest regardless of libc build.
 */
typedef unsigned long u64;
typedef long s64;

#define AT_FDCWD (-100)
#define O_RDONLY 0
#define O_CLOEXEC 0x80000
#define PROT_READ 0x1
#define PROT_EXEC 0x4
#define MAP_PRIVATE 0x2
#define PAGE 4096UL
#define MAX_ARGS 128
#define MAX_ENVS 256

static inline s64 sc3(s64 n, s64 a, s64 b, s64 c)
{
	register s64 x0 asm("x0") = a;
	register s64 x1 asm("x1") = b;
	register s64 x2 asm("x2") = c;
	register s64 x8 asm("x8") = n;
	asm volatile("svc #0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x8) : "memory");
	return x0;
}

static inline s64 sc4(s64 n, s64 a, s64 b, s64 c, s64 d)
{
	register s64 x0 asm("x0") = a;
	register s64 x1 asm("x1") = b;
	register s64 x2 asm("x2") = c;
	register s64 x3 asm("x3") = d;
	register s64 x8 asm("x8") = n;
	asm volatile("svc #0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x8) : "memory");
	return x0;
}

static inline s64 sys_openat(const char *path)
{
	return sc4(56, AT_FDCWD, (s64) path, O_RDONLY | O_CLOEXEC, 0);
}

static inline s64 sys_read(s64 fd, void *buffer, u64 length)
{
	return sc3(63, fd, (s64) buffer, length);
}

static inline s64 sys_close(s64 fd)
{
	return sc3(57, fd, 0, 0);
}

static inline s64 sys_mmap(s64 addr, u64 length, s64 prot, s64 flags, s64 fd, s64 offset)
{
	register s64 x0 asm("x0") = addr;
	register s64 x1 asm("x1") = (s64) length;
	register s64 x2 asm("x2") = prot;
	register s64 x3 asm("x3") = flags;
	register s64 x4 asm("x4") = fd;
	register s64 x5 asm("x5") = offset;
	register s64 x8 asm("x8") = 222;
	asm volatile("svc #0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5), "r"(x8) : "memory");
	return x0;
}

static inline s64 sys_munmap(s64 addr, u64 length)
{
	return sc3(215, addr, (s64) length, 0);
}

static inline s64 sys_execve(const char *path, char *const argv[], char *const envp[])
{
	return sc3(221, (s64) path, (s64) argv, (s64) envp);
}

static u64 length_of(const char *text)
{
	u64 size = 0;
	while (text && text[size])
		size++;
	return size;
}

static void copy_text(char *destination, const char *source)
{
	while (*source)
		*destination++ = *source++;
	*destination = 0;
}

/* Returns 1 when the file can be mapped executable (signed binding), 0 when it
 * cannot (unsigned downloaded file), -1 for non-ELF/short files. */
static int elf_exec_mapping_state(const char *path)
{
	unsigned char magic[4];
	s64 fd = sys_openat(path);
	s64 mapping;
	if (fd < 0)
		return -1;
	if (sys_read(fd, magic, 4) != 4 ||
	    magic[0] != 0x7f || magic[1] != 'E' || magic[2] != 'L' || magic[3] != 'F') {
		sys_close(fd);
		return -1;
	}
	mapping = sys_mmap(0, PAGE, PROT_READ | PROT_EXEC, MAP_PRIVATE, fd, 0);
	sys_close(fd);
	if (mapping < 0)
		return 0;
	sys_munmap(mapping, PAGE);
	return 1;
}

static char redirect_argv0[1024];
static char redirect_env0[1024];
static char *redirect_argv[MAX_ARGS + 4];
static char *redirect_env[MAX_ENVS + 2];

int execve(const char *path, char *const argv[], char *const envp[])
{
	char *const *input;
	char *const *environment;
	int count;
	int state;

	if (!path)
		return (int) sys_execve(path, argv, envp);

	/* Skip the redirect when already running inside the loader chain. */
	for (environment = envp; environment && *environment; environment++) {
		const char *item = *environment;
		if (item[0] == 'M' && item[1] == 'H' && item[2] == '_' && item[3] == 'E' &&
		    item[4] == 'X' && item[5] == 'E' && item[6] == 'C' && item[7] == '_' &&
		    item[8] == 'R' && item[9] == 'E' && item[10] == 'D' && item[11] == 'I' &&
		    item[12] == 'R' && item[13] == 'E' && item[14] == 'C' && item[15] == 'T' &&
		    item[16] == '=' && item[17] == '1' && item[18] == 0)
			return (int) sys_execve(path, argv, envp);
	}

	state = elf_exec_mapping_state(path);
	if (state != 0)
		return (int) sys_execve(path, argv, envp);

	/* Unsigned ELF: hand it to the in-memory loader instead of failing. */
	redirect_argv[0] = "/usr/bin/python3";
	redirect_argv[1] = "/usr/bin/mh-exec";
	redirect_argv[2] = (char *) path;
	count = 0;
	if (argv && argv[0]) {
		const char *name = argv[0];
		u64 length;
		u64 index = 0;
		copy_text(redirect_argv0, "MH_ELF_ARGV0=");
		length = length_of(redirect_argv0);
		while (name[index] && index < sizeof(redirect_argv0) - length - 1) {
			redirect_argv0[length + index] = name[index];
			index++;
		}
		redirect_argv0[length + index] = 0;
	}
	count = 0;
	while (argv && argv[count + 1] && count < 120) {
		redirect_argv[3 + count] = argv[count + 1];
		count++;
	}
	redirect_argv[3 + count] = 0;

	count = 0;
	while (envp && envp[count] && count < MAX_ENVS - 1) {
		redirect_env[count] = envp[count];
		count++;
	}
	redirect_env[count++] = redirect_argv0;
	copy_text(redirect_env0, "MH_EXEC_REDIRECT=1");
	redirect_env[count++] = redirect_env0;
	redirect_env[count] = 0;

	sys_execve("/usr/bin/python3", redirect_argv, redirect_env);
	return -1;
}
