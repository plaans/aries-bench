#!/bin/bash

# Exit on error
set -e

if test $# -ne 4
then
    echo "usage: solve.sh TIMEOUT SOLVER FZN_DIR RES_DIR" 1>&2
    exit 1
fi

TIMEOUT=$1
SOLVER=$2
FZN_DIR=$3
RES_DIR=$4

DIRS=$(ls $FZN_DIR)

NUM_SOLVED=0
NUM_SKIPPED=0

for DIR in $DIRS;
do
    if ! test -d $FZN_DIR/$DIR
    then
        continue
    fi

    FZN_FILES=$(ls $FZN_DIR/$DIR | egrep '\.fzn$')

    echo Solving $DIR problems:

    for FZN_FILE in $FZN_FILES
    do
        SUB_DIR=${FZN_FILE%.*}
        RES_FILE=${FZN_FILE%.*}.dzn
        STATS_FILE=${FZN_FILE%.*}.csv

        FZN_PATH=$FZN_DIR/$DIR/$FZN_FILE
        SUB_RES_DIR=$RES_DIR/$DIR/$SUB_DIR

        if test -e $SUB_RES_DIR
        then
            echo " - $FZN_FILE skipped"
            NUM_SKIPPED=$(( NUM_SKIPPED + 1 ))
        else 
            echo " - $FZN_FILE"
            scripts/solve_single.sh $TIMEOUT "$SOLVER" $FZN_PATH $SUB_RES_DIR
            NUM_SOLVED=$(( NUM_SOLVED + 1 ))
        fi
    done
    echo
done

NUM_TOTAL=$(( $NUM_SOLVED + $NUM_SKIPPED ))

printf " Solved: %3d\n" $NUM_SOLVED
printf "Skipped: %3d\n" $NUM_SKIPPED
printf "  Total: %3d\n" $NUM_TOTAL