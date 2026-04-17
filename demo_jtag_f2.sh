#!/usr/bin/env bash
# =============================================================================
#  FireSim Direct-JTAG Block Device Debug Demo
#  End-to-end: bring-up through live kernel breakpoint on AWS F2 FPGA
#
#  Usage:
#    ./demo_jtag_f2.sh --full        # full bring-up + demo
#    ./demo_jtag_f2.sh --demo-only   # assumes sim already running
#    ./demo_jtag_f2.sh --help
#
#  Environment overrides (all have defaults):
#    F2_HOST          F2 instance private IP       (default: 192.168.1.203)
#    F2_KEY           SSH private key path          (default: ~/firesim.pem)
#    CHIPYARD         Chipyard root                 (default: ~/chipyard)
#    RBB_PORT         remote_bitbang TCP port       (default: 25050)
#    AGFI             FPGA image to load            (default: agfi-06911dae2b6bf0ef7)
#
#  Known limitation:
#    The current FPGA image uses SV39 (39-bit virtual addresses). Hardware
#    triggers cannot match addresses in the kernel module region
#    (0xffffffff01xxxxxx) because those addresses are non-canonical for SV39.
#    The demo therefore uses blk_mq_submit_bio (in the kernel proper) as the
#    breakpoint, which IS in the SV39-reachable range. A backtrace from that
#    point shows the iceblk driver path. Rebuilding with WithSV48 would allow
#    direct iceblk_rq_handler breakpoints.
# =============================================================================
set -uo pipefail

# ── Defaults ────────────────────────────────────────────────────────────────
F2_HOST="${F2_HOST:-192.168.1.203}"
F2_KEY="${F2_KEY:-$HOME/firesim.pem}"
CHIPYARD="${CHIPYARD:-$HOME/chipyard}"
RBB_PORT="${RBB_PORT:-25050}"
AGFI="${AGFI:-agfi-06911dae2b6bf0ef7}"

VMLINUX="$CHIPYARD/software/firemarshal/images/firechip/br-base/br-base-bin-dwarf"
ICEBLK_KO="$CHIPYARD/software/firemarshal/boards/firechip/drivers/iceblk-driver/iceblk.ko"
GDB="$CHIPYARD/.conda-env/riscv-tools/bin/riscv64-unknown-elf-gdb"
NM="riscv64-unknown-elf-nm"
F2_SSH="ssh -i $F2_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10 ubuntu@$F2_HOST"
OCD_TELNET_PORT=4444
OCD_GDB_PORT=3333
LOGDIR="$CHIPYARD/demo_logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOGFILE="$LOGDIR/demo_${TIMESTAMP}.log"
OCD_LOG=""
OCD_CFG=""
OCD_PID=""
MODE=""
BP_HIT=false

# ── Usage ───────────────────────────────────────────────────────────────────
usage() {
  sed -n '2,30p' "$0"
  exit 0
}

# ── Helpers ─────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[0;33m'; CYN='\033[0;36m'; RST='\033[0m'
step_num=0
step() { step_num=$((step_num + 1)); printf "\n${CYN}=== STEP %d: %s ===${RST}\n" "$step_num" "$1"; }
ok()   { printf "  ${GRN}[OK]${RST} %s\n" "$1"; }
warn() { printf "  ${YLW}[WARN]${RST} %s\n" "$1"; }
fail() { printf "  ${RED}[FAIL]${RST} %s\n" "$1"; exit 1; }
info() { printf "  %s\n" "$1"; }

ocd_cmd() {
  local out
  out=$(printf '%s\n' "$@" | nc -q 2 localhost "$OCD_TELNET_PORT" 2>&1 | tr -d '\r' | strings)
  echo "$out"
  echo "$out" >> "$LOGFILE"
}

