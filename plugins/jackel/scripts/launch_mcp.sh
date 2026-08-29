#!/bin/sh
# Portable launcher for the JACKAL MCP adapter.
#
# Behaviourally identical to launch_mcp.zsh: it never searches the caller PATH,
# probes a fixed list of absolute interpreters, and execs the first one that
# passes the full capability probe. Written in POSIX sh so the plugin runs on
# hosts without zsh.

set -u

# Fixed absolute candidates only. The caller PATH is never consulted.
PYTHON_CANDIDATES="/opt/homebrew/bin/python3
/usr/local/bin/python3
/usr/bin/python3"

script_path=$0
case $script_path in
  /*) ;;
  *) script_path=$PWD/$script_path ;;
esac
# Parameter expansion only: `dirname` is an external command and the caller
# PATH is deliberately untrusted, so resolving the plugin root must not depend
# on anything outside the shell itself. `cd` and `pwd` are builtins.
scripts_dir=${script_path%/*}
plugin_root=$(CDPATH= cd -- "$scripts_dir/.." && pwd -P) || exit 126

target="$plugin_root/mcp/server.py"
if [ "$#" -gt 0 ]; then
  if [ "$1" != "provision" ]; then
    printf '%s\n' "jackal_mcp=refused reason=invalid-launcher-arguments" >&2
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
atomic_rename = {"Darwin": "renameatx_np", "Linux": "renameat2"}.get(platform.system())
assert atomic_rename is not None
assert callable(getattr(libc, atomic_rename, None))
platform.system(); platform.machine(); Path("/").is_absolute()
selector = selectors.DefaultSelector(); selector.close()
assert callable(signal.setitimer) and callable(signal.getitimer)
assert signal.ITIMER_REAL >= 0 and signal.SIGALRM > 0
assert callable(tarfile.open) and callable(urllib.request.urlopen)'

PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE

IFS='
'
for python in $PYTHON_CANDIDATES; do
  if [ -f "$python" ] && [ -x "$python" ] && \
      "$python" -I -S -B -c "$probe" </dev/null >/dev/null 2>/dev/null; then
    exec "$python" -I -S -B "$target" "$@"
  fi
done

printf '%s\n' "jackal_mcp=refused reason=no-compatible-python requirement='Python >=3.10 with an atomic no-replace rename (Darwin renameatx_np / Linux renameat2) at one of the fixed candidate paths' recovery='macOS: brew install python | Linux: install a distribution python3 >=3.10 at /usr/bin/python3'" >&2
exit 126
