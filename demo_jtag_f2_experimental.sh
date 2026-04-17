#!/usr/bin/env bash
# =============================================================================
#  EXPERIMENTAL: Direct iceblk_rq_handler breakpoint investigation
#
#  This is a separate experimental script — it does NOT modify the gold
#  demo (demo_jtag_f2.sh). It assumes the simulation is already running
#  and Linux is booted (equivalent to --demo-only preconditions).
#
#  Experiments:
#    1. Software breakpoint on iceblk_rq_handler (bypasses SV39 hw trigger limit)
#    2. Single-step from blk_mq_submit_bio into iceblk driver
#    3. Hardware breakpoint address truncation test
#
#  Usage:
#    ./demo_jtag_f2_experimental.sh             # full bring-up + experiments
#    ./demo_jtag_f2_experimental.sh --demo-only # assumes sim already running
#
#  Environment overrides (same as gold demo):
#    F2_HOST, F2_KEY, CHIPYARD, RBB_PORT, AGFI
# =============================================================================
set -uo pipefail

F2_HOST="${F2_HOST:-192.168.1.203}"
F2_KEY="${F2_KEY:-$HOME/firesim.pem}"
CHIPYARD="${CHIPYARD:-$HOME/chipyard}"
RBB_PORT="${RBB_PORT:-25050}"
AGFI="${AGFI:-agfi-06911dae2b6bf0ef7}"

VMLINUX="$CHIPYARD/software/firemarshal/images/firechip/br-base/br-base-bin-dwarf"
ICEBLK_KO="$CHIPYARD/software/firemarshal/boards/firechip/drivers/iceblk-driver/iceblk.ko"
NM="riscv64-unknown-elf-nm"
F2_SSH="ssh -i $F2_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10 ubuntu@$F2_HOST"
OCD_TELNET_PORT=4444
LOGDIR="$CHIPYARD/demo_logs"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOGFILE="$LOGDIR/experimental_${TIMESTAMP}.log"
OCD_LOG=""
OCD_CFG=""
OCD_PID=""

mkdir -p "$LOGDIR"
exec > >(tee -a "$LOGFILE") 2>&1

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[0;33m'; CYN='\033[0;36m'; MAG='\033[0;35m'; RST='\033[0m'
step_num=0
step()  { step_num=$((step_num + 1)); printf "\n${CYN}=== STEP %d: %s ===${RST}\n" "$step_num" "$1"; }
ok()    { printf "  ${GRN}[OK]${RST} %s\n" "$1"; }
warn()  { printf "  ${YLW}[WARN]${RST} %s\n" "$1"; }
fail()  { printf "  ${RED}[FAIL]${RST} %s\n" "$1"; exit 1; }
info()  { printf "  %s\n" "$1"; }
exper() { printf "  ${MAG}[EXP]${RST} %s\n" "$1"; }

ocd_cmd() {
  local out
  out=$(printf '%s\n' "$@" | nc -q 2 localhost "$OCD_TELNET_PORT" 2>&1 | tr -d '\r' | strings)
  echo "$out"
  echo "$out" >> "$LOGFILE"
}

ocd_cmd_quiet() {
  printf '%s\n' "$@" | nc -q 1 localhost "$OCD_TELNET_PORT" > /dev/null 2>&1
}

cleanup() {
  echo ""
  if [ -n "$OCD_PID" ] && kill -0 "$OCD_PID" 2>/dev/null; then
    info "Cleanup: clearing breakpoints and resuming target..."
    printf 'rbp all\nresume\n' | nc -q 2 localhost "$OCD_TELNET_PORT" > /dev/null 2>&1
    sleep 1
    kill "$OCD_PID" 2>/dev/null
    info "Cleanup: OpenOCD stopped (pid $OCD_PID)"
  fi
  for pid in $(pgrep -f "ssh.*-L.*${RBB_PORT}.*${F2_HOST}" 2>/dev/null); do
    kill "$pid" 2>/dev/null
  done
  [ -n "$OCD_CFG" ] && [ -f "$OCD_CFG" ] && rm -f "$OCD_CFG"
  info "Log saved to $LOGFILE"
}
trap cleanup EXIT

# ── Parse args ────────────────────────────────────────────────────────────────
case "${1:---full}" in
  --full)       MODE=full ;;
  --demo-only)  MODE=demo ;;
  --help|-h)    sed -n '2,20p' "$0"; exit 0 ;;
  *)            echo "Unknown argument: $1"; exit 1 ;;
