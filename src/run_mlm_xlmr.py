#!/usr/bin/env python
# coding=utf-8
# Copyright 2020 The HuggingFace Team All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Fine-tuning the library models for masked language modeling (BERT, ALBERT, RoBERTa...) on a text file or a dataset.

Here is the full list of checkpoints on the hub that can be fine-tuned by this script:
https://huggingface.co/models?filter=fill-mask
"""
# You can also adapt this script on your own masked language modeling task. Pointers for this are left as comments.

import json
import logging
import math
import os
import pickle
import random
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import chain
from typing import Optional, Tuple, Union
from sklearn.metrics import accuracy_score
import datasets
import torch
import transformers
# import wandb
from datasets import load_dataset, load_metric
from filelock import FileLock
from torch import nn
from torch.nn import CrossEntropyLoss
from torch.utils.data import Dataset
from transformers import (AutoConfig, AutoModelForPreTraining, AutoTokenizer, CONFIG_MAPPING,
                          DataCollatorForLanguageModeling, HfArgumentParser, MODEL_FOR_MASKED_LM_MAPPING,
                          PreTrainedTokenizer, RobertaModel, Trainer, TrainingArguments, is_torch_tpu_available,
                          set_seed)
from transformers.models.bert.modeling_bert import (BertForPreTrainingOutput)
from transformers.models.roberta.modeling_roberta import RobertaLMHead, RobertaPreTrainedModel
from transformers.trainer_utils import get_last_checkpoint
from transformers.utils import send_example_telemetry  # check_min_version,
from transformers.utils.versions import require_version

require_version("datasets>=1.8.0", "To fix: pip install -r examples/pytorch/language-modeling/requirements.txt")
# wandb.init(project="esco-xlm-r", entity="jjzha")
os.environ["WANDB_DISABLED"] = "true"
torch.backends.cuda.matmul.allow_tf32 = True

logger = logging.getLogger(__name__)
MODEL_CONFIG_CLASSES = list(MODEL_FOR_MASKED_LM_MAPPING.keys())
MODEL_TYPES = tuple(conf.model_type for conf in MODEL_CONFIG_CLASSES)
os.environ['CUDA_LAUNCH_BLOCKING'] = "1"


@dataclass
class ModelArguments:
    """
    Arguments pertaining to which model/config/tokenizer we are going to fine-tune, or train from scratch.
    """

    model_name_or_path: Optional[str] = field(
            default=None,
            metadata={
                    "help": (
                            "The model checkpoint for weights initialization.Don't set if you want to train a model "
                            "from scratch."
                    )
                    },
            )
    model_type: Optional[str] = field(
            default=None,
            metadata={"help": "If training from scratch, pass a model type from the list: " + ", ".join(MODEL_TYPES)},
            )
    config_overrides: Optional[str] = field(
            default=None,
            metadata={
                    "help": (
                            "Override some existing default config settings when a model is trained from scratch. "
                            "Example: "
                            "n_embd=10,resid_pdrop=0.2,scale_attn_weights=false,summary_type=cls_index"
                    )
                    },
            )
    config_name: Optional[str] = field(
            default=None, metadata={"help": "Pretrained config name or path if not the same as model_name"}
            )
    tokenizer_name: Optional[str] = field(
            default=None, metadata={"help": "Pretrained tokenizer name or path if not the same as model_name"}
            )
    cache_dir: Optional[str] = field(
            default=None,
            metadata={"help": "Where do you want to store the pretrained models downloaded from huggingface.co"},
            )
    use_fast_tokenizer: bool = field(
            default=True,
            metadata={"help": "Whether to use one of the fast tokenizer (backed by the tokenizers library) or not."},
            )
    model_revision: str = field(
            default="main",
            metadata={"help": "The specific model version to use (can be a branch name, tag name or commit id)."},
            )
    use_auth_token: bool = field(
            default=False,
            metadata={
                    "help": (
                            "Will use the token generated when running `transformers-cli login` (necessary to use "
                            "this script "
                            "with private models)."
                    )
                    },
            )

    def __post_init__(self):
        if self.config_overrides is not None and (self.config_name is not None or self.model_name_or_path is not None):
            raise ValueError(
                    "--config_overrides can't be used in combination with --config_name or --model_name_or_path"
                    )


@dataclass
class DataTrainingArguments:
    """
    Arguments pertaining to what data we are going to input our model for training and eval.
    """

    dataset_name: Optional[str] = field(
            default=None, metadata={"help": "The name of the dataset to use (via the datasets library)."}
            )
    dataset_config_name: Optional[str] = field(
            default=None, metadata={"help": "The configuration name of the dataset to use (via the datasets library)."}
            )
    train_file: Optional[str] = field(default=None, metadata={"help": "The input training data file (a text file)."})
    validation_file: Optional[str] = field(
            default=None,
            metadata={"help": "An optional input evaluation data file to evaluate the perplexity on (a text file)."},
            )
    overwrite_cache: bool = field(
            default=False, metadata={"help": "Overwrite the cached training and evaluation sets"}
            )
    validation_split_percentage: Optional[int] = field(
            default=1,
            metadata={
                    "help": "The percentage of the train set used as validation set in case there's no validation split"
                    },
            )
    max_seq_length: Optional[int] = field(
            default=None,
            metadata={
                    "help": (
                            "The maximum total input sequence length after tokenization. Sequences longer "
                            "than this will be truncated."
                    )
                    },
            )
    preprocessing_num_workers: Optional[int] = field(
            default=None,
            metadata={"help": "The number of processes to use for the preprocessing."},
            )
    mlm_probability: float = field(
            default=0.15, metadata={"help": "Ratio of tokens to mask for masked language modeling loss"}
            )
    line_by_line: bool = field(
            default=False,
            metadata={"help": "Whether distinct lines of text in the dataset are to be handled as distinct sequences."},
            )
    pad_to_max_length: bool = field(
            default=False,
            metadata={
                    "help": (
                            "Whether to pad all samples to `max_seq_length`. "
                            "If False, will pad the samples dynamically when batching to the maximum length in the "
                            "batch."
                    )
                    },
            )
    max_train_samples: Optional[int] = field(
            default=None,
            metadata={
                    "help": (
                            "For debugging purposes or quicker training, truncate the number of training examples to "
                            "this "
                            "value if set."
                    )
                    },
            )
    max_eval_samples: Optional[int] = field(
            default=None,
            metadata={
                    "help": (
                            "For debugging purposes or quicker training, truncate the number of evaluation examples "
                            "to this "
                            "value if set."
                    )
                    },
            )

    def __post_init__(self):
        if self.dataset_name is None and self.train_file is None and self.validation_file is None:
            raise ValueError("Need either a dataset name or a training/validation file.")
        else:
            if self.train_file is not None:
                extension = self.train_file.split(".")[-1]
                if extension not in ["csv", "json", "txt"]:
                    raise ValueError("`train_file` should be a csv, a json or a txt file.")
            if self.validation_file is not None:
                extension = self.validation_file.split(".")[-1]
                if extension not in ["csv", "json", "txt"]:
                    raise ValueError("`validation_file` should be a csv, a json or a txt file.")


class CustomXLMPreTrainingHeads(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.predictions = RobertaLMHead(config)
        self.seq_relationship = nn.Linear(config.hidden_size, 3)

    def forward(self, sequence_output, pooled_output):
        prediction_scores = self.predictions(sequence_output)
        seq_relationship_score = self.seq_relationship(pooled_output)
        return prediction_scores, seq_relationship_score


class RobertaForPretraining(RobertaPreTrainedModel):
    _keys_to_ignore_on_load_missing = [r"position_ids", r"lm_drp_head.decoder.bias"]
    _keys_to_ignore_on_load_unexpected = [r"pooler"]

    def __init__(self, config):
        super().__init__(config)

        if config.is_decoder:
            logger.warning(
                    "If you want to use `RobertaForMaskedLM` make sure `config.is_decoder=False` for "
                    "bi-directional self-attention."
                    )

        self.roberta = RobertaModel(config)
        self.lm_drp_head = CustomXLMPreTrainingHeads(config)

        self.init_weights()

    def get_output_embeddings(self):
        return self.lm_drp_head.predictions.decoder

    def set_output_embeddings(self, new_embeddings):
        self.lm_drp_head.predictions.decoder = new_embeddings

    def forward(
            self,
            input_ids: Optional[torch.Tensor] = None,
            attention_mask: Optional[torch.Tensor] = None,
            token_type_ids: Optional[torch.Tensor] = None,
            position_ids: Optional[torch.Tensor] = None,
            head_mask: Optional[torch.Tensor] = None,
            inputs_embeds: Optional[torch.Tensor] = None,
            labels: Optional[torch.Tensor] = None,
            drp_label: Optional[torch.Tensor] = None,
            # output_attentions: Optional[bool] = None,
            # output_hidden_states: Optional[bool] = None,
            return_dict: Optional[bool] = None,
            ) -> Union[Tuple[torch.Tensor], BertForPreTrainingOutput]:
        r"""
        labels (:obj:`torch.LongTensor` of shape :obj:`(batch_size, sequence_length)`, `optional`):
            Labels for computing the masked language modeling loss. Indices should be in ``[-100, 0, ...,
            config.vocab_size]`` (see ``input_ids`` docstring) Tokens with indices set to ``-100`` are ignored
            (masked), the loss is only computed for the tokens with labels in ``[0, ..., config.vocab_size]``
        kwargs (:obj:`Dict[str, any]`, optional, defaults to `{}`):
            Used to hide legacy arguments that have been deprecated.
        """
        # return_dict = return_dict if return_dict is not None else self.config.use_return_dict

        return_dict = return_dict if return_dict is not None else self.config.use_return_dict

        outputs = self.roberta(
                input_ids,
                attention_mask=attention_mask,
                token_type_ids=token_type_ids,
                position_ids=position_ids,
                head_mask=head_mask,
                inputs_embeds=inputs_embeds,
                )

        sequence_output, pooled_output = outputs[:2]
        prediction_scores, seq_relationship_score = self.lm_drp_head(sequence_output, pooled_output)

        total_loss = None

        if labels is not None and drp_label is not None:
            loss_fct = CrossEntropyLoss()
            masked_lm_loss = loss_fct(prediction_scores.view(-1, self.config.vocab_size), labels.view(-1))
            next_sentence_loss = loss_fct(seq_relationship_score.view(-1, 3), drp_label.view(-1))
            total_loss = masked_lm_loss + next_sentence_loss

        if not return_dict:
            output = (prediction_scores, seq_relationship_score) + outputs[2:]
            return ((total_loss,) + output) if total_loss is not None else output

        return BertForPreTrainingOutput(
                loss=total_loss,
                prediction_logits=prediction_scores,
                seq_relationship_logits=seq_relationship_score,
                hidden_states=outputs.hidden_states,
                attentions=outputs.attentions,
                )


def main():
    # See all possible arguments in src/transformers/training_args.py
    # or by passing the --help flag to this script.
    # We now keep distinct sets of args, for a cleaner separation of concerns.

    parser = HfArgumentParser((ModelArguments, DataTrainingArguments, TrainingArguments))
    if len(sys.argv) == 2 and sys.argv[1].endswith(".json"):
        # If we pass only one argument to the script and it's the path to a json file,
        # let's parse it to get our arguments.
        model_args, data_args, training_args = parser.parse_json_file(json_file=os.path.abspath(sys.argv[1]))
    else:
        model_args, data_args, training_args = parser.parse_args_into_dataclasses()

    # Sending telemetry. Tracking the example usage helps us better allocate resources to maintain them. The
    # information sent is the one passed as arguments along with your Python/PyTorch versions.
    send_example_telemetry("run_mlm", model_args, data_args)

    # Setup logging
    logging.basicConfig(
            format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
            datefmt="%m/%d/%Y %H:%M:%S",
            handlers=[logging.StreamHandler(sys.stdout)],
            )

    log_level = training_args.get_process_log_level()
    logger.setLevel(log_level)
    datasets.utils.logging.set_verbosity(log_level)
    transformers.utils.logging.set_verbosity(log_level)
    transformers.utils.logging.enable_default_handler()
    transformers.utils.logging.enable_explicit_format()

    # Log on each process the small summary:
    logger.warning(
            f"Process rank: {training_args.local_rank}, device: {training_args.device}, n_gpu: {training_args.n_gpu}"
            + f"distributed training: {bool(training_args.local_rank != -1)}, 16-bits training: {training_args.fp16}"
            )
    # Set the verbosity to info of the Transformers logger (on main process only):
    logger.info(f"Training/evaluation parameters {training_args}")

    # Detecting last checkpoint.
    last_checkpoint = None
    if os.path.isdir(training_args.output_dir) and training_args.do_train and not training_args.overwrite_output_dir:
        last_checkpoint = get_last_checkpoint(training_args.output_dir)
        if last_checkpoint is None and len(os.listdir(training_args.output_dir)) > 0:
            raise ValueError(
                    f"Output directory ({training_args.output_dir}) already exists and is not empty. "
                    "Use --overwrite_output_dir to overcome."
                    )
        elif last_checkpoint is not None and training_args.resume_from_checkpoint is None:
            logger.info(
                    f"Checkpoint detected, resuming training at {last_checkpoint}. To avoid this behavior, change "
                    "the `--output_dir` or add `--overwrite_output_dir` to train from scratch."
                    )

    # Set seed before initializing model.
    set_seed(training_args.seed)

    # Get the datasets: you can either provide your own CSV/JSON/TXT training and evaluation files (see below)
    # or just provide the name of one of the public datasets available on the hub at https://huggingface.co/datasets/
    # (the dataset will be downloaded automatically from the datasets Hub
    #
    # For CSV/JSON files, this script will use the column called 'text' or the first column. You can easily tweak this
    # behavior (see below)
    #
    # In distributed training, the load_dataset function guarantee that only one local process can concurrently
    # download the dataset.
    if data_args.dataset_name is not None:
        # Downloading and loading a dataset from the hub.
        raw_datasets = load_dataset(
                data_args.dataset_name,
                data_args.dataset_config_name,
                cache_dir=model_args.cache_dir,
                use_auth_token=True if model_args.use_auth_token else None,
                )
        if "validation" not in raw_datasets.keys():
            raw_datasets["validation"] = load_dataset(
                    data_args.dataset_name,
                    data_args.dataset_config_name,
                    split=f"train[:{data_args.validation_split_percentage}%]",
                    cache_dir=model_args.cache_dir,
                    use_auth_token=True if model_args.use_auth_token else None,
                    )
            raw_datasets["train"] = load_dataset(
                    data_args.dataset_name,
                    data_args.dataset_config_name,
                    split=f"train[{data_args.validation_split_percentage}%:]",
                    cache_dir=model_args.cache_dir,
                    use_auth_token=True if model_args.use_auth_token else None,
                    )
    else:
        data_files = {}
        if data_args.train_file is not None:
            data_files["train"] = data_args.train_file
            extension = data_args.train_file.split(".")[-1]
        if data_args.validation_file is not None:
            data_files["validation"] = data_args.validation_file
            extension = data_args.validation_file.split(".")[-1]
        if extension == "txt":
            extension = "text"
        raw_datasets = load_dataset(
                extension,
                data_files=data_files,
                cache_dir=model_args.cache_dir,
                use_auth_token=True if model_args.use_auth_token else None,
                )

        # If no validation data is there, validation_split_percentage will be used to divide the dataset.
        if "validation" not in raw_datasets.keys():
            raw_datasets["validation"] = load_dataset(
                    extension,
                    data_files=data_files,
                    split=f"train[:{data_args.validation_split_percentage}%]",
                    cache_dir=model_args.cache_dir,
                    use_auth_token=True if model_args.use_auth_token else None,
                    )
            raw_datasets["train"] = load_dataset(
                    extension,
                    data_files=data_files,
                    split=f"train[{data_args.validation_split_percentage}%:]",
                    cache_dir=model_args.cache_dir,
                    use_auth_token=True if model_args.use_auth_token else None,
                    )

    # See more about loading any type of standard or custom dataset (from files, python dict, pandas DataFrame, etc) at
    # https://huggingface.co/docs/datasets/loading_datasets.html.

    # Load pretrained model and tokenizer
    #
    # Distributed training:
    # The .from_pretrained methods guarantee that only one local process can concurrently
    # download model & vocab.
    config_kwargs = {
            "cache_dir": model_args.cache_dir,
            "revision": model_args.model_revision,
            "use_auth_token": True if model_args.use_auth_token else None,
            }
    if model_args.config_name:
        config = AutoConfig.from_pretrained(model_args.config_name, **config_kwargs)
    elif model_args.model_name_or_path:
        config = AutoConfig.from_pretrained(model_args.model_name_or_path, **config_kwargs)
    else:
        config = CONFIG_MAPPING[model_args.model_type]()
        logger.warning("You are instantiating a new config instance from scratch.")
        if model_args.config_overrides is not None:
            logger.info(f"Overriding config: {model_args.config_overrides}")
            config.update_from_string(model_args.config_overrides)
            logger.info(f"New config: {config}")

    tokenizer_kwargs = {
            "cache_dir": model_args.cache_dir,
            "use_fast": model_args.use_fast_tokenizer,
            "revision": model_args.model_revision,
            "use_auth_token": True if model_args.use_auth_token else None,
            }
    if model_args.tokenizer_name:
        tokenizer = AutoTokenizer.from_pretrained(model_args.tokenizer_name, **tokenizer_kwargs)
    elif model_args.model_name_or_path:
        tokenizer = AutoTokenizer.from_pretrained(model_args.model_name_or_path, **tokenizer_kwargs)
    else:
        raise ValueError(
                "You are instantiating a new tokenizer from scratch. This is not supported by this script."
                "You can do it from another script, save it, and load it from here, using --tokenizer_name."
                )

    if model_args.model_name_or_path:
        model = RobertaForPretraining.from_pretrained(
                model_args.model_name_or_path,
                from_tf=bool(".ckpt" in model_args.model_name_or_path),
                config=config,
                cache_dir=model_args.cache_dir,
                revision=model_args.model_revision,
                use_auth_token=True if model_args.use_auth_token else None,
                ignore_mismatched_sizes=True
                )
    else:
        logger.info("Training new model from scratch")
        model = AutoModelForPreTraining.from_config(config)

    model.resize_token_embeddings(len(tokenizer))

    # Preprocessing the datasets.
    # First we tokenize all the texts.
    if training_args.do_train:
        column_names = raw_datasets["train"].column_names
    else:
        column_names = raw_datasets["validation"].column_names
    text_column_name = "text" if "text" in column_names else column_names[0]

    if data_args.max_seq_length is None:
        max_seq_length = tokenizer.model_max_length
        if max_seq_length > 1024:
            logger.warning(
                    f"The tokenizer picked seems to have a very large `model_max_length` ("
                    f"{tokenizer.model_max_length}). "
                    "Picking 1024 instead. You can change that default value by passing --max_seq_length xxx."
                    )
            max_seq_length = 1024
    else:
        if data_args.max_seq_length > tokenizer.model_max_length:
            logger.warning(
                    f"The max_seq_length passed ({data_args.max_seq_length}) is larger than the maximum length for the"
                    f"model ({tokenizer.model_max_length}). Using max_seq_length={tokenizer.model_max_length}."
                    )
        max_seq_length = min(data_args.max_seq_length, tokenizer.model_max_length)

    if data_args.line_by_line:
        # When using line_by_line, we just tokenize each nonempty line.
        padding = "max_length" if data_args.pad_to_max_length else False

        def tokenize_function(examples):
            # Remove empty lines
            examples[text_column_name] = [
                    line for line in examples[text_column_name] if len(line) > 0 and not line.isspace()
                    ]
            return tokenizer(
                    examples[text_column_name],
                    padding=padding,
                    truncation=True,
                    max_length=max_seq_length,
                    # We use this option because DataCollatorForLanguageModeling (see below) is more efficient when it
                    # receives the `special_tokens_mask`.
                    return_special_tokens_mask=True,
                    )

        with training_args.main_process_first(desc="dataset map tokenization"):
            tokenized_datasets = raw_datasets.map(
                    tokenize_function,
                    batched=True,
                    num_proc=data_args.preprocessing_num_workers,
                    remove_columns=[text_column_name],
                    load_from_cache_file=not data_args.overwrite_cache,
                    desc="Running tokenizer on dataset line_by_line",
                    )
    else:
        # Otherwise, we tokenize every text, then concatenate them together before splitting them in smaller parts.
        # We use `return_special_tokens_mask=True` because DataCollatorForLanguageModeling (see below) is more
        # efficient when it receives the `special_tokens_mask`.
        def tokenize_function(examples):
            return tokenizer(examples[text_column_name], return_special_tokens_mask=True)

        with training_args.main_process_first(desc="dataset map tokenization"):
            tokenized_datasets = raw_datasets.map(
                    tokenize_function,
                    batched=True,
                    num_proc=data_args.preprocessing_num_workers,
                    remove_columns=column_names,
                    load_from_cache_file=not data_args.overwrite_cache,
                    desc="Running tokenizer on every text in dataset",
                    )

        # Main data processing function that will concatenate all texts from our dataset and generate chunks of
        # max_seq_length.
        def group_texts(examples):
            # Concatenate all texts.
            concatenated_examples = {k: list(chain(*examples[k])) for k in examples.keys()}
            total_length = len(concatenated_examples[list(examples.keys())[0]])
            # We drop the small remainder, we could add padding if the model supported it instead of this drop, you can
            # customize this part to your needs.
            if total_length >= max_seq_length:
                total_length = (total_length // max_seq_length) * max_seq_length
            # Split by chunks of max_len.
            result = {
                    k: [t[i: i + max_seq_length] for i in range(0, total_length, max_seq_length)]
                    for k, t in concatenated_examples.items()
                    }
            return result

        # Note that with `batched=True`, this map processes 1,000 texts together, so group_texts throws away a
        # remainder for each of those groups of 1,000 texts. You can adjust that batch_size here but a higher value
        # might be slower to preprocess.
        #
        # To speed up this part, we use multiprocessing. See the documentation of the map method for more information:
        # https://huggingface.co/docs/datasets/package_reference/main_classes.html#datasets.Dataset.map

        with training_args.main_process_first(desc="grouping texts together"):
            tokenized_datasets = tokenized_datasets.map(
                    group_texts,
                    batched=True,
                    num_proc=data_args.preprocessing_num_workers,
                    load_from_cache_file=not data_args.overwrite_cache,
                    desc=f"Grouping texts in chunks of {max_seq_length}",
                    )

    if training_args.do_train:
        if "train" not in tokenized_datasets:
            raise ValueError("--do_train requires a train dataset")
        train_dataset = tokenized_datasets["train"]
        if data_args.max_train_samples is not None:
            max_train_samples = min(len(train_dataset), data_args.max_train_samples)
            train_dataset = train_dataset.select(range(max_train_samples))

    if training_args.do_eval:
        if "validation" not in tokenized_datasets:
            raise ValueError("--do_eval requires a validation dataset")
        eval_dataset = tokenized_datasets["validation"]
        if data_args.max_eval_samples is not None:
            max_eval_samples = min(len(eval_dataset), data_args.max_eval_samples)
            eval_dataset = eval_dataset.select(range(max_eval_samples))

        def preprocess_logits_for_metrics(logits, labels):
            if isinstance(logits, tuple):
                # Depending on the model and config, logits may contain extra tensors,
                # like past_key_values, but logits always come first
                logits_mlm, logits_erp = logits[0], logits[1]
            return logits_mlm.argmax(dim=-1), logits_erp.argmax(dim=-1)

        metric = load_metric("accuracy")

        def compute_metrics(eval_preds):
            (preds_mlm, preds_erp), (labels_mlm, labels_erp) = eval_preds
            # preds have the same shape as the labels, after the argmax(-1) has been calculated
            # by preprocess_logits_for_metrics

            labels_mlm = labels_mlm.reshape(-1)
            preds_mlm = preds_mlm.reshape(-1)

            labels_erp = labels_erp.reshape(-1)
            preds_erp = preds_erp.reshape(-1)

            mask = labels_mlm != -100
            labels_mlm = labels_mlm[mask]
            preds_mlm = preds_mlm[mask]

            logger.info(f"Labels MLM: {labels_mlm}")
            logger.info(f"Preds MLM: {preds_mlm}")
            logger.info(f"Labels ERP: {labels_erp}")
            logger.info(f"Preds ERP: {preds_erp}")

            eval_metric = metric.compute(predictions=preds_mlm, references=labels_mlm)
            eval_metric["accuracy_erp"] = accuracy_score(y_true=labels_erp, y_pred=preds_erp)

            return eval_metric

    # Data collator
    # This one will take care of randomly masking the tokens.
    pad_to_multiple_of_8 = data_args.line_by_line and training_args.fp16 and not data_args.pad_to_max_length
    data_collator = DataCollatorForLanguageModeling(
            tokenizer=tokenizer,
            mlm_probability=data_args.mlm_probability,
            pad_to_multiple_of=8 if pad_to_multiple_of_8 else None,
            )

    # Initialize our Trainer
    trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=train_dataset if training_args.do_train else None,
            eval_dataset=eval_dataset if training_args.do_eval else None,
            tokenizer=tokenizer,
            data_collator=data_collator,
            compute_metrics=compute_metrics if training_args.do_eval and not is_torch_tpu_available() else None,
            preprocess_logits_for_metrics=preprocess_logits_for_metrics if training_args.do_eval and not
            is_torch_tpu_available() else None,
            )

    # Training
    if training_args.do_train:
        checkpoint = None
        if training_args.resume_from_checkpoint is not None:
            checkpoint = training_args.resume_from_checkpoint
        elif last_checkpoint is not None:
            checkpoint = last_checkpoint
        train_result = trainer.train(resume_from_checkpoint=checkpoint)
        trainer.save_model()  # Saves the tokenizer too for easy upload
        metrics = train_result.metrics

        max_train_samples = (
                data_args.max_train_samples if data_args.max_train_samples is not None else len(train_dataset)
        )
        metrics["train_samples"] = min(max_train_samples, len(train_dataset))

        trainer.log_metrics("train", metrics)
        trainer.save_metrics("train", metrics)
        trainer.save_state()

    # Evaluation
    if training_args.do_eval:
        logger.info("*** Evaluate ***")

        metrics = trainer.evaluate()

        max_eval_samples = data_args.max_eval_samples if data_args.max_eval_samples is not None else len(eval_dataset)
        metrics["eval_samples"] = min(max_eval_samples, len(eval_dataset))
        try:
            perplexity = math.exp(metrics["eval_loss"])
        except OverflowError:
            perplexity = float("inf")
        metrics["perplexity"] = perplexity

        trainer.log_metrics("eval", metrics)
        trainer.save_metrics("eval", metrics)

    kwargs = {"finetuned_from": model_args.model_name_or_path, "tasks": "fill-mask-and-erp"}
    if data_args.dataset_name is not None:
        kwargs["dataset_tags"] = data_args.dataset_name
        if data_args.dataset_config_name is not None:
            kwargs["dataset_args"] = data_args.dataset_config_name
            kwargs["dataset"] = f"{data_args.dataset_name} {data_args.dataset_config_name}"
        else:
            kwargs["dataset"] = data_args.dataset_name

    if training_args.push_to_hub:
        trainer.push_to_hub(**kwargs)
    else:
        trainer.create_model_card(**kwargs)


def _mp_fn(index):
    # For xla_spawn (TPUs)
    main()


if __name__ == "__main__":
    main()
