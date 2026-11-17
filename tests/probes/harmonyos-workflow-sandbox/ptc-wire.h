#ifndef MH_PTC_WIRE_H
#define MH_PTC_WIRE_H

#include <stddef.h>

struct PtcWire {
    char line[1600];
    size_t used;
    int ready;
    int binding;
    int logged;
    int completed;
    int cancelled;
};

int ptc_wire_receive(int socket, int cancel, struct PtcWire *wire);

#endif
