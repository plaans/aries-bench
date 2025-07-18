#!/bin/bash

# Exit on error
set -e

if test $# -ne 3
then
    echo "usage: compile.sh SOLVER MZN_DIR FZN_DIR" 1>&2
    exit 1
fi

SOLVER=$1
MZN_DIR=$2
FZN_DIR=$3

INSTANCES_FILE="instances.csv"
INSTANCES_PATH=$FZN_DIR/$INSTANCES_FILE

DIRS=$(ls $MZN_DIR)

NUM_COMPILED=0
NUM_SKIPPED=0

mkdir -p $FZN_DIR
echo -n "" > $INSTANCES_PATH

for DIR in $DIRS;
do
    if ! test -d $MZN_DIR/$DIR 
    then
        continue
    fi

    MODEL_FILES=$(ls $MZN_DIR/$DIR | egrep '\.mzn$')
    DATA_FILES=$(ls $MZN_DIR/$DIR | egrep '\.(dzn|json)$')

    echo Compiling $DIR problems:
    mkdir -p $FZN_DIR/$DIR

    for MODEL_FILE in $MODEL_FILES
    do
        for DATA_FILE in $DATA_FILES
        do
            FZN_FILE=${DATA_FILE%.*}.fzn
            FZN_PATH=$FZN_DIR/$DIR/$FZN_FILE

            if test -e $FZN_PATH
            then
                echo " - $MODEL_FILE $DATA_FILE skipped"
                NUM_SKIPPED=$(( NUM_SKIPPED + 1 ))
            else 
                echo " - $MODEL_FILE $DATA_FILE"
                minizinc --compile \
                    --solver $SOLVER \
                    --no-output-ozn \
                    --fzn $FZN_PATH \
                    $MZN_DIR/$DIR/$MODEL_FILE \
                    $MZN_DIR/$DIR/$DATA_FILE
                NUM_COMPILED=$(( NUM_COMPILED + 1 ))
            fi 

            echo $FZN_PATH >> $INSTANCES_PATH
        done
        echo
    done
done

NUM_TOTAL=$(( $NUM_COMPILED + $NUM_SKIPPED ))

printf "Compiled: %3d\n" $NUM_COMPILED
printf " Skipped: %3d\n" $NUM_SKIPPED
printf "   Total: %3d\n" $NUM_TOTAL