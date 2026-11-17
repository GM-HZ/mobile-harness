#include "ptc-wire.h"
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>

static int send_frame(int socket, const char *frame)
{
    size_t length = strlen(frame);
    return send(socket, frame, length, MSG_NOSIGNAL) == (ssize_t)length ? 0 : EIO;
}

static int receive_line(int socket, int cancel, struct PtcWire *wire)
{
    const char *line = wire->line;
    if (!wire->ready && !strcmp(line, "{\"m\":\"ready\",\"a\":[2],\"t\":\"q\"}")) {
        wire->ready = 1;
        if (cancel == 1) {
            return send_frame(socket, "{\"m\":\"run\",\"a\":[\"workspace\",{\"code\":\"return await fixture.double(21);\","
                              "\"programFormat\":\"function-body\",\"retainsState\":false,\"maxOutputBytes\":4096,"
                              "\"namespaces\":[{\"global\":\"fixture\",\"names\":[\"double\"]}]}],\"t\":\"q\",\"i\":\"run\"}\n");
        }
        if (cancel == 2) {
            return send_frame(socket, "{\"m\":\"run\",\"a\":[\"workspace\",{\"code\":\"await fixture.double(21); console.log('ptc-wire-spin'); while (true) {}\","
                              "\"programFormat\":\"function-body\",\"retainsState\":false,\"maxOutputBytes\":4096,"
                              "\"namespaces\":[{\"global\":\"fixture\",\"names\":[\"double\"]}]}],\"t\":\"q\",\"i\":\"run\"}\n");
        }
        return send_frame(socket, "{\"m\":\"run\",\"a\":[\"workspace\",{\"code\":\"const { readFile } = await import('node:fs/promises'); "
                          "const text = await readFile('read.txt', 'utf8'); if (text.length !== 12) throw new Error('bad fixture'); "
                          "console.log('ptc-wire-log'); return await fixture.double(21);\","
                          "\"programFormat\":\"function-body\",\"retainsState\":false,\"maxOutputBytes\":4096,"
                          "\"namespaces\":[{\"global\":\"fixture\",\"names\":[\"double\"]}]}],\"t\":\"q\",\"i\":\"run\"}\n");
    }
    if (wire->ready && !strncmp(line, "{\"m\":\"log\",", 11)) {
        if (!strstr(line, cancel == 2 ? "ptc-wire-spin" : "ptc-wire-log")) return EPROTO;
        wire->logged = 1;
        return 0;
    }
    const char invoke[] = "{\"m\":\"invoke\",\"a\":[\"fixture\",\"double\",[21]],\"t\":\"q\",\"i\":\"";
    if (wire->ready && !wire->binding && !strncmp(line, invoke, sizeof(invoke) - 1)) {
        const char *id = line + sizeof(invoke) - 1;
        size_t id_length = strspn(id, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-");
        if (id_length == 0 || id_length > 64 || strcmp(id + id_length, "\"}")) return EPROTO;
        wire->binding = 1;
        if (cancel == 1) return send_frame(socket, "{\"m\":\"revoke\",\"a\":[],\"t\":\"q\"}\n");
        char reply[128];
        snprintf(reply, sizeof(reply), "{\"t\":\"s\",\"i\":\"%.*s\",\"r\":[42]}\n", (int)id_length, id);
        return send_frame(socket, reply);
    }
    if (wire->binding && !cancel && !strcmp(line, "{\"t\":\"s\",\"i\":\"run\",\"r\":{\"value\":[42]}}")) {
        wire->completed = 1;
        return 0;
    }
    if (wire->binding && cancel == 1 && !strcmp(line, "{\"t\":\"s\",\"i\":\"run\",\"r\":{}}")) {
        wire->cancelled = 1;
        return 0;
    }
    return EPROTO;
}

int ptc_wire_receive(int socket, int cancel, struct PtcWire *wire)
{
    char bytes[512];
    ssize_t length = recv(socket, bytes, sizeof(bytes), MSG_DONTWAIT);
    if (length < 0) return errno == EAGAIN || errno == EINTR ? 0 : errno;
    if (length == 0) return EIO;
    for (ssize_t index = 0; index < length; ++index) {
        if (bytes[index] == '\n') {
            wire->line[wire->used] = '\0';
            int status = receive_line(socket, cancel, wire);
            if (status) return status;
            wire->used = 0;
        } else {
            if (wire->used >= sizeof(wire->line) - 1) return EMSGSIZE;
            wire->line[wire->used++] = bytes[index];
        }
    }
    return 0;
}
