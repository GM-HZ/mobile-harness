"""In-memory ELF loader prototype used by tests/smoke/mate60-proot-exec.py.
It embeds a tiny aarch64 ET_EXEC image (write syscall + ret), writes it to ./probe.elf,
maps its PT_LOAD segment at its fixed vaddr with anonymous memory, mprotects RX and jumps.
It proves the "anonymous executable memory + userspace ELF loading" route works in the
HarmonyOS app sandbox without file-signature-backed exec."""
#!/usr/bin/env python3
"""In-memory ELF loader prototype: reads an ELF, maps segments anonymously, executes it."""
import base64, ctypes, os, struct, sys
ELF = base64.b64decode("f0VMRgIBAQAAAAAAAAAAAAIAtwABAAAAAAFAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAEAAOAABAAAAAAAAAAEAAAAFAAAAAAAAAAAAAAAAAEAAAAAAAAAAQAAAAAAAIAIAAAAAAAAgAgAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAgNIBCAAQIgKA0ggIgNIBAADUwANf1gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABJTi1NRU1PUlktRUxGLU9LCgAAAAAAAAAAAAAAAAAAAA==")
libc = ctypes.CDLL(None, use_errno=True)
libc.mmap.restype = ctypes.c_void_p
libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]
libc.mprotect.restype = ctypes.c_int
libc.mprotect.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
PROT_READ, PROT_WRITE, PROT_EXEC = 1, 2, 4
MAP_PRIVATE, MAP_FIXED, MAP_ANON, MAP_FIXED_NOREPLACE = 2, 0x10, 0x20, 0x100000

def align(value):
    return (value + 0xFFF) & ~0xFFF

def main():
    if len(sys.argv) > 1:
        data = open(sys.argv[1], 'rb').read()
    else:
        with open('./probe.elf', 'wb') as handle:
            handle.write(ELF)
        data = open('./probe.elf', 'rb').read()
        print('ELF_WRITTEN_TO_DISK', len(data))
    if data[:4] != b'\x7fELF':
        print('NOT_ELF'); return 1
    phoff = struct.unpack_from('<Q', data, 32)[0]
    entry = struct.unpack_from('<Q', data, 24)[0]
    phentsize, phnum = struct.unpack_from('<HH', data, 54)
    print('ELF_HEADER_OK entry=0x%x phnum=%d' % (entry, phnum))
    for index in range(phnum):
        offset = phoff + index * phentsize
        p_type, p_flags = struct.unpack_from('<II', data, offset)
        p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_align = struct.unpack_from('<QQQQQQ', data, offset + 8)
        if p_type != 1 or p_memsz == 0:
            continue
        size = align(p_memsz)
        address = libc.mmap(p_vaddr, size, PROT_READ | PROT_WRITE,
                            MAP_PRIVATE | MAP_ANON | MAP_FIXED, -1, 0)
        if address == -1:
            print('MMAP_FAILED', ctypes.get_errno(), os.strerror(ctypes.get_errno())); return 1
        if address != p_vaddr:
            print('MMAP_ADDRESS_MISMATCH', hex(address), hex(p_vaddr)); return 1
        chunk = data[p_offset:p_offset + p_filesz]
        ctypes.memmove(p_vaddr, chunk, len(chunk))
        prot = (PROT_READ if p_flags & 4 else 0) | (PROT_WRITE if p_flags & 2 else 0) | (PROT_EXEC if p_flags & 1 else 0)
        if libc.mprotect(p_vaddr, size, prot) != 0:
            print('MPROTECT_FAILED', ctypes.get_errno()); return 1
        print('SEGMENT_MAPPED', hex(p_vaddr), 'size', size, 'prot', prot)
    fn = ctypes.CFUNCTYPE(ctypes.c_int)(entry)
    print('ENTER_ENTRY 0x%x' % entry)
    fn()
    print('RETURNED_FROM_ELF (no exit_group called)')
    return 0

sys.exit(main())
