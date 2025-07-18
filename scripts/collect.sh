#!/bin/bash

# Exit on error
set -e

if test $# -eq 0
then
    echo "usage: collect.sh RES_DIR+" 1>&2
    exit 1
fi

RES_DIRS="$@"

for RES_DIR in $RES_DIRS
do
    # If RES_DIR is not a directory
    if ! test -d $RES_DIR
    then
        echo "'$RES_DIR' is not a directory" 1>&2
        exit 1
    fi

    echo ""
    echo "----- $RES_DIR -----"

    OUTPUT_FILE=$RES_DIR/results.csv

    # If output file already exists: continue
    if test -f $OUTPUT_FILE
    then
        echo "$OUTPUT_FILE already exists"
        continue
    fi

    DIRS=$(ls $RES_DIR)

    NUM_COLLECTED=0

    echo -n "" > $OUTPUT_FILE

    for DIR in $DIRS;
    do
        # If DIR is not a directory: continue
        if ! test -d $RES_DIR/$DIR
        then
            continue
        fi

        PROBLEMS=$(ls $RES_DIR/$DIR)

        echo Collecting $DIR results:

        for PROBLEM in $PROBLEMS;
        do
            CSV_FILE=$PROBLEM.csv

            CSV_PATH=$RES_DIR/$DIR/$PROBLEM/$PROBLEM.csv
            echo " - $CSV_FILE"

            tail -n +2 $CSV_PATH |
                sed -E "s/^/$DIR,$PROBLEM,/g" \
                >> $OUTPUT_FILE


            NUM_COLLECTED=$(( NUM_COLLECTED + 1 ))
        done
        echo
    done

    HEADER=problem,flatzinc,$(head -1 $CSV_PATH)
    sed -i "1i$HEADER" $OUTPUT_FILE

    printf "Collected: %3d\n" $NUM_COLLECTED
done
