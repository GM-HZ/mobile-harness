#!/usr/bin/python3
"""In-memory ELF runner shipped only in self-built HAPs (signed-exec bypass).

This tool lives at /usr/bin/mh-exec in the packaged PRoot guest when the build
was made with HARMONY_SELF_BUILD=1. It loads a downloaded static ELF image into
anonymous executable memory and runs it, bypassing HarmonyOS file code-signing
for exec. Store/distribution builds do not include it.

Usage inside the packaged PRoot guest:

    mh-exec ./downloaded-tool arg1 arg2 ...

It supports ET_EXEC and ET_DYN (static PIE) images: segments are mapped at their
fixed/relative addresses with MAP_FIXED anonymous memory, relocated by the guest
itself for static PIE (musl rcrt1), mprotected to their final permissions, and
entered from a forked child with a real argc/argv/envp/auxv stack so that
exit_group in the loaded program only ends the child.

The HarmonyOS app sandbox permits anonymous PROT_EXEC memory; executable file
mappings are limited to signed HAP files, which is why programs are loaded from
bytes instead of execve.
"""
import ctypes
import os
import struct
import sys

PROT_READ, PROT_WRITE, PROT_EXEC = 1, 2, 4
MAP_PRIVATE, MAP_FIXED, MAP_ANON = 2, 0x10, 0x20
PAGE = 0x1000
AT_NULL, AT_PHDR, AT_PHENT, AT_PHNUM = 0, 3, 4, 5
AT_PAGESZ, AT_BASE, AT_FLAGS, AT_ENTRY = 6, 7, 8, 9
AT_UID, AT_EUID, AT_GID, AT_EGID = 11, 12, 13, 14
AT_HWCAP, AT_CLKTCK, AT_SECURE, AT_RANDOM, AT_EXECFN = 16, 17, 23, 25, 31

libc = ctypes.CDLL(None, use_errno=True)
libc.mmap.restype = ctypes.c_void_p
libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]
libc.mprotect.restype = ctypes.c_int
libc.mprotect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]


def align_down(value):
    return value & ~(PAGE - 1)


def align_up(value):
    return (value + PAGE - 1) & ~(PAGE - 1)


def parse(data):
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise SystemExit("not a 64-bit little-endian ELF")
    e_type, e_machine = struct.unpack_from("<HH", data, 16)
    if e_machine != 183:
        raise SystemExit("not an aarch64 ELF")
    e_entry = struct.unpack_from("<Q", data, 24)[0]
    e_phoff = struct.unpack_from("<Q", data, 32)[0]
    phentsize, phnum = struct.unpack_from("<HH", data, 54)
    segments = []
    interp = None
    for index in range(phnum):
        offset = e_phoff + index * phentsize
        p_type, p_flags = struct.unpack_from("<II", data, offset)
        p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from("<QQQQQQ", data, offset + 8)
        if p_type == 1 and p_memsz:
            segments.append({"flags": p_flags, "offset": p_offset, "vaddr": p_vaddr,
                             "filesz": p_filesz, "memsz": p_memsz, "align": p_align})
        elif p_type == 3 and p_filesz:
            interp = data[p_offset:p_offset + p_filesz].split(b"\0")[0].decode("utf8", "replace")
    return e_type, e_entry, e_phoff, segments, phnum, interp


def map_segments(data, e_type, segments, base=None):
    if base is None:
        base = 0 if e_type == 2 else 0x1000000000
    mapped = []
    for segment in segments:
        start = align_down(segment["vaddr"])
        delta = segment["vaddr"] - start
        size = align_up(segment["memsz"] + delta)
        address = base + start
        pointer = libc.mmap(address, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON | MAP_FIXED, -1, 0)
        if pointer == -1:
            first = ctypes.get_errno()
            pointer = libc.mmap(address, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0)
            second = ctypes.get_errno()
            if pointer == -1:
                raise SystemExit("mmap failed vaddr=0x%x size=0x%x fixed_errno=%d %s hint_errno=%d %s" %
                                 (segment["vaddr"], size, first, os.strerror(first), second, os.strerror(second)))
            if pointer != address:
                raise SystemExit("mmap hint returned 0x%x instead of 0x%x (fixed_errno=%d %s)" %
                                 (pointer, address, first, os.strerror(first)))
        chunk = data[segment["offset"]:segment["offset"] + segment["filesz"]]
        if chunk:
            ctypes.memmove(pointer + delta, chunk, len(chunk))
        prot = (PROT_READ if segment["flags"] & 4 else 0) | (PROT_WRITE if segment["flags"] & 2 else 0) | \
               (PROT_EXEC if segment["flags"] & 1 else 0)
        if libc.mprotect(pointer, size, prot) != 0:
            raise SystemExit("mprotect failed vaddr=0x%x" % segment["vaddr"])
        mapped.append((pointer, size, prot))
    return base, mapped


def phdr_address(e_phoff, segments):
    for segment in segments:
        if segment["offset"] <= e_phoff < segment["offset"] + segment["filesz"]:
            return segment["vaddr"] + (e_phoff - segment["offset"])
    raise SystemExit("program headers are not inside a loadable segment")


