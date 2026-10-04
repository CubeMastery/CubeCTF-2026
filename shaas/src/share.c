#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <pwd.h>

int main(int argc, char *argv[]) {
    if (argc != 4) {
        printf("Usage: share <username> <filename> <target_user>\n");
        return 1;
    }

    char *username = argv[1];
    char *filename = argv[2];
    char *target_user = argv[3];

    struct passwd *pw = getpwnam(username);
    if (pw == NULL) {
        printf("User not found\n");
        return 1;
    }

    char srcpath[512];
    sprintf(srcpath, "/chroot/%s/home/%s/%s", username, username, ilename);

    struct stat st;
    if (lstat(srcpath, &st) != 0) {
        printf("File not found\n");
        return 1;
    }

    if (st.st_uid != pw->pw_uid) {
        printf("File not owned by you\n");
        return 1;
    }

    printf("Are you sure you want to share this file with %s? This cannot be undone [y/N]\n", target_user);
    fflush(stdout);

    char response[16];
    if (fgets(response, sizeof(response), stdin) == NULL) {
        printf("Canceled\n");
        return 1;
    }
    if (response[0] != 'y' && response[0] != 'Y') {
        printf("Canceled\n");
        return 1;
    }

    char cmd[4096];
    snprintf(cmd, sizeof(cmd),
        "mkdir -p /chroot/%s/home/%s && cp %s /chroot/%s/home/%s/ && chown %s:%s /chroot/%s/home/%s/%s && rm %s",
        target_user, target_user,
        srcpath,
        target_user, target_user,
        target_user, target_user,
        target_user, target_user, filename,
        srcpath);
    system(cmd);

    printf("OK\n");
    return 0;
}
