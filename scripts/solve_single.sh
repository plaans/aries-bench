#!/bin/bash

if test $# -ne 4
then
    echo "usage: solve_single.sh TIMEOUT SOLVER FZN_FILE RES_DIR" 1>&2
    exit 1
fi

TIMEOUT=$1
SOLVER=$2
FZN_FILE=$3
RES_DIR=$4
METADATA_FILE='metadata.txt'

export ARIES_CSV_STATS='true'

FZN_BASE_NAME=$(basename $FZN_FILE)
RES_FILE=${FZN_BASE_NAME%.*}.dzn
STATS_FILE=${FZN_BASE_NAME%.*}.csv

mkdir -p $RES_DIR
head -3 $FZN_FILE > $RES_DIR/$METADATA_FILE

timeout $TIMEOUT $SOLVER \
    -i \
    $FZN_FILE \
    > $RES_DIR/$RES_FILE \
    2> $RES_DIR/$STATS_FILE

exit 0
