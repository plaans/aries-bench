#!/bin/bash

# Exit on error
set -e

if test $# -ne 1
then
    echo "usage: check.sh SOLVER" 1>&2
    exit 1
fi

SOLVER=$1

FZN_FILE=$(mktemp --tmpdir aries-bench-XXXXXXXXXX.fzn)
OUT_FILE=$(mktemp --tmpdir aries-bench-XXXXXXXXXX.out)
CSV_FILE=$(mktemp --tmpdir aries-bench-XXXXXXXXXX.csv)

echo "var 1..3: x;
solve minimize x;" > $FZN_FILE

export ARIES_CSV_STATS='true'
$SOLVER -i $FZN_FILE > $OUT_FILE 2> $CSV_FILE

EXIT_CODE=0

if ! test -s $OUT_FILE
then 
    echo "'$SOLVER' does not output solution" 1>&2
    EXIT_CODE=1
fi

if ! test -s $CSV_FILE
then 
    echo "'$SOLVER' does not output statistics" 1>&2
    EXIT_CODE=1
fi

rm -f $FZN_FILE
rm -f $OUT_FILE
rm -f $CSV_FILE

exit $EXIT_CODE
