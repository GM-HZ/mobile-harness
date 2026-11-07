"""Run through the embedded PRoot Bash bridge."""
import errno
import os
import sys

if len(sys.argv) == 1:
    original = os.open("/dev/null", os.O_RDONLY)
    os.dup2(original, 200, inheritable=False)
    os.dup2(original, 201, inheritable=True)
    os.close(original)
    os.execv(sys.executable, [sys.executable, __file__, "check"])

try:
    os.fstat(200)
except OSError as error:
    if error.errno != errno.EBADF:
        raise
else:
    raise AssertionError("FD_CLOEXEC descriptor survived exec")
os.fstat(201)
print("HARMONY_CLOEXEC_HIGH_FD_OK")
