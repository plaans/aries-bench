#!/bin/bash

#SBATCH --job-name=aries-fzn

# Exit on error
set -e

if test $# -ne 4
then
    echo "usage: slurm.sh TIMEOUT SOLVER INSTANCES_FILE RES_DIR" 1>&2
    exit 1
fi

TIMEOUT=$1
SOLVER=$2
INSTANCES_FILE=$3
RES_DIR=$4

ID=$SLURM_ARRAY_TASK_ID

FZN_FILE=$(cat $INSTANCES_FILE | sed "${ID}q;d")
SUB_PATH=$(echo $FZN_FILE | sed -E 's/.+\/([^/]+)\/([^/]+)\.fzn$/\1\/\2/')
SUB_RES_DIR=$RES_DIR/$SUB_PATH

scripts/solve_single.sh $TIMEOUT "$SOLVER" $FZN_FILE $SUB_RES_DIR
