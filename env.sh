# Minimal Chipyard environment for RTL generation + FireSim metasim on this VM
# (no conda-based chipyard setup; reuses the FireSim HBM environment).
# Generated for the HBM/Radiance integration; see HBM_RADIANCE_INTEGRATION_REPORT.md
source /scratch/trazzaque/env-hbm.sh
# firtool 1.75.0 (conda-reqs/circt.json) for Chisel 6.7.0 RTL generation
export PATH=/scratch/trazzaque/tools/firtool-1.75.0/bin:$PATH
# RISCV provides libfesvr.a + fesvr headers for the FireSim driver link
# (riscv-isa-sim v1.1.0 built with CXXFLAGS="-include cstdint"; no
# cross-compiler is needed for the MemPerf traffic-generator target).
export RISCV=/scratch/trazzaque/tools/riscv
