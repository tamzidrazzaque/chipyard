# See LICENSE for license details.

# DOC include start: Bridge Build System Changes
##########################
# Driver Sources & Flags #
##########################

# FESVR is a host-side driver dependency. Allow it to live outside the target
# cross-toolchain while retaining the historical RISCV-based default.
FIRESIM_FESVR_PREFIX ?= $(RISCV)
ifeq (,$(strip $(FIRESIM_FESVR_PREFIX)))
FIRESIM_FESVR_PREFIX := $(RISCV)
endif

FIRESIM_FESVR_ARCHIVE := $(FIRESIM_FESVR_PREFIX)/lib/libfesvr.a
FIRESIM_RISCV_DSO := $(FIRESIM_FESVR_PREFIX)/lib/libriscv.so

ifeq (,$(wildcard $(FIRESIM_FESVR_ARCHIVE)))
$(error FireSim host FESVR archive not found: $(FIRESIM_FESVR_ARCHIVE))
endif
ifeq (,$(wildcard $(FIRESIM_RISCV_DSO)))
$(error FireSim cospike library not found: $(FIRESIM_RISCV_DSO))
endif
LRISCV=-lriscv

firechip_lib_dir = $(chipyard_dir)/generators/firechip/chip/src/main/cc
firechip_bridgestubs_lib_dir = $(chipyard_dir)/generators/firechip/bridgestubs/src/main/cc
testchipip_csrc_dir = $(chipyard_dir)/generators/testchipip/src/main/resources/testchipip/csrc

# DRIVER_H only used to update recipe pre-reqs (ok to track more files)

# fesvr and related srcs
DRIVER_H += \
		$(shell find $(testchipip_csrc_dir) -name "*.h") \
		$(shell find $(firechip_bridgestubs_lib_dir)/fesvr -name "*.h")
DRIVER_CC += \
		$(testchipip_csrc_dir)/cospike_impl.cc \
		$(testchipip_csrc_dir)/testchip_tsi.cc \
		$(testchipip_csrc_dir)/testchip_dtm.cc \
		$(testchipip_csrc_dir)/testchip_htif.cc \
		$(firechip_bridgestubs_lib_dir)/fesvr/firesim_tsi.cc \
		$(firechip_bridgestubs_lib_dir)/fesvr/firesim_dtm.cc \
		$(FIRESIM_FESVR_ARCHIVE)
# Disable missing override warning for testchipip.
TARGET_CXX_FLAGS += \
		-isystem $(testchipip_csrc_dir) \
		-isystem $(FIRESIM_FESVR_PREFIX)/include \
		-Wno-inconsistent-missing-override
TARGET_LD_FLAGS += \
		-L$(FIRESIM_FESVR_PREFIX)/lib \
		-Wl,-rpath,$(FIRESIM_FESVR_PREFIX)/lib \
		$(LRISCV)

# top-level sources
DRIVER_CC += $(addprefix $(firechip_lib_dir)/firesim/, $(addsuffix .cc, firesim_top))
TARGET_CXX_FLAGS += -I$(firechip_bridgestubs_lib_dir)/bridge/test

# bridge sources
DRIVER_H += $(shell find $(firechip_bridgestubs_lib_dir) -name "*.h")
DRIVER_CC += \
		$(wildcard \
			$(addprefix \
				$(firechip_bridgestubs_lib_dir)/, \
				$(addsuffix .cc,bridges/* bridges/tracerv/* bridges/cospike/*) \
			) \
		)
TARGET_CXX_FLAGS += \
		-I$(firechip_bridgestubs_lib_dir) \
		-I$(firechip_bridgestubs_lib_dir)/bridge \
		-I$(firechip_bridgestubs_lib_dir)/bridge/tracerv \
		-I$(firechip_bridgestubs_lib_dir)/bridge/cospike
TARGET_LD_FLAGS += \
	-l:libdwarf.so -l:libelf.so \
	-lz \

# other
TARGET_CXX_FLAGS += \
		-I$(GENERATED_DIR) \
		-g

# DOC include end: Bridge Build System Changes
