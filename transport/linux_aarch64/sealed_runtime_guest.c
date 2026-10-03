/* Development-only single-request sealed-runtime guest. Not a release-qualified broker.
 * Inputs arrive only after the raw serial channel is ready. No host filesystem,
 * network, interactive shell, or guest process-inspection service is required.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/reboot.h>
#include <sys/mount.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <termios.h>
#include <unistd.h>

static int channel = -1;
static void shutdown_guest(void) {
    sync();
    reboot(RB_POWER_OFF);
    for (;;) pause();
}
static int transfer(int fd, void *buffer, size_t length, int writing) {
    unsigned char *p = buffer;
    while (length) {
        ssize_t n = writing ? write(fd, p, length) : read(fd, p, length);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += n;
        length -= (size_t)n;
    }
    return 0;
}
static void refuse(void) {
    if (channel >= 0) {
        char message[] = "JKRERR1\n";
        (void)transfer(channel, message, sizeof(message) - 1, 1);
        (void)tcdrain(channel);
    }
    shutdown_guest();
}
static uint64_t read_u64(void) {
    unsigned char b[8];
    if (transfer(channel, b, sizeof(b), 0)) refuse();
    uint64_t n = 0;
    for (size_t i = 0; i < sizeof(b); ++i) n = (n << 8) | b[i];
    return n;
}
static void write_u64(uint64_t n) {
    unsigned char b[8];
    for (size_t i = sizeof(b); i > 0; --i) { b[i - 1] = n & 255; n >>= 8; }
    if (transfer(channel, b, sizeof(b), 1)) shutdown_guest();
}
static void send_file(int fd, uint64_t length) {
    unsigned char buffer[8192];
    if (lseek(fd, 0, SEEK_SET) < 0) refuse();
    while (length) {
        size_t amount = length < sizeof(buffer) ? (size_t)length : sizeof(buffer);
        if (transfer(fd, buffer, amount, 0) || transfer(channel, buffer, amount, 1)) refuse();
        length -= amount;
    }
}
int main(void) {
    const struct rlimit no_core = {0, 0};
    if (getpid() != 1 || setrlimit(RLIMIT_CORE, &no_core)) return 1;
    umask(077);
    if (mkdir("/dev", 0700) && errno != EEXIST) return 1;
    if (mount("devtmpfs", "/dev", "devtmpfs", MS_NOSUID, "mode=0755")) return 1;
    if (mknod("/dev/ttyAMA0", S_IFCHR | 0600, makedev(204, 64)) && errno != EEXIST) return 1;
    if (mknod("/dev/null", S_IFCHR | 0600, makedev(1, 3)) && errno != EEXIST) return 1;
    if (mknod("/dev/urandom", S_IFCHR | 0444, makedev(1, 9)) && errno != EEXIST) return 1;
    int null_fd = open("/dev/null", O_RDWR);
    if (null_fd < 0) return 1;
    for (int fd = 0; fd < 3; ++fd) if (dup2(null_fd, fd) < 0) return 1;
    if (null_fd > 2) close(null_fd);
    channel = open("/dev/ttyAMA0", O_RDWR | O_NOCTTY | O_CLOEXEC);
    if (channel < 0) return 1;
    struct termios tty;
    if (tcgetattr(channel, &tty)) refuse();
    cfmakeraw(&tty);
    tty.c_iflag &= ~(IXOFF | IXANY);
    tty.c_cflag |= CLOCAL | CREAD;
    if (tcsetattr(channel, TCSANOW, &tty) || tcflush(channel, TCIFLUSH)) refuse();
    struct termios observed;
    if (tcgetattr(channel, &observed) ||
        (observed.c_lflag & (ECHO | ECHONL | ICANON | ISIG | IEXTEN)) ||
        (observed.c_iflag & (IGNBRK | BRKINT | PARMRK | ISTRIP | INLCR | IGNCR | ICRNL | IXON | IXOFF | IXANY)) ||
        (observed.c_oflag & OPOST)) refuse();
    if (mkdir("/sealed", 0755) && errno != EEXIST) refuse();
    if (mount("/dev/vda", "/sealed", "ext4", MS_RDONLY | MS_NOSUID | MS_NODEV, "")) refuse();
    if (mount("tmpfs", "/sealed/tmp", "tmpfs", MS_NOSUID | MS_NODEV | MS_NOEXEC, "mode=1777")) refuse();
    if (mount("tmpfs", "/sealed/dev", "tmpfs", MS_NOSUID | MS_NOEXEC, "mode=0755")) refuse();
    if (mount("proc", "/sealed/proc", "proc", MS_RDONLY | MS_NOSUID | MS_NODEV | MS_NOEXEC, "")) refuse();
    if (mknod("/sealed/dev/null", S_IFCHR | 0666, makedev(1, 3)) ||
        mknod("/sealed/dev/urandom", S_IFCHR | 0444, makedev(1, 9))) refuse();
    if (chmod("/sealed/dev/null", 0666) || chmod("/sealed/dev/urandom", 0444)) refuse();
    /* Refuse any enabled serial console before receiving request bytes. */
    int consoles = open("/sealed/proc/consoles", O_RDONLY | O_CLOEXEC);
    char console_data[4096];
    if (consoles < 0) refuse();
    ssize_t console_length = read(consoles, console_data, sizeof(console_data) - 1);
    if (console_length < 0 || console_length == sizeof(console_data) - 1) refuse();
    console_data[console_length] = 0;
    close(consoles);
    if (console_length && strncmp(console_data, "ttynull ", 8)) refuse();
    if (console_length && strchr(console_data, '\n') &&
        strchr(console_data, '\n')[1] != 0) refuse();
    if (mkdir("/capture", 0700) ||
        mount("tmpfs", "/capture", "tmpfs", MS_NOSUID | MS_NODEV | MS_NOEXEC,
              "mode=0700,size=1073741824")) refuse();
    char ready[] = "JKRRDY1\n";
    if (transfer(channel, ready, sizeof(ready) - 1, 1) || tcdrain(channel)) refuse();

    char magic[8];
    if (transfer(channel, magic, sizeof(magic), 0) || memcmp(magic, "JKRREQ1\n", sizeof(magic))) refuse();
    uint64_t request_length = read_u64();
    if (request_length == 0 || request_length > (1u << 30)) refuse();
    int request = open("/sealed/tmp/request", O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (request < 0) refuse();
    unsigned char buffer[8192];
    while (request_length) {
        size_t amount = request_length < sizeof(buffer) ? (size_t)request_length : sizeof(buffer);
        if (transfer(channel, buffer, amount, 0) || transfer(request, buffer, amount, 1)) refuse();
        request_length -= amount;
    }
    if (close(request)) refuse();
    int out = open("/capture/stdout", O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    int err = open("/capture/stderr", O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    int input = open("/sealed/tmp/request", O_RDONLY | O_CLOEXEC);
    if (out < 0 || err < 0 || input < 0) refuse();
    int execution_error[2];
    if (pipe2(execution_error, O_CLOEXEC)) refuse();
    pid_t child = fork();
    if (child < 0) refuse();
    if (!child) {
        close(execution_error[0]);
        char failure = 1;
        if (dup2(input, 0) < 0 || dup2(out, 1) < 0 || dup2(err, 2) < 0 ||
            chroot("/sealed") || chdir("/runtime") ||
            setgroups(0, NULL) || setgid(65534) || setuid(65534)) {
            (void)transfer(execution_error[1], &failure, 1, 1);
            _exit(125);
        }
        char *environment[] = {"LC_ALL=C", "LANG=C", "HOME=/tmp", "PATH=/usr/bin", NULL};
        char *arguments[] = {"/usr/bin/python3", "-I", "-S", "-B",
            "/runtime/isolated_entry.py", "plugin", "stdio", NULL};
        execve(arguments[0], arguments, environment);
        (void)transfer(execution_error[1], &failure, 1, 1);
        _exit(126);
    }
    close(execution_error[1]);
    char failure;
    ssize_t error_length;
    do { error_length = read(execution_error[0], &failure, 1); } while (error_length < 0 && errno == EINTR);
    close(execution_error[0]);
    int status;
    while (waitpid(child, &status, 0) < 0) if (errno != EINTR) refuse();
    if (error_length != 0) refuse();
    struct stat out_info, err_info;
    if (fstat(out, &out_info) || fstat(err, &err_info) || out_info.st_size < 0 || err_info.st_size < 0) refuse();
    if ((uint64_t)out_info.st_size + (uint64_t)err_info.st_size >= (1u << 30)) refuse();
    int code = WIFEXITED(status) ? WEXITSTATUS(status) : WIFSIGNALED(status) ? -WTERMSIG(status) : -255;
    char response[] = "JKRRES1\n";
    if (transfer(channel, response, sizeof(response) - 1, 1)) shutdown_guest();
    write_u64((uint64_t)(int64_t)code);
    write_u64((uint64_t)out_info.st_size);
    write_u64((uint64_t)err_info.st_size);
    send_file(out, (uint64_t)out_info.st_size);
    send_file(err, (uint64_t)err_info.st_size);
    (void)tcdrain(channel);
    char acknowledgement[8];
    if (transfer(channel, acknowledgement, sizeof(acknowledgement), 0) ||
        memcmp(acknowledgement, "JKRACK1\n", sizeof(acknowledgement))) refuse();
    char complete[] = "JKREND1\n";
    if (transfer(channel, complete, sizeof(complete) - 1, 1)) shutdown_guest();
    (void)tcdrain(channel);
    shutdown_guest();
    return 0;
}