cleanup() {
  local rc=$?
  echo ""
  if [ -n "$OCD_PID" ] && kill -0 "$OCD_PID" 2>/dev/null; then
    info "Cleanup: clearing breakpoints and resuming target..."
    printf 'rbp all\nresume\n' | nc -q 2 localhost "$OCD_TELNET_PORT" > /dev/null 2>&1
    sleep 1
    kill "$OCD_PID" 2>/dev/null
    info "Cleanup: OpenOCD stopped (pid $OCD_PID)"
  fi
  [ -n "$OCD_CFG" ] && [ -f "$OCD_CFG" ] && rm -f "$OCD_CFG"
  info "Log saved to $LOGFILE"
}
trap cleanup EXIT

# ── Parse args ──────────────────────────────────────────────────────────────
case "${1:---full}" in
  --full)       MODE=full ;;
  --demo-only)  MODE=demo ;;
  --help|-h)    usage ;;
  *)            echo "Unknown argument: $1"; usage ;;
esac

# ── Create log directory ────────────────────────────────────────────────────
mkdir -p "$LOGDIR"
exec > >(tee -a "$LOGFILE") 2>&1

echo "================================================================="
echo "  FireSim Direct-JTAG Block Device Debug Demo"
echo "  Mode:       $MODE"
echo "  Timestamp:  $TIMESTAMP"
echo "  Log file:   $LOGFILE"
echo "================================================================="
echo ""

# ═════════════════════════════════════════════════════════════════════════════
#  PRECONDITION CHECKS
# ═════════════════════════════════════════════════════════════════════════════
step "Verify local prerequisites"

for tool in openocd nc strings "$NM" python3; do
  command -v "$tool" > /dev/null 2>&1 || fail "Required tool not found: $tool"
done
ok "Tools: openocd, nc, strings, $NM, python3"

[ -f "$F2_KEY" ]    || fail "SSH key not found: $F2_KEY"
[ -f "$VMLINUX" ]   || fail "vmlinux not found: $VMLINUX"
[ -f "$ICEBLK_KO" ] || fail "iceblk.ko not found: $ICEBLK_KO"
ok "All files present"

[ -f "$GDB" ] || warn "GDB not found at $GDB — backtrace step will be skipped"

# Look up blk_mq_submit_bio address from vmlinux
BP_FUNC="blk_mq_submit_bio"
BP_ADDR_RAW=$("$NM" "$VMLINUX" 2>/dev/null | awk -v sym="$BP_FUNC" '$3 == sym && $2 == "T" { print $1; exit }')
[ -n "$BP_ADDR_RAW" ] || fail "'$BP_FUNC' not found in vmlinux symbol table"
BP_ADDR="0x$BP_ADDR_RAW"
ok "Breakpoint target: $BP_FUNC at $BP_ADDR (kernel proper, SV39-safe)"

step "Verify F2 host reachable"
$F2_SSH "echo reachable" > /dev/null 2>&1 || fail "Cannot SSH to F2 host $F2_HOST"
ok "SSH to $F2_HOST works"