esac

echo "================================================================="
printf "  ${MAG}EXPERIMENTAL${RST}: Direct iceblk_rq_handler breakpoint investigation\n"
echo "  Mode:       $MODE"
echo "  Timestamp:  $TIMESTAMP"
echo "  Log file:   $LOGFILE"
echo "  NOTE: This does NOT modify the gold demo (demo_jtag_f2.sh)"
echo "================================================================="

# ═══════════════════════════════════════════════════════════════════════════════
#  PRECONDITIONS
# ═══════════════════════════════════════════════════════════════════════════════
step "Verify preconditions"

for tool in openocd nc strings "$NM" python3; do
  command -v "$tool" > /dev/null 2>&1 || fail "Required tool not found: $tool"
done
[ -f "$VMLINUX" ]   || fail "vmlinux not found: $VMLINUX"
[ -f "$ICEBLK_KO" ] || fail "iceblk.ko not found: $ICEBLK_KO"
$F2_SSH "echo reachable" > /dev/null 2>&1 || fail "Cannot SSH to $F2_HOST"
ok "Tools present, F2 reachable"

# ═══════════════════════════════════════════════════════════════════════════════
#  FULL BRING-UP (unless --demo-only)
# ═══════════════════════════════════════════════════════════════════════════════
if [ "$MODE" = "full" ]; then

  step "Kill any stale simulation and reload AGFI"
  $F2_SSH "sudo pkill -9 FireSim-f2 2>/dev/null; tmux kill-session -t firesim 2>/dev/null; sleep 2" || true
  LOAD_OUT=$($F2_SSH "sudo fpga-load-local-image -S 0 -I $AGFI 2>&1")
  echo "$LOAD_OUT" | grep -qi "loaded\|success\|AFIDEVICE" && ok "AGFI loaded" || warn "AGFI load status unclear"
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

# ═══════════════════════════════════════════════════════════════════════════════
#  VERIFY SIMULATION
# ═══════════════════════════════════════════════════════════════════════════════
step "Verify simulation is running"

SIM_COUNT=$($F2_SSH "pgrep -c FireSim-f2 2>/dev/null" 2>/dev/null | tr -d '[:space:]')
SIM_COUNT="${SIM_COUNT:-0}"
[ "$SIM_COUNT" -gt 0 ] 2>/dev/null || fail "No FireSim simulation running"
ok "Simulation running, F2 reachable"

# ═══════════════════════════════════════════════════════════════════════════════
#  RESOLVE ADDRESSES
# ═══════════════════════════════════════════════════════════════════════════════
step "Resolve symbol addresses"

BP_SUBMIT_RAW=$("$NM" "$VMLINUX" 2>/dev/null | awk '$3 == "blk_mq_submit_bio" && $2 == "T" { print $1; exit }')
[ -n "$BP_SUBMIT_RAW" ] || fail "blk_mq_submit_bio not in vmlinux"
BP_SUBMIT="0x$BP_SUBMIT_RAW"
ok "blk_mq_submit_bio = $BP_SUBMIT (kernel proper, SV39-safe)"

ICEBLK_BASE=$($F2_SSH "tmux send-keys -t firesim 'cat /sys/module/iceblk/sections/.text 2>/dev/null || grep iceblk /proc/modules | awk \"{print \\\"0x\\\"\\\$6}\"' Enter" 2>/dev/null)
sleep 3
CONSOLE=$($F2_SSH "tmux capture-pane -t firesim -p 2>/dev/null" 2>/dev/null || echo "")
ICEBLK_BASE=$(echo "$CONSOLE" | grep -oE '0x[0-9a-f]{10,16}' | grep 'ffffffff' | tail -1)

