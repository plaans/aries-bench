MZN_DIR := 'minizinc'
FZN_DIR := 'flatzinc'
RES_DIR := 'results'

SLURM_DIR := 'slurm'
SLURM_PATTERN := 'slurm-%A_%a'

TMP_DIR := 'tmp'
INSTANCES_FILE := FZN_DIR/'instances.csv'

TIMEOUT := '10m'
JOB_TIMEOUT := '30' 

MZN_SOLVER := 'aries'
SOLVER_BIN := 'aries'


_default:
    @just --list --unsorted
    @echo
    @echo TIMEOUT={{TIMEOUT}}
    @echo JOB_TIMEOUT={{JOB_TIMEOUT}}

# Compile the problems for the given solver
compile:
    scripts/compile.sh {{MZN_SOLVER}} {{MZN_DIR}} {{FZN_DIR}}

# Check everything is ready to solve
check *FLAGS:
    test -d {{FZN_DIR}}
    ! test -e {{RES_DIR}}/{{TMP_DIR}}
    mkdir -p {{SLURM_DIR}}
    scripts/check.sh '{{SOLVER_BIN + ' ' + FLAGS}}'

# Solve the problems with the given solver binary and flags
[confirm]
solve *FLAGS: (check FLAGS)
    scripts/solve.sh {{TIMEOUT}} '{{SOLVER_BIN + ' ' + FLAGS}}' {{FZN_DIR}} {{RES_DIR}}/{{TMP_DIR}}

# Hidden recipe for dry run
_slurm DRY *FLAGS: (check FLAGS)
    @echo
    @echo "         Solver: {{SOLVER_BIN + ' ' + FLAGS}}"
    @echo "Problem timeout: {{TIMEOUT}}"
    @echo "  Slurm timeout: {{JOB_TIMEOUT}}m"
    @echo "  Num instances: $(wc -l < {{INSTANCES_FILE}})"
    @echo
    sbatch {{DRY}} \
        --time={{JOB_TIMEOUT}} \
        --output={{SLURM_DIR}}/{{SLURM_PATTERN}}.out \
        --error={{SLURM_DIR}}/{{SLURM_PATTERN}}.err \
        --array=1-$(wc -l < {{INSTANCES_FILE}}) \
        scripts/slurm.sh {{TIMEOUT}} '{{SOLVER_BIN + ' ' + FLAGS}}' {{INSTANCES_FILE}} {{RES_DIR}}/{{TMP_DIR}}

# Dry run to solve the problems using slurm
dry-slurm *FLAGS: (_slurm '--test-only' FLAGS)

# Solve the problems using slurm
[confirm("Use recipe `dry-slurm` before. Run recipe `slurm`?")]
slurm *FLAGS: (_slurm '' FLAGS)

# Show the job with the given id
show JOB_ID:
    scontrol show jobid={{JOB_ID}}

# Watch the current jobs
watch:
    watch squeue -u $USER

# Collect the results in CSV file
collect:
    scripts/collect.sh {{RES_DIR}}/*

# Rename tmp directory
rename NAME:
    test -d {{RES_DIR}}/{{TMP_DIR}}
    ! test -e {{RES_DIR}}/{{NAME}}
    mv -f {{RES_DIR}}/{{TMP_DIR}} {{RES_DIR}}/{{NAME}}

# Plot the results
plot *ARGS:
    python scripts/plot.py {{RES_DIR}} {{ARGS}}

[confirm]
clean-fzn:
    rm -rf {{FZN_DIR}}

[confirm]
clean-tmp:
    rm -rf {{RES_DIR}}/{{TMP_DIR}}

[confirm]
clean: clean-tmp clean-fzn 