def build_stack(argv, entry, phdr, phnum, phentsize, at_base=0):
    size = 2 * 1024 * 1024
    pointer = libc.mmap(None, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0)
    if pointer == -1:
        raise SystemExit("stack mmap failed")
    top = pointer + size

    def push(payload):
        nonlocal top
        top -= len(payload) + 1
        ctypes.memmove(top, payload + b"\0", len(payload) + 1)
        return top

    argv_ptrs = [push(item.encode()) for item in argv]
    environment = [name + b"=" + value for name, value in sorted(os.environb.items()) if b"=" not in name]
    env_ptrs = [push(item) for item in environment]
    random_bytes = os.urandom(16)
    random_ptr = push(random_bytes)
    top &= ~0xF
    auxv = [(AT_PHDR, phdr), (AT_PHENT, phentsize), (AT_PHNUM, phnum), (AT_PAGESZ, PAGE),
            (AT_BASE, at_base), (AT_FLAGS, 0), (AT_ENTRY, entry), (AT_UID, os.getuid()),
            (AT_EUID, os.geteuid()), (AT_GID, os.getgid()), (AT_EGID, os.getegid()),
            (AT_HWCAP, 0), (AT_CLKTCK, 100), (AT_SECURE, 0), (AT_RANDOM, random_ptr),
            (AT_EXECFN, argv_ptrs[0]), (AT_NULL, 0)]
    top -= 16 * len(auxv)
    auxv_address = top
    for index, (kind, value) in enumerate(auxv):
        ctypes.memmove(auxv_address + index * 16, struct.pack("<QQ", kind, value), 16)
    top -= 8 * (len(env_ptrs) + 1)
    for index, value in enumerate(env_ptrs):
        ctypes.memmove(top + index * 8, struct.pack("<Q", value), 8)
    ctypes.memmove(top + len(env_ptrs) * 8, struct.pack("<Q", 0), 8)
    top -= 8 * (len(argv_ptrs) + 1)
    for index, value in enumerate(argv_ptrs):
        ctypes.memmove(top + index * 8, struct.pack("<Q", value), 8)
    ctypes.memmove(top + len(argv_ptrs) * 8, struct.pack("<Q", 0), 8)
    top -= 8
    ctypes.memmove(top, struct.pack("<Q", len(argv_ptrs)), 8)
    return top


def trampoline():
    page = libc.mmap(None, PAGE, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_PRIVATE | MAP_ANON, -1, 0)
    if page == -1:
        raise SystemExit("trampoline mmap failed")
    code = bytes.fromhex("3f00009100001fd6")  # mov sp, x1 ; br x0
    ctypes.memmove(page, code, len(code))
    return page


def load_interpreter(path):
    """Map the dynamic interpreter (musl ld, a signed HAP binding) into anonymous memory."""
    override = os.environ.get("MH_ELF_INTERP")
    interp_path = override or path
    data = open(interp_path, "rb").read()
    i_type, i_entry, i_phoff, i_segments, i_phnum, _ = parse(data)
    base, _mapped = map_segments(data, i_type, i_segments, base=0x2000000000)
    if base != 0x2000000000:
        raise SystemExit("interpreter base mismatch")
    return i_entry + base, base


def main():
    argv = sys.argv[1:]
    if not argv:
        raise SystemExit("usage: mh-exec <elf> [args...]")
    path = argv[0]
    data = open(path, "rb").read()
    e_type, e_entry, e_phoff, segments, phnum, interp = parse(data)
    if os.environ.get("MH_ELF_DRY_RUN"):
        for segment in segments:
            print("SEGMENT vaddr=0x%x offset=0x%x filesz=%d memsz=%d align=0x%x flags=%d" %
                  (segment["vaddr"], segment["offset"], segment["filesz"], segment["memsz"],
                   segment["align"], segment["flags"]))
        print("ENTRY 0x%x TYPE %d PHDR 0x%x INTERP %s" %
              (e_entry, e_type, phdr_address(e_phoff, segments), interp or "-"))
        print("ARGV", argv)
        return 0
    loaded_argv = [os.environ.get("MH_ELF_ARGV0") or argv[0]] + argv[1:]
    pid = os.fork()
    if pid == 0:
        # Map and start inside the child only: MAP_FIXED segments (0x400000 for a
        # non-PIE static binary) would otherwise clobber the parent interpreter.
        try:
            base, mapped = map_segments(data, e_type, segments)
            main_phdr = phdr_address(e_phoff, segments) + base
            main_entry = e_entry + base
            if interp:
                start, at_base = load_interpreter(interp)
                print("LOADED segments=%d base=0x%x entry=0x%x interp=%s interp_base=0x%x" %
                      (len(mapped), base, e_entry, interp, at_base))
            else:
                start, at_base = main_entry, 0
                print("LOADED segments=%d base=0x%x entry=0x%x" % (len(mapped), base, e_entry))
            stack = build_stack(loaded_argv, main_entry, main_phdr, phnum, 56, at_base)
            page = trampoline()
            target = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)(page)
            target(start, stack)
        finally:
            # A launched program exits the child itself. Reaching here means it could not run.
            os._exit(126)
    _, status = os.waitpid(pid, 0)
    if os.WIFEXITED(status):
        print("CHILD_EXIT %d" % os.WEXITSTATUS(status))
        return os.WEXITSTATUS(status)
    print("CHILD_SIGNAL %d" % os.WTERMSIG(status))
    return 1


if __name__ == "__main__":
    sys.exit(main())
