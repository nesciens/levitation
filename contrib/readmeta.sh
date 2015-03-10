#!/bin/sh

hexdump -e '"%08_ax: " 7/4 " %04x " 1/1 " %01x" "\n"' "$@" | less