if [ -z "$ICEBLK_BASE" ]; then
  ICEBLK_BASE="0xffffffff01374000"
  warn "Could not dynamically resolve iceblk base; using known value: $ICEBLK_BASE"
else
  ok "iceblk module base (dynamic): $ICEBLK_BASE"
fi

HANDLER_OFFSET=$("$NM" "$ICEBLK_KO" 2>/dev/null | awk '$3 == "iceblk_rq_handler" { print $1; exit }')
if [ -z "$HANDLER_OFFSET" ]; then
  fail "iceblk_rq_handler not found in iceblk.ko symbol table"
fi
ok "iceblk_rq_handler offset in .ko = 0x$HANDLER_OFFSET"

HANDLER_ADDR=$(python3 -c "
base = int('$ICEBLK_BASE', 16)
offset = int('$HANDLER_OFFSET', 16)
print(hex(base + offset))
")
ok "iceblk_rq_handler absolute address = $HANDLER_ADDR"

# Show SV39 analysis
python3 -c "
addr = int('$HANDLER_ADDR', 16)
bit38 = (addr >> 38) & 1
upper = (addr >> 39)
canonical_sv39 = (upper == 0 and bit38 == 0) or (upper == 0x1ffffff and bit38 == 1)
print(f'  Address analysis:')
print(f'    Full:      {hex(addr)}')
print(f'    Bit 38:    {bit38}')
print(f'    Bits[63:39]: {hex(upper)}')
print(f'    SV39 canonical: {canonical_sv39}')
print(f'    Lower 39 bits: {hex(addr & 0x7fffffffff)}')
"

# ═══════════════════════════════════════════════════════════════════════════════
#  SET UP JTAG
# ═══════════════════════════════════════════════════════════════════════════════
step "Set up SSH tunnel + OpenOCD"

for pid in $(pgrep -f "ssh.*-L.*${RBB_PORT}.*${F2_HOST}" 2>/dev/null); do
  kill "$pid" 2>/dev/null
done
for pid in $(pgrep -f "openocd.*remote_bitbang" 2>/dev/null); do
  kill "$pid" 2>/dev/null
done
sleep 2

ssh -i "$F2_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
  -f -N -L ${RBB_PORT}:localhost:${RBB_PORT} ubuntu@"$F2_HOST"
sleep 2
ss -tln 2>/dev/null | grep -q ":${RBB_PORT} " || fail "SSH tunnel not listening"
ok "Tunnel established"

OCD_CFG=$(mktemp /tmp/jtag_exp_XXXX.cfg)
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

OCD_LOG="$LOGDIR/openocd_experimental_${TIMESTAMP}.log"
openocd -f "$OCD_CFG" > "$OCD_LOG" 2>&1 &
OCD_PID=$!

OCD_READY=false
for i in $(seq 1 20); do
  sleep 1
  kill -0 "$OCD_PID" 2>/dev/null || { cat "$OCD_LOG"; fail "OpenOCD exited during startup."; }
  if grep -q "Examined RISC-V" "$OCD_LOG" 2>/dev/null; then
    OCD_READY=true; ok "OpenOCD connected (${i}s)"; break
  fi
done
$OCD_READY || fail "OpenOCD did not connect within 20s"

ocd_cmd "halt" > /dev/null
ok "Target halted"

# ═══════════════════════════════════════════════════════════════════════════════
#  EXPERIMENT 1: SOFTWARE BREAKPOINT on iceblk_rq_handler
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "================================================================="
printf "  ${MAG}EXPERIMENT 1${RST}: Software breakpoint on iceblk_rq_handler\n"
echo "================================================================="
echo ""
exper "Software breakpoints patch memory with 'ebreak', no hw trigger needed."
exper "This should bypass the SV39 address-width limitation entirely."

step "Attempt software breakpoint at iceblk_rq_handler ($HANDLER_ADDR)"

ocd_cmd_quiet "rbp all"

# First, verify we can read memory at the handler address
exper "Reading instruction at $HANDLER_ADDR to verify memory access..."
MEM_OUT=$(ocd_cmd "mdw $HANDLER_ADDR 1")
echo "$MEM_OUT"

if echo "$MEM_OUT" | grep -qiE "error|failed|could not|exception"; then
  warn "Cannot read memory at $HANDLER_ADDR — software breakpoint will likely fail"
  MEM_READABLE=false
else
  MEM_READABLE=true
  ok "Memory at $HANDLER_ADDR is readable"
fi

# Try setting a software breakpoint (no 'hw' flag = software breakpoint)
exper "Setting software breakpoint: bp $HANDLER_ADDR 2"
SW_BP_OUT=$(ocd_cmd "bp $HANDLER_ADDR 2")
echo "$SW_BP_OUT"

SW_BP_SET=false
if echo "$SW_BP_OUT" | grep -qi "breakpoint set"; then
  SW_BP_SET=true
  ok "Software breakpoint set at $HANDLER_ADDR"
elif echo "$SW_BP_OUT" | grep -qi "error\|failed\|can't"; then
  warn "Software breakpoint failed: $SW_BP_OUT"
else
  warn "Ambiguous response — testing anyway"
  SW_BP_SET=true
fi

SW_BP_HIT=false
if $SW_BP_SET; then
  step "Trigger I/O and test software breakpoint"

  $F2_SSH "tmux send-keys -t firesim 'dd if=/dev/iceblk of=/dev/null bs=4096 count=1 2>&1; echo SWBP_DD_DONE' Enter" 2>/dev/null
  sleep 1
  ok "dd queued (target still halted)"

  exper "Resuming target..."
  ocd_cmd_quiet "resume"

  exper "Waiting for breakpoint hit (up to 30s)..."
  for i in $(seq 1 30); do
    sleep 1
    STATE=$(printf "targets\n" | nc -q 2 localhost "$OCD_TELNET_PORT" 2>&1 | strings | grep "riscv.cpu" | grep -oE "halted|running" | head -1)
    if [ "$STATE" = "halted" ]; then
      HIT_PC=$(printf "reg pc\n" | nc -q 2 localhost "$OCD_TELNET_PORT" 2>&1 | strings | grep "pc (/64):" | awk '{print $3}')
      exper "Target halted at PC=$HIT_PC after ${i}s"

      # Check if PC matches handler address (exact or nearby for compressed instructions)
      MATCH=$(python3 -c "
hit = int('$HIT_PC', 16)
expect = int('$HANDLER_ADDR', 16)
delta = abs(hit - expect)
if delta <= 2:
    print('EXACT')
elif delta <= 32:
    print('NEAR')
else:
    print('NO')
")
      if [ "$MATCH" = "EXACT" ] || [ "$MATCH" = "NEAR" ]; then
        SW_BP_HIT=true
        ok "SOFTWARE BREAKPOINT HIT at $HIT_PC (iceblk_rq_handler) after ${i}s!"

        exper "Capturing registers..."
        ocd_cmd "reg pc" "reg ra" "reg sp" "reg a0"

        exper "Capturing backtrace via single OpenOCD register dump..."
        ocd_cmd "reg ra"
        break
      else
        exper "PC=$HIT_PC does not match handler $HANDLER_ADDR (delta too large), resuming..."
        ocd_cmd_quiet "resume"
      fi
    fi
  done

  if ! $SW_BP_HIT; then
    CONSOLE=$($F2_SSH "tmux capture-pane -t firesim -p | tail -8" 2>/dev/null || echo "(n/a)")
    DD_DONE=$(echo "$CONSOLE" | grep -c 'SWBP_DD_DONE' || echo 0)
    warn "Software breakpoint did NOT hit after 30s"
    info "  dd completed: $( [ "$DD_DONE" -gt 0 ] && echo 'yes' || echo 'no/unknown')"
    info "  Console tail:"
    echo "$CONSOLE" | sed 's/^/    /'
  fi

  ocd_cmd_quiet "rbp all"
  ocd_cmd_quiet "resume"
  sleep 2
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  EXPERIMENT 2: Hardware breakpoint with SV39-truncated address
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "================================================================="
printf "  ${MAG}EXPERIMENT 2${RST}: Hardware trigger with SV39-truncated address\n"
echo "================================================================="
echo ""

TRUNC_ADDR=$(python3 -c "
addr = int('$HANDLER_ADDR', 16)
trunc39 = addr & 0x7fffffffff
sign_ext = trunc39 | (0xffffffffffffffff << 39) if (trunc39 >> 38) & 1 else trunc39
print(hex(sign_ext & 0xffffffffffffffff))
")
exper "Full handler addr:  $HANDLER_ADDR"
exper "SV39-truncated:     $TRUNC_ADDR"

SAME=$(python3 -c "print('same' if int('$HANDLER_ADDR',16) == int('$TRUNC_ADDR',16) else 'different')")
if [ "$SAME" = "same" ]; then
  exper "Addresses match — the address IS SV39-canonical. HW trigger might work."
else
  exper "Addresses differ — confirms non-canonical for SV39."
  exper "Testing whether hw trigger on truncated addr might match anyway..."
fi

step "Try hardware breakpoint at truncated address $TRUNC_ADDR"

ocd_cmd_quiet "halt"
ocd_cmd_quiet "rbp all"
HW_TRUNC_OUT=$(ocd_cmd "bp $TRUNC_ADDR 2 hw")
echo "$HW_TRUNC_OUT"

HW_TRUNC_SET=false
if echo "$HW_TRUNC_OUT" | grep -qi "breakpoint set"; then
  HW_TRUNC_SET=true
  ok "Hardware breakpoint set at truncated addr $TRUNC_ADDR"
else
  warn "Could not set hw breakpoint at $TRUNC_ADDR"
fi

HW_TRUNC_HIT=false
if $HW_TRUNC_SET; then
  $F2_SSH "tmux send-keys -t firesim 'dd if=/dev/iceblk of=/dev/null bs=4096 count=1 2>&1; echo HWTRUNC_DONE' Enter" 2>/dev/null
  sleep 1
  ocd_cmd_quiet "resume"

  for i in $(seq 1 20); do
    sleep 1
    STATE=$(printf "targets\n" | nc -q 2 localhost "$OCD_TELNET_PORT" 2>&1 | strings | grep "riscv.cpu" | grep -oE "halted|running" | head -1)
    if [ "$STATE" = "halted" ]; then
      HIT_PC=$(printf "reg pc\n" | nc -q 2 localhost "$OCD_TELNET_PORT" 2>&1 | strings | grep "pc (/64):" | awk '{print $3}')
      exper "Halted at PC=$HIT_PC after ${i}s"

      MATCH=$(python3 -c "
hit = int('$HIT_PC', 16)
expect = int('$HANDLER_ADDR', 16)
trunc = int('$TRUNC_ADDR', 16)
if abs(hit - expect) <= 2 or abs(hit - trunc) <= 2:
    print('HIT')
else:
    print('NO')
")
      if [ "$MATCH" = "HIT" ]; then
        HW_TRUNC_HIT=true
        ok "Hardware trigger on truncated addr matched iceblk_rq_handler!"
        break
      else
        ocd_cmd_quiet "resume"
      fi
    fi
  done

  if ! $HW_TRUNC_HIT; then
    warn "Hardware breakpoint on truncated addr did NOT hit (expected)"
  fi

  ocd_cmd_quiet "halt"
  ocd_cmd_quiet "rbp all"
  ocd_cmd_quiet "resume"
  sleep 2
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  EXPERIMENT 3: Step from blk_mq_submit_bio into iceblk
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "================================================================="
printf "  ${MAG}EXPERIMENT 3${RST}: Step from blk_mq_submit_bio toward iceblk\n"
echo "================================================================="
echo ""
exper "Hit hw bp at blk_mq_submit_bio, then single-step up to 500 instrs"
exper "looking for PC to enter the iceblk module address range."

step "Set hw breakpoint at blk_mq_submit_bio ($BP_SUBMIT)"

ocd_cmd_quiet "halt"
ocd_cmd_quiet "rbp all"
STEP_BP_OUT=$(ocd_cmd "bp $BP_SUBMIT 2 hw")
echo "$STEP_BP_OUT"

if ! echo "$STEP_BP_OUT" | grep -qi "breakpoint set"; then
  warn "Cannot set hw breakpoint at $BP_SUBMIT — skipping step experiment"
else
  ok "Hardware breakpoint set at $BP_SUBMIT"

  $F2_SSH "tmux send-keys -t firesim 'dd if=/dev/iceblk of=/dev/null bs=4096 count=1 2>&1; echo STEP_DD_DONE' Enter" 2>/dev/null
  sleep 1
  ocd_cmd_quiet "resume"

  STEP_BP_HIT=false
  for i in $(seq 1 20); do
    sleep 1
    STATE=$(printf "targets\n" | nc -q 2 localhost "$OCD_TELNET_PORT" 2>&1 | strings | grep "riscv.cpu" | grep -oE "halted|running" | head -1)
    if [ "$STATE" = "halted" ]; then
      HIT_PC=$(printf "reg pc\n" | nc -q 2 localhost "$OCD_TELNET_PORT" 2>&1 | strings | grep "pc (/64):" | awk '{print $3}')
      if [ "$HIT_PC" = "$BP_SUBMIT" ]; then
        STEP_BP_HIT=true
        ok "Hit blk_mq_submit_bio at $BP_SUBMIT after ${i}s"
        break
      else
        ocd_cmd_quiet "resume"
      fi
    fi
  done

  if ! $STEP_BP_HIT; then
    warn "Could not hit blk_mq_submit_bio — skipping step-through"
  else
    step "Single-step toward iceblk module (up to 500 instructions)"

    ocd_cmd_quiet "rbp all"

    ICEBLK_BASE_INT=$(python3 -c "print(int('$ICEBLK_BASE', 16))")
    ICEBLK_END_INT=$(python3 -c "print(int('$ICEBLK_BASE', 16) + 0x10000)")
    REACHED_ICEBLK=false
    STEP_COUNT=0
    STEP_LIMIT=500

    for i in $(seq 1 $STEP_LIMIT); do
      printf "step\n" | nc -q 1 localhost "$OCD_TELNET_PORT" > /dev/null 2>&1
      sleep 0.1
      PC_RAW=$(printf "reg pc\n" | nc -q 1 localhost "$OCD_TELNET_PORT" 2>&1 | strings | grep "pc (/64):" | awk '{print $3}')
      STEP_COUNT=$i

      if [ $((i % 50)) -eq 0 ]; then
        exper "  step $i: PC=$PC_RAW"
      fi

      IN_ICEBLK=$(python3 -c "
try:
    pc = int('$PC_RAW', 16)
    if $ICEBLK_BASE_INT <= pc < $ICEBLK_END_INT:
        print('yes')
    else:
        print('no')
except:
    print('no')
")
      if [ "$IN_ICEBLK" = "yes" ]; then
        REACHED_ICEBLK=true
        ok "REACHED ICEBLK MODULE at step $i! PC=$PC_RAW"

        exper "Capturing registers at iceblk entry:"
        ocd_cmd "reg pc" "reg ra" "reg sp" "reg a0"

        exper "Stepping 5 more inside iceblk..."
        for j in $(seq 1 5); do
          STEP2=$(ocd_cmd "step" "reg pc")
          PC2=$(echo "$STEP2" | grep "pc (/64):" | awk '{print $3}')
          exper "  iceblk step $j: PC=$PC2"
        done
        break
      fi
    done

    if ! $REACHED_ICEBLK; then
      warn "Did NOT reach iceblk module in $STEP_COUNT steps"
      PC_FINAL=$(printf "reg pc\n" | nc -q 1 localhost "$OCD_TELNET_PORT" 2>&1 | strings | grep "pc (/64):" | awk '{print $3}')
      info "  Final PC after $STEP_COUNT steps: $PC_FINAL"
    fi
  fi

  ocd_cmd_quiet "halt"
  ocd_cmd_quiet "rbp all"
  ocd_cmd_quiet "resume"
fi

# ═══════════════════════════════════════════════════════════════════════════════
#  RESULTS SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "================================================================="
printf "  ${MAG}EXPERIMENTAL RESULTS SUMMARY${RST}\n"
echo "================================================================="
echo ""
echo "Experiment 1 — Software breakpoint on iceblk_rq_handler:"
if $SW_BP_HIT; then
  printf "  ${GRN}SUCCESS${RST}: Software breakpoint hit at $HANDLER_ADDR\n"
  echo "  This proves software breakpoints bypass the SV39 hw trigger limit."
  echo "  Recommendation: Use 'bp <addr> 2' instead of 'bp <addr> 2 hw' for"
  echo "  kernel module addresses to get direct iceblk breakpoints."
else
  if $SW_BP_SET; then
    printf "  ${RED}FAILED${RST}: Breakpoint was set but did not hit\n"
    echo "  The breakpoint was accepted by OpenOCD but the target did not stop."
    if ! $MEM_READABLE; then
      echo "  Root cause: memory at $HANDLER_ADDR is not accessible via debug module."
      echo "  The debug module may not be able to resolve non-canonical SV39 VAs."
    else
      echo "  Memory was readable; the ebreak patch may not have triggered correctly."
    fi
  else
    printf "  ${RED}FAILED${RST}: Could not set software breakpoint\n"
  fi
fi

echo ""
echo "Experiment 2 — Hardware trigger with SV39-truncated address:"
if $HW_TRUNC_HIT; then
  printf "  ${GRN}SUCCESS${RST}: Truncated address matched\n"
else
  printf "  ${YLW}DID NOT HIT${RST} (expected for non-canonical addresses)\n"
  echo "  The hw trigger compares only lower 39 bits; the module address"
  echo "  bit-pattern does not produce a match."
fi

echo ""
echo "Experiment 3 — Step from blk_mq_submit_bio into iceblk:"
if [ "${REACHED_ICEBLK:-false}" = "true" ]; then
  printf "  ${GRN}SUCCESS${RST}: Reached iceblk module after $STEP_COUNT steps\n"
  echo "  This provides a path to inspect iceblk code from the gold demo"
  echo "  by adding a step-through phase after the blk_mq_submit_bio hit."
else
  if [ "${STEP_BP_HIT:-false}" = "true" ]; then
    printf "  ${YLW}PARTIAL${RST}: Hit blk_mq_submit_bio but did not reach iceblk in $STEP_COUNT steps\n"
    echo "  The call chain from blk_mq_submit_bio to iceblk_rq_handler may be"
    echo "  longer than $STEP_LIMIT instructions, or the path differs at runtime."
  else
    printf "  ${RED}SKIPPED${RST}: Could not hit blk_mq_submit_bio\n"
  fi
fi

echo ""
echo "Overall recommendation:"
if $SW_BP_HIT; then
  printf "  ${GRN}Direct iceblk_rq_handler breakpoint is possible via software breakpoints.${RST}\n"
  echo "  Update the gold demo to use 'bp <addr> 2' (without hw) for module addresses."
elif [ "${REACHED_ICEBLK:-false}" = "true" ]; then
  echo "  Direct hw breakpoint not possible, but stepping from blk_mq_submit_bio"
  echo "  reaches iceblk in ~$STEP_COUNT steps. This could be added as an optional"
  echo "  phase in the gold demo."
else
  echo "  Direct iceblk_rq_handler breakpoint is not currently possible."
  echo "  Blockers:"
  echo "    1. Hardware triggers: SV39 address width (39 bits) cannot match"
  echo "       module addresses in the 0xffffffff01xxxxxx range"
  echo "    2. Software breakpoints: may fail if the debug module cannot"
  echo "       resolve non-canonical virtual addresses for memory patching"
  echo "  To fix: rebuild FPGA with WithSV48 config fragment (pgLevels=4)"
  echo "  This widens vaddrBits to 48, making all kernel module addresses"
  echo "  reachable by both hardware triggers and software breakpoints."
fi

echo ""
echo "Logs:"
echo "  Experiment: $LOGFILE"
echo "  OpenOCD:    $OCD_LOG"
echo ""