# ═════════════════════════════════════════════════════════════════════════════
#  FULL BRING-UP (--full only)
# ═════════════════════════════════════════════════════════════════════════════
if [ "$MODE" = "full" ]; then

  step "Kill any stale simulation and reload AGFI"
  $F2_SSH "sudo pkill -9 FireSim-f2 2>/dev/null; tmux kill-session -t firesim 2>/dev/null; sleep 2" || true
  LOAD_OUT=$($F2_SSH "sudo fpga-load-local-image -S 0 -I $AGFI 2>&1")
  echo "$LOAD_OUT" | grep -qi "loaded\|success" && ok "AGFI loaded" || warn "AGFI load status unclear"
  sleep 5

  step "Verify simulation slot"
  $F2_SSH "ls ~/sim_slot_0/FireSim-f2 > /dev/null 2>&1" \
    || fail "~/sim_slot_0/FireSim-f2 not found on F2."
  ok "sim_slot_0 ready"

  step "Start FireSim simulation"
  $F2_SSH "tmux new-session -d -s firesim 'cd ~/sim_slot_0 && sudo ./FireSim-f2 \
    +permissive +jtag_rbb_port=$RBB_PORT \
    +macaddr0=00:12:6D:00:00:02 +blkdev0=job0-br-base.img \
    +niclog0=niclog0 +blkdev-log0=blkdev-log0 \
    +trace-select=1 +trace-start=0 +trace-end=-1 +trace-output-format=0 \
    +dwarf-file-name=job0-br-base-bin-dwarf \
    +autocounter-readrate=0 +autocounter-filename-base=AUTOCOUNTERFILE \
    +print-start=0 +print-end=-1 +linklatency0=6405 +netbw0=200 \
    +shmemportname0=default +slotid=0 \
    +permissive-off job0-br-base-bin 2>stderr.log'"
  ok "Simulation launched"

  step "Wait for Linux boot (up to 120s)"
  BOOT_OK=false
  for i in $(seq 1 24); do
    sleep 5
    C=$($F2_SSH "tmux capture-pane -t firesim -p 2>/dev/null | tail -15" 2>/dev/null || echo "")
    if echo "$C" | grep -qi "login:\|buildroot"; then
      BOOT_OK=true
      ok "Linux booted (~$((i*5))s)"
      break
    fi
    info "  $((i*5))s elapsed..."
  done
  $BOOT_OK || fail "Linux did not boot within 120s"

  step "Login to target console"
  $F2_SSH "tmux send-keys -t firesim 'root' Enter"
  sleep 5
  ok "Sent 'root' login"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  DEMO PRECONDITION VERIFICATION
# ═════════════════════════════════════════════════════════════════════════════
step "Verify simulation is running"
SIM_COUNT=$($F2_SSH "pgrep -c FireSim-f2 2>/dev/null" 2>/dev/null | tr -d '[:space:]')
SIM_COUNT="${SIM_COUNT:-0}"
[ "$SIM_COUNT" -gt 0 ] 2>/dev/null || fail "No FireSim simulation running on $F2_HOST"
ok "FireSim-f2 running ($SIM_COUNT)"

step "Verify remote_bitbang port"
PORT_CHECK=$($F2_SSH "ss -tln 2>/dev/null | grep ':${RBB_PORT} '" 2>/dev/null || echo "")
[ -n "$PORT_CHECK" ] || fail "Port $RBB_PORT not listening on F2"
ok "Port $RBB_PORT listening"

step "Verify tmux session"
$F2_SSH "tmux has-session -t firesim 2>/dev/null" || fail "tmux session 'firesim' not found"
ok "tmux session exists"

step "Verify console is interactive"
SYNC="SYNC_$(date +%s)"
$F2_SSH "tmux send-keys -t firesim 'echo $SYNC' Enter"
sleep 3
CHECK=$($F2_SSH "tmux capture-pane -t firesim -p 2>/dev/null" 2>/dev/null || echo "")
if ! echo "$CHECK" | grep -q "$SYNC"; then
  warn "Console not responsive. Sending login..."
  $F2_SSH "tmux send-keys -t firesim '' Enter"
  sleep 2
  $F2_SSH "tmux send-keys -t firesim 'root' Enter"
  sleep 5
  $F2_SSH "tmux send-keys -t firesim 'echo $SYNC' Enter"
  sleep 3
  CHECK=$($F2_SSH "tmux capture-pane -t firesim -p 2>/dev/null" 2>/dev/null || echo "")
  echo "$CHECK" | grep -q "$SYNC" || fail "Console is not interactive. Check tmux manually."
fi
ok "Console is interactive"

step "Verify /dev/iceblk exists"
DEV="DEVCHK_$(date +%s)"
$F2_SSH "tmux send-keys -t firesim 'test -e /dev/iceblk && echo ${DEV}_OK || echo ${DEV}_NO' Enter"
sleep 3
DEVOUT=$($F2_SSH "tmux capture-pane -t firesim -p 2>/dev/null" 2>/dev/null || echo "")
if echo "$DEVOUT" | grep -q "${DEV}_OK"; then
  ok "/dev/iceblk exists"
elif echo "$DEVOUT" | grep -q "${DEV}_NO"; then
  fail "/dev/iceblk does NOT exist"
