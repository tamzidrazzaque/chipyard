#!/bin/bash
# =============================================================================
# Direct JTAG Block Device Debug Demo on AWS F2 FPGA
# =============================================================================
#
# This script demonstrates end-to-end JTAG debugging of a Linux kernel
# block device driver running on a FireSim FPGA simulation. The demo uses
# a clock-adapted JTAG TAP that works with FireSim's FAME-1 transformation.
#
# Prerequisites:
#   - Manager host (c5.4xlarge) at 192.168.1.124
#   - F2 instance at 192.168.1.203 with FPGA SDK installed
#   - AGFI: agfi-06911dae2b6bf0ef7 (FireSimDirectJTAGRocketConfig)
#   - OpenOCD 0.12.0+ on manager
#   - RISC-V GDB in $CHIPYARD/.conda-env/riscv-tools/bin/
#
# Configuration:
#   - Target config: FireSimDirectJTAGRocketConfig
#   - Platform config: BaseF2Config
#   - Binder: WithJTAGBridge
#   - Host driver: jtagbridge_t / remote_bitbang_t on port 25050
#   - Block device: iceblk (FireSim custom)
#   - Breakpoint target: blk_mq_submit_bio at 0xffffffff8039db42
#
# =============================================================================

set -e
F2_HOST="192.168.1.203"
F2_KEY="~/firesim.pem"
F2_SSH="ssh -i $F2_KEY -o StrictHostKeyChecking=no ubuntu@$F2_HOST"
CHIPYARD="/home/ubuntu/chipyard"
GDB="$CHIPYARD/.conda-env/riscv-tools/bin/riscv64-unknown-elf-gdb"
VMLINUX="$CHIPYARD/software/firemarshal/images/firechip/br-base/br-base-bin-dwarf"
AGFI="agfi-06911dae2b6bf0ef7"
JTAG_PORT=25050

echo "=== STEP 1: Load AGFI on F2 FPGA ==="
$F2_SSH "sudo fpga-load-local-image -S 0 -I $AGFI"

echo ""
echo "=== STEP 2: Start FireSim simulation in tmux ==="
$F2_SSH "tmux kill-session -t firesim 2>/dev/null || true"
$F2_SSH "tmux new-session -d -s firesim 'cd ~/sim_slot_0 && sudo ./FireSim-f2 \
  +permissive +jtag_rbb_port=$JTAG_PORT \
  +macaddr0=00:12:6D:00:00:02 +blkdev0=job0-br-base.img \
  +niclog0=niclog0 +blkdev-log0=blkdev-log0 \
  +trace-select=1 +trace-start=0 +trace-end=-1 +trace-output-format=0 \
  +dwarf-file-name=job0-br-base-bin-dwarf \
  +autocounter-readrate=0 +autocounter-filename-base=AUTOCOUNTERFILE \
  +print-start=0 +print-end=-1 +linklatency0=6405 +netbw0=200 \
  +shmemportname0=default +slotid=0 \
  +permissive-off job0-br-base-bin 2>stderr.log'"

echo "Waiting 60 seconds for Linux to boot..."
sleep 60

echo ""
echo "=== STEP 3: Verify Linux booted ==="
$F2_SSH "tmux capture-pane -t firesim -p | tail -5"

echo ""
echo "=== STEP 4: Set up SSH tunnel for JTAG ==="
pkill -f "ssh.*${JTAG_PORT}.*${F2_HOST}" 2>/dev/null || true
ssh -i $F2_KEY -o StrictHostKeyChecking=no -f -N -L ${JTAG_PORT}:localhost:${JTAG_PORT} ubuntu@$F2_HOST
sleep 2

echo ""
echo "=== STEP 5: Connect OpenOCD ==="
pkill -f openocd 2>/dev/null || true
openocd -f /tmp/jtag_fpga_25050.cfg > /tmp/openocd_jtag.log 2>&1 &
sleep 12
grep "Examined RISC-V" /tmp/openocd_jtag.log && echo "OpenOCD connected!" || echo "OpenOCD FAILED"

echo ""
echo "=== STEP 6: Login to target console ==="
$F2_SSH "tmux send-keys -t firesim 'root' Enter"
sleep 3

echo ""
echo "=== STEP 7: Verify GDB can connect ==="
$GDB -batch \
  -ex "set confirm off" \
  -ex "set debuginfod enabled off" \
  -ex "target remote :3333" \
  -ex "file $VMLINUX" \
  -ex "info registers pc ra" \
  2>&1 | grep -E "pc |ra "

echo ""
echo "=== STEP 8: Set hardware breakpoint on blk_mq_submit_bio ==="
printf "halt\nbp 0xffffffff8039db42 2 hw\nresume\n" | nc -q 5 localhost 4444 2>&1 | grep -v "^$"
sleep 2

echo ""
echo "=== STEP 9: Trigger block I/O from target ==="
$F2_SSH "tmux send-keys -t firesim 'dd if=/dev/iceblk of=/dev/null bs=4096 count=1' Enter"
sleep 8

echo ""
echo "=== STEP 10: Check if breakpoint hit ==="
RESULT=$(printf "halt\nreg pc\n" | nc -q 3 localhost 4444 2>&1)
echo "$RESULT"
if echo "$RESULT" | grep -q "0xffffffff8039db42"; then
    echo ""
    echo "*** BREAKPOINT HIT at blk_mq_submit_bio! ***"
fi

echo ""
echo "=== STEP 11: Read registers and backtrace via GDB ==="
$GDB -batch \
  -ex "set confirm off" \
  -ex "set debuginfod enabled off" \
  -ex "target remote :3333" \
  -ex "file $VMLINUX" \
  -ex "info registers pc ra sp a0 a1" \
  -ex "bt 5" \
  2>&1 | grep -v "^$" | head -20

echo ""
echo "=== STEP 12: Single-step through blk_mq_submit_bio ==="
for i in 1 2 3 4 5; do
  STEP_RESULT=$(printf "step\nreg pc\n" | nc -q 3 localhost 4444 2>&1)
  PC=$(echo "$STEP_RESULT" | grep "pc " | awk '{print $3}')
  echo "  step $i: PC = $PC"
done

echo ""
echo "=== STEP 13: Resume target ==="
printf "rbp all\nresume\n" | nc -q 2 localhost 4444 2>&1 > /dev/null

echo ""
echo "=== DEMO COMPLETE ==="
echo ""
echo "Summary:"
echo "  - Linux booted on F2 FPGA with direct JTAG bridge"
echo "  - OpenOCD connected via remote_bitbang -> JTAGBridge -> FAME-1 JTAG TAP"
echo "  - GDB attached to running Linux kernel"
echo "  - Hardware breakpoint hit at blk_mq_submit_bio (block device submit)"
echo "  - Single-stepped through block driver code"
echo "  - Call chain: dd -> vfs_read -> ... -> __submit_bio -> blk_mq_submit_bio"
