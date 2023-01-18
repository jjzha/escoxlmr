#!/bin/bash

MODEL=$1
PARAMETERS=$2

for SEED in 276800 381552 497646 624189 884832; do

  echo "Training $MODEL on $PARAMETERS on seed $SEED"
  python3 train.py \
    --dataset_configs configs/bhola/$PARAMETERS.json \
    --parameters_config configs/bhola/$MODEL.json \
    --name bhola.$MODEL.$PARAMETERS.$SEED \
    --device 0 \
    --seed $SEED

done