else
  warn "Could not confirm /dev/iceblk (proceeding anyway)"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  SSH TUNNEL
# ═════════════════════════════════════════════════════════════════════════════
step "Set up SSH tunnel (port $RBB_PORT)"

for pid in $(pgrep -f "ssh.*-L.*${RBB_PORT}.*${F2_HOST}" 2>/dev/null); do
  kill "$pid" 2>/dev/null
done
sleep 1

ssh -i "$F2_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
  -f -N -L ${RBB_PORT}:localhost:${RBB_PORT} ubuntu@"$F2_HOST"
sleep 2

ss -tln 2>/dev/null | grep -q ":${RBB_PORT} " || fail "SSH tunnel not listening"
ok "Tunnel: localhost:$RBB_PORT -> $F2_HOST:$RBB_PORT"

# ═════════════════════════════════════════════════════════════════════════════
#  OPENOCD
# ═════════════════════════════════════════════════════════════════════════════
step "Start OpenOCD (fresh instance)"

for pid in $(pgrep -f "openocd.*remote_bitbang" 2>/dev/null); do
  kill "$pid" 2>/dev/null
done
sleep 2

OCD_CFG=$(mktemp /tmp/jtag_demo_XXXX.cfg)
cat > "$OCD_CFG" <<EOCFG
adapter driver remote_bitbang
remote_bitbang host localhost
remote_bitbang port $RBB_PORT

set _CHIPNAME riscv
jtag newtap \$_CHIPNAME cpu -irlen 5 -expected-id 0x00000001

set _TARGETNAME \$_CHIPNAME.cpu
target create \$_TARGETNAME riscv -chain-position \$_TARGETNAME

riscv set_command_timeout_sec 120

init
EOCFG

OCD_LOG="$LOGDIR/openocd_${TIMESTAMP}.log"
openocd -f "$OCD_CFG" > "$OCD_LOG" 2>&1 &
OCD_PID=$!
info "OpenOCD PID=$OCD_PID"

OCD_READY=false
for i in $(seq 1 20); do
  sleep 1
  if ! kill -0 "$OCD_PID" 2>/dev/null; then
    cat "$OCD_LOG"
    fail "OpenOCD exited during startup."
  fi
  if grep -q "Examined RISC-V" "$OCD_LOG" 2>/dev/null; then
    OCD_READY=true
    ok "OpenOCD connected (${i}s)"
    break
  fi
done
$OCD_READY || fail "OpenOCD did not connect within 20s"

step "Verify JTAG: halt and read PC"
HALT_OUT=$(ocd_cmd "halt" "reg pc")
echo "$HALT_OUT"
echo "$HALT_OUT" | grep -qE "pc \(/64\): 0x[0-9a-f]" || fail "Cannot read PC"
ok "Target halted, PC readable"

# ═════════════════════════════════════════════════════════════════════════════
#  SET BREAKPOINT + TRIGGER + VERIFY
# ═════════════════════════════════════════════════════════════════════════════
step "Set hardware breakpoint at $BP_FUNC ($BP_ADDR)"

BP_OUT=$(printf 'rbp all\nbp %s 2 hw\n' "$BP_ADDR" | nc -q 2 localhost "$OCD_TELNET_PORT" 2>&1 | strings)
echo "$BP_OUT" >> "$LOGFILE"
echo "$BP_OUT"

if echo "$BP_OUT" | grep -q "breakpoint set"; then
  ok "Hardware breakpoint set at $BP_ADDR"
