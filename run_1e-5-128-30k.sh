python3 src/run_mlm_xlmr.py --train_file resources/esco_features.json \
                            --line_by_line \
                            --output_dir xlm-experiment-1e-5-128-30k \
                            --model_type xlm-roberta-large \
                            --tokenizer_name xlm-roberta-large \
                            --per_device_train_batch_size 8 \
                            --per_device_eval_batch_size 8 \
                            --gradient_accumulation_steps 16  \
                            --eval_accumulation_steps 16 \
                            --gradient_checkpointing \
                            --model_name_or_path xlm-roberta-large \
                            --tf32 1 \
                            --do_train \
                            --do_eval \
                            --evaluation_strategy steps \
                            --max_steps 30000 \
                            --save_steps 10000 \
                            --learning_rate 0.00001 \
                            --logging_steps 500 \
                            --eval_steps 1000 \
                            --warmup_steps 3000 \
                            --weight_decay 0.01
#                            \
#                            --prediction_loss_only
