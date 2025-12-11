#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <command> [args...]\n", argv[0]);
        return 1;
    }

    struct timespec start_time;
    clock_gettime(CLOCK_MONOTONIC, &start_time);

    // clones the process, once with pid 0 (child) and once with pid > 0 (parent)
    pid_t pid = fork();
    if (pid == -1) {
        // in the unlikely event of process fork failure
        perror("fork");
        return 1;
    }

    if (pid == 0) {
        // executing passed command in the child process
        execvp(argv[1], &argv[1]);
        // we reach here only if execvp fails
        perror("execvp");
        return 1;
    } else {
        // waiting for child process to finish, prints time and exits with same status
        int status;
        waitpid(pid, &status, 0);
        struct timespec end_time;
        clock_gettime(CLOCK_MONOTONIC, &end_time);

        double elapsed = (end_time.tv_sec - start_time.tv_sec) + (end_time.tv_nsec - start_time.tv_nsec) / 1e9;
        fprintf(stderr, "Wall-clock time: %.3f sec\n", elapsed);

        if (WIFEXITED(status)) {
            return WEXITSTATUS(status);
        } else {
            return 1;
        }
    }
}