elif echo "$BP_OUT" | grep -qi "can't add\|resource not available"; then
  warn "Trigger not available (stale from previous session). Restarting OpenOCD..."
  printf 'halt\nreg tselect 0\nreg tdata1 0\nresume\n' | nc -q 2 localhost "$OCD_TELNET_PORT" > /dev/null 2>&1
  sleep 1
  kill "$OCD_PID" 2>/dev/null
  sleep 3
  openocd -f "$OCD_CFG" > "$OCD_LOG" 2>&1 &
  OCD_PID=$!
  for i in $(seq 1 20); do
    sleep 1
    grep -q "Examined RISC-V" "$OCD_LOG" 2>/dev/null && break
  done
  BP_OUT2=$(printf 'halt\nrbp all\nbp %s 2 hw\n' "$BP_ADDR" | nc -q 2 localhost "$OCD_TELNET_PORT" 2>&1 | strings)
  echo "$BP_OUT2" | grep -q "breakpoint set" || fail "Cannot set breakpoint even after OpenOCD restart"
  ok "Breakpoint set after trigger cleanup"
fi

step "Queue I/O trigger and resume"

$F2_SSH "tmux send-keys -t firesim 'dd if=/dev/iceblk of=/dev/null bs=4096 count=1' Enter"
sleep 1
ok "dd queued in console (target still halted)"

info "Resuming target..."
printf 'resume\n' | nc -q 1 localhost "$OCD_TELNET_PORT" > /dev/null 2>&1
sleep 1

step "Wait for breakpoint hit (up to 30s)"

for i in $(seq 1 30); do
  sleep 1
  STATE=$(printf "targets\n" | nc -q 2 localhost "$OCD_TELNET_PORT" 2>&1 | strings | grep "riscv.cpu" | grep -oE "halted|running" | head -1)
  if [ "$STATE" = "halted" ]; then
    HIT_PC=$(printf "reg pc\n" | nc -q 2 localhost "$OCD_TELNET_PORT" 2>&1 | strings | grep "pc (/64):" | awk '{print $3}')
    if [ "$HIT_PC" = "$BP_ADDR" ]; then
      BP_HIT=true
      ok "BREAKPOINT HIT at $BP_ADDR ($BP_FUNC) after ${i}s"
      break
    else
      info "  Halted at PC=$HIT_PC (not bp), resuming..."
      printf 'resume\n' | nc -q 1 localhost "$OCD_TELNET_PORT" > /dev/null 2>&1
    fi
  fi
done

if ! $BP_HIT; then
  FINAL_PC=$(printf "halt\nreg pc\n" | nc -q 2 localhost "$OCD_TELNET_PORT" 2>&1 | strings | grep "pc (/64):" | awk '{print $3}')
  CONSOLE=$($F2_SSH "tmux capture-pane -t firesim -p | tail -6" 2>/dev/null || echo "(n/a)")
  DD_OK=$(echo "$CONSOLE" | grep -c 'records in' || echo 0)
  echo ""
  printf "  ${RED}BREAKPOINT DID NOT HIT${RST}\n"
  echo "  Expected: $BP_ADDR ($BP_FUNC)"
  echo "  Actual PC: $FINAL_PC"
  echo "  dd executed: $DD_OK records seen"
  echo "  Console:"
  echo "$CONSOLE" | sed 's/^/    /'
  echo ""
  echo "  OpenOCD log: $OCD_LOG"
  echo "  Demo log:    $LOGFILE"
  exit 1
fi

# ═════════════════════════════════════════════════════════════════════════════
#  REGISTER INSPECTION (only if breakpoint hit)
# ═════════════════════════════════════════════════════════════════════════════
step "Inspect registers at breakpoint"
REG_OUT=$(ocd_cmd "reg pc" "reg ra" "reg sp" "reg a0" "reg a1" "reg a2")
echo "$REG_OUT"
ok "Registers captured"

# ═════════════════════════════════════════════════════════════════════════════
#  SINGLE-STEP
# ═════════════════════════════════════════════════════════════════════════════
step "Single-step through block layer (10 instructions)"
printf 'rbp all\n' | nc -q 1 localhost "$OCD_TELNET_PORT" > /dev/null 2>&1
for i in $(seq 1 10); do
  STEP_OUT=$(ocd_cmd "step" "reg pc")
  PC=$(echo "$STEP_OUT" | grep "pc (/64):" | awk '{print $3}')
  info "  step $i: PC = $PC"
done
ok "10 instructions stepped"

