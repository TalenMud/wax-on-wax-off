#!/usr/bin/env bash
# Emergency stop for brain/arm/dodge.py on the GX10: a UDP stop message, then SIGINT to the
# process (both turn torque off). The arm power switch is still the real e-stop.
#   tools/arm_stop.sh [host]        # default host: the GX10 on the direct cable
HOST="${1:-10.42.0.109}"
python3 -c "import socket,sys; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); [s.sendto(b'{\"t\":\"stop\"}',(sys.argv[1],9310)) for _ in range(3)]" "$HOST"
ssh -o BatchMode=yes -o ConnectTimeout=3 "asus@$HOST" 'pkill -INT -f "brain.arm.dodge live" && echo "sent SIGINT"' || echo "no dodge process (or GX10 unreachable)"
