#!/bin/zsh

set -u

PYTHON_CANDIDATES=(
  /opt/homebrew/bin/python3
  /usr/local/bin/python3
  /usr/bin/python3
)

plugin_root=${0:A:h:h}
target="$plugin_root/mcp/server.py"
if (( $# > 0 )); then
  if [[ "$1" != "provision" ]]; then
    print -u2 -r -- "jackal_mcp=refused reason=invalid-launcher-arguments"
    exit 64
  fi
  shift
  target="$plugin_root/scripts/provision_runtime.py"
fi

probe='import ctypes, os, platform, selectors, signal, socket, sys, tarfile, urllib.request
from pathlib import Path
assert sys.version_info >= (3, 10)
required_os = ("CLD_DUMPED", "CLD_EXITED", "CLD_KILLED", "O_CREAT", "O_DIRECTORY", "O_EXCL", "O_NOFOLLOW", "O_NONBLOCK", "O_RDONLY", "O_WRONLY", "P_PID", "WEXITED", "WNOHANG", "WNOWAIT", "access", "dup", "fchmod", "fstat", "fsync", "killpg", "lseek", "mkdir", "open", "read", "replace", "scandir", "set_blocking", "stat", "waitid", "write")
assert all(hasattr(os, name) for name in required_os)
assert hasattr(socket, "socketpair")
libc = ctypes.CDLL(None)
assert callable(getattr(libc, "renameatx_np", None))
platform.system(); platform.machine(); Path("/").is_absolute()
selector = selectors.DefaultSelector(); selector.close()
assert callable(signal.setitimer) and callable(signal.getitimer)
assert signal.ITIMER_REAL >= 0 and signal.SIGALRM > 0
assert callable(tarfile.open) and callable(urllib.request.urlopen)'

export PYTHONDONTWRITEBYTECODE=1
for python in "${PYTHON_CANDIDATES[@]}"; do
  if [[ -f "$python" && -x "$python" ]] && \
      "$python" -I -S -B -c "$probe" </dev/null >/dev/null 2>/dev/null; then
    exec "$python" -I -S -B "$target" "$@"
  fi
done

print -u2 -r -- "jackal_mcp=refused reason=no-compatible-python requirement='Python >=3.10 at /opt/homebrew/bin/python3' recovery='brew install python'"
exit 126