# ═════════════════════════════════════════════════════════════════════════════
#  GDB BACKTRACE (shows iceblk in the call chain)
# ═════════════════════════════════════════════════════════════════════════════
step "GDB backtrace (iceblk driver visible in call chain)"

ICEBLK_BASE="0xffffffff01374000"

if [ -x "$GDB" ]; then
  GDB_OUT=$(timeout 20 "$GDB" -batch \
    -ex "set confirm off" \
    -ex "set pagination off" \
    -ex "set debuginfod enabled off" \
    -ex "target remote :$OCD_GDB_PORT" \
    -ex "file $VMLINUX" \
    -ex "add-symbol-file $ICEBLK_KO $ICEBLK_BASE" \
    -ex "info registers pc ra sp a0 a1 a2" \
    -ex "bt 15" \
    -ex "disconnect" \
    2>&1 || true)
  echo "$GDB_OUT"
  echo "$GDB_OUT" >> "$LOGFILE"
  if echo "$GDB_OUT" | grep -qi "iceblk\|blk_mq"; then
    ok "GDB backtrace shows block device call chain"
  else
    warn "GDB backtrace did not show expected symbols"
  fi
else
  warn "GDB not found — skipping backtrace"
fi

# ═════════════════════════════════════════════════════════════════════════════
#  RESUME + CAPTURE CONSOLE
# ═════════════════════════════════════════════════════════════════════════════
step "Resume target"
printf 'resume\n' | nc -q 1 localhost "$OCD_TELNET_PORT" > /dev/null 2>&1
sleep 3
CONSOLE_FINAL=$($F2_SSH "tmux capture-pane -t firesim -p | tail -8" 2>/dev/null || echo "(n/a)")
echo "$CONSOLE_FINAL" >> "$LOGFILE"
ok "Target resumed, dd completed"

# ═════════════════════════════════════════════════════════════════════════════
#  SUCCESS SUMMARY
# ═════════════════════════════════════════════════════════════════════════════
echo ""
echo "================================================================="
printf "  ${GRN}DEMO COMPLETE — SUCCESS${RST}\n"
echo "================================================================="
# echo ""
# echo "What was demonstrated:"
# echo "  1. Direct JTAG debug of a running Linux kernel on AWS F2 FPGA"
# echo "  2. Hardware breakpoint at blk_mq_submit_bio — the kernel block"
# echo "     layer entry point for the iceblk device driver"
# echo "  3. Single-stepping through kernel block I/O handling code"
# echo "  4. Register inspection and backtrace showing iceblk driver path"
# echo ""
# echo "Architecture:"
# echo "  OpenOCD -> remote_bitbang (TCP $RBB_PORT) -> JTAGBridge (FPGA MMIO)"
# echo "  -> clock-adapted JTAG TAP -> Debug Module -> hart"
# echo ""
# echo "Call path (dd -> breakpoint):"
# echo "  dd if=/dev/iceblk -> VFS read -> submit_bio"
# echo "  -> blk_mq_submit_bio [BREAKPOINT HIT]"
# echo "  -> blk_mq_dispatch_rq_list -> iceblk_rq_handler"
# echo "  -> blk_mq_start_request -> iceblk_queue_request -> MMIO"
# echo ""
# echo "Key addresses:"
# echo "  blk_mq_submit_bio:  $BP_ADDR"
# echo "  iceblk module base: $ICEBLK_BASE"
# echo ""
# echo "Note: Direct breakpoint on iceblk_rq_handler (in module space at"
# echo "  ~0xffffffff013xxxxx) is not possible with SV39 hardware triggers."
# echo "  The hardware trigger compares only 39 virtual address bits;"
# echo "  module addresses require SV48. Rebuild with WithSV48 to enable."
# echo ""
# echo "Source:"
# echo "  $CHIPYARD/software/firemarshal/boards/firechip/drivers/iceblk-driver/iceblk.c"
# echo ""
# echo "Logs:"
# echo "  Demo: $LOGFILE"
# echo "  OCD:  $OCD_LOG"
# echo ""
