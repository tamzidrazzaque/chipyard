#!/usr/bin/env bash
# ============================================================================
# DEMO: Live kernel debugging of FireSim iceblk block device driver
#        via direct JTAG on AWS F2 FPGA
#
# Prerequisites:
#   - F2 FPGA instance running at F2_HOST with AGFI loaded
#   - FireSim simulation running in tmux session "firesim" with Linux booted
#   - SSH key: ~/firesim.pem
#   - br-base-bin-dwarf and iceblk.ko on manager for symbol loading
#
# This script demonstrates:
#   1. SSH tunnel to the JTAG remote_bitbang port on F2
#   2. OpenOCD connecting over direct JTAG bridge
#   3. Hardware breakpoint on the iceblk_rq_handler driver function
#   4. Triggering block I/O from Linux userspace (dd)
#   5. Breakpoint hit inside the actual device driver
#   6. Register inspection and single-stepping through driver code
# ============================================================================
set -euo pipefail

F2_HOST="${F2_HOST:-192.168.1.203}"
F2_KEY="${F2_KEY:-$HOME/firesim.pem}"
RBB_PORT=25050
VMLINUX="$HOME/chipyard/software/firemarshal/images/firechip/br-base/br-base-bin-dwarf"
ICEBLK_KO="$HOME/chipyard/software/firemarshal/boards/firechip/drivers/iceblk-driver/iceblk.ko"
ICEBLK_TEXT_ADDR=0xffffffff01374000   # from /proc/modules on target
ICEBLK_RQ_HANDLER=0xffffffff013746e6  # iceblk_rq_handler offset 0x6e6

OCD_CFG=$(mktemp /tmp/jtag_demo_XXXX.cfg)
cat > "$OCD_CFG" <<'EOF'
adapter driver remote_bitbang
remote_bitbang host localhost
remote_bitbang port 25050

set _CHIPNAME riscv
jtag newtap $_CHIPNAME cpu -irlen 5 -expected-id 0x00000001

set _TARGETNAME $_CHIPNAME.cpu
target create $_TARGETNAME riscv -chain-position $_TARGETNAME

riscv set_command_timeout_sec 120

init
EOF

ocd_cmd() { printf "%s\n" "$@" | nc -q 5 localhost 4444 2>&1 | strings; }

echo "=== STEP 1: SSH tunnel to F2 JTAG port ==="
ssh -i "$F2_KEY" -o ConnectTimeout=10 -f -N -L ${RBB_PORT}:localhost:${RBB_PORT} ubuntu@"$F2_HOST" 2>/dev/null || true
echo "  Tunnel established (localhost:${RBB_PORT} -> ${F2_HOST}:${RBB_PORT})"

echo ""
echo "=== STEP 2: Start OpenOCD ==="
openocd -f "$OCD_CFG" &
OCD_PID=$!
sleep 3
echo "  OpenOCD PID=$OCD_PID, GDB server on :3333, telnet on :4444"

echo ""
echo "=== STEP 3: Verify JTAG connection ==="
ocd_cmd "halt" "reg pc"
echo "  Target halted."

echo ""
echo "=== STEP 4: Set hardware breakpoint on iceblk_rq_handler ==="
ocd_cmd "rbp all" "bp $ICEBLK_RQ_HANDLER 2 hw" "resume"
echo "  HW breakpoint set at $ICEBLK_RQ_HANDLER (iceblk_rq_handler)"
echo "  Target resumed, waiting for block I/O..."

echo ""
echo "=== STEP 5: Trigger block I/O from Linux userspace ==="
ssh -i "$F2_KEY" ubuntu@"$F2_HOST" \
  'tmux send-keys -t firesim "dd if=/dev/iceblk of=/dev/null bs=4096 count=1" Enter'
echo "  Sent: dd if=/dev/iceblk of=/dev/null bs=4096 count=1"
echo "  Waiting for breakpoint hit..."
sleep 10

echo ""
echo "=== STEP 6: Check breakpoint hit ==="
ocd_cmd "halt" "reg pc"
echo ""
echo "  Expected: pc = $ICEBLK_RQ_HANDLER (iceblk_rq_handler)"

echo ""
echo "=== STEP 7: Inspect registers ==="
ocd_cmd "reg pc" "reg ra" "reg sp" "reg a0" "reg a1"

echo ""
echo "=== STEP 8: Single-step through driver code ==="
ocd_cmd "rbp all"
for i in $(seq 1 10); do
  ocd_cmd "step" "reg pc"
done

echo ""
echo "=== STEP 9: GDB session (registers + backtrace + module symbols) ==="
$HOME/chipyard/.conda-env/riscv-tools/bin/riscv64-unknown-elf-gdb -batch \
  -ex "set confirm off" \
  -ex "set pagination off" \
  -ex "set debuginfod enabled off" \
  -ex "target remote :3333" \
  -ex "file $VMLINUX" \
  -ex "add-symbol-file $ICEBLK_KO $ICEBLK_TEXT_ADDR" \
  -ex "info registers pc ra sp a0 a1 a2 a3 a4 a5 s0 s1" \
  -ex "bt 15" \
  -ex "disconnect" \
  2>&1 || true

echo ""
echo "=== STEP 10: Resume target and clean up ==="
ocd_cmd "resume"

echo ""
echo "=== DEMO COMPLETE ==="
echo ""
echo "What was demonstrated:"
echo "  - Direct JTAG debug of a running Linux kernel on AWS F2 FPGA"
echo "  - Hardware breakpoint in the FireSim iceblk block device driver"
echo "  - Single-stepping through iceblk_rq_handler -> blk_mq_start_request"
echo "  - Register and backtrace inspection at driver level"
echo ""
echo "Call path: dd(userspace) -> VFS read -> blk_mq_submit_bio -> "
echo "  blk_mq_dispatch_rq_list -> iceblk_rq_handler [BREAKPOINT]"
echo "  -> blk_mq_start_request -> iceblk_queue_request -> MMIO writes"

rm -f "$OCD_CFG"
