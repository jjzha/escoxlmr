#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @Filename:    prepare_pretraining_data.py
# @Time:        27/07/2022 11.36

import json
import logging
import os
import random
import sys
import time
from collections import defaultdict

import pyonmttok
from torch.utils.data import Dataset

logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        datefmt="%m/%d/%Y %H:%M:%S",
        level=logging.INFO
        )


class TextDatasetForEscoRelationPrediction(Dataset):
    def __init__(
            self,
            file_path: str,
            ):

        if not os.path.isfile(file_path):
            raise ValueError(f"Input file path {file_path} not found")

        directory, filename = os.path.split(file_path)

        logging.info(f"Creating features from dataset file at {directory}")

        # We create three data structures to account for the ESCO relation prediction objective
        self.documents = []
        self.linked = defaultdict(list)
        self.grouped = defaultdict(list)

        with open(file_path, encoding="utf-8") as f:
            for line in f:
                try:
                    line = json.loads(line)
                    if not line:
                        break
                except json.decoder.JSONDecodeError:
                    raise ValueError(
                            f"There were some issues with decoding json block: {line}."
                            )

                description = line[list(line.keys())[0]]

                if description:
                    key = list(line.keys())[0]
                    self.documents.append({key: description})
                    self.linked[key].append(description)  # linked via esco code (same page)
                    self.grouped[key[:2]].append(description)  # same level 2 major group

        logging.info(f"Creating examples from {len(self.documents)} documents.")
        self.examples = []
        self.create_examples_from_document()

        start = time.time()
        with open(f"{directory}/esco_features.json", "w+", encoding="utf-8") as fw:
            for example in self.examples:
                fw.write(json.dumps(example, ensure_ascii=False))
                fw.write("\n")

        logging.info(
                f"Saving features into file [took {time.time() - start:.3f} s]"
                )

    def create_examples_from_document(self):
        # Here we make the strong assumption that a combination of two ESCO descriptions is <512 tokens. From our
        # analysis it seems that the average number of tokens of one description is around 30 tokens.
        i = 0

        while i < len(self.documents):
            segment = self.documents[i]
            current_code = list(segment.keys())[0]

            sent_a = segment[current_code]
            current_rand_val = random.random()

            # random
            if current_rand_val < 0.33:
                is_random_next = True
                is_linked_next = False

                # This should rarely go for more than one iteration for large
                # corpora. However, just to be careful, we try to make sure that
                # the random document is not the same as the document
                # we're processing.
                for _ in range(10):
                    random_document_index = random.randint(0, len(self.documents) - 1)
                    if self.documents[random_document_index] != segment:
                        break

                random_document_index = random.randint(0, len(self.documents) - 1)
                random_document = self.documents[random_document_index]
                random_document = list(random_document.values())[0]
                sent_b = random_document

            # linked
            elif 0.33 <= current_rand_val < 0.66:
                is_linked_next = True
                is_random_next = False

                random_document_index = random.randint(0, len(self.linked[current_code]) - 1)
                linked_document = self.linked[current_code][random_document_index]
                sent_b = linked_document

            # grouped
            else:
                is_random_next = False
                is_linked_next = False
                random_document_index = random.randint(0, len(self.grouped[current_code[:2]]) - 1)
                grouped_document = self.grouped[current_code[:2]][random_document_index]
                sent_b = grouped_document

            # add labels for erp objective
            if is_random_next:
                label = 0
            elif is_linked_next:
                label = 1
            else:
                label = 2

            example = {
                    "data": f"<s>{sent_a}</s></s>{sent_b}</s>",  # sep token for RoBERTa
                    "drp_label": label
                    }

            self.examples.append(example)

            i += 1


def main():

    if not os.path.isfile(f"{sys.argv[1]}/processed_esco_descriptions_all.json"):
        langs = ["bg", "es", "cs", "da", "de", "et", "el", "en", "fr", "ga", "hr", "it", "lv", "lt", "hu", "mt", "nl",
                 "pl", "pt", "ro", "sk", "sl", "fi", "sv", "is", "no", "ar"]
        tokenizer = pyonmttok.Tokenizer("conservative", joiner_annotate=False)

        statistics = defaultdict(dict)
        for lang in langs:
            list_of_entities_and_descriptions = []

            cnt = 0
            cnt_desc = 0
            avg_len_descriptions = 0
            avg_len_alt_labels = 0
            avg_len_must_skills = 0
            avg_len_opt_skills = 0
            len_descriptions = []

            with open(f"resources/esco_taxonomy/esco_occupations_descriptions_{lang}.json",
                      mode="r+",
                      encoding='utf-8') as f:
                for line in f:
                    data = json.loads(line, strict=False)
                    description = data["description"].strip()
                    tokens = tokenizer(description)

                    # gather statistics
                    avg_len_descriptions += len(tokens)
                    len_descriptions.append(len(tokens))
                    avg_len_alt_labels += len(data["alt_label"] if data.get("alt_label") else [])
                    avg_len_must_skills += len(data["must_skills"] if data.get("must_skills") else [])
                    avg_len_opt_skills += len(data["opt_skills"] if data.get("opt_skills") else [])
                    cnt += 1
                    cnt_desc += 1

                    list_of_entities_and_descriptions.append({data["esco_code"]: f"{data['pref_label']} {description}"})

                    if data.get("alt_label"):
                        for alt_label in data["alt_label"]:
                            list_of_entities_and_descriptions.append({data["esco_code"]: f"{alt_label} {description}"})

                    if data.get("must_skills"):
                        for must_skill in data["must_skills"]:
                            must_skill_description = must_skill["description"].strip()
                            tokens_must_skill = tokenizer(must_skill_description)
                            avg_len_descriptions += len(tokens_must_skill)
                            list_of_entities_and_descriptions.append({data["esco_code"]: f"{must_skill['title']} "
                                                                                            f"{must_skill_description}"})
                            cnt_desc += 1

                    if data.get("opt_skills"):
                        for opt_skill in data["opt_skills"]:
                            opt_skill_description = opt_skill["description"].strip()
                            tokens_opt_skill = tokenizer(opt_skill_description)
                            avg_len_descriptions += len(tokens_opt_skill)
                            list_of_entities_and_descriptions.append({data["esco_code"]: f"{opt_skill['title']} "
                                                                                            f"{opt_skill_description}"})
                            cnt_desc += 1

                logging.info(f"current language: {lang}")
                logging.info(f"total entities: {len(list_of_entities_and_descriptions)}")
                logging.info(f"avg len descriptions: {avg_len_descriptions / cnt_desc}")
                logging.info(f"avg len must_skills: {avg_len_must_skills / cnt}")
                logging.info(f"avg len opt_skills: {avg_len_opt_skills / cnt}")

                statistics[lang] = {"instances": len(list_of_entities_and_descriptions),
                                    "len_desc": {avg_len_descriptions / cnt_desc}}

                with open(f"resources/processed_esco_descriptions_all_new.json", "a+", encoding="utf-8") as fw:
                    for item in list_of_entities_and_descriptions:
                        fw.write(json.dumps(item, ensure_ascii=False))
                        fw.write("\n")

            logging.info(statistics)

    # if not os.path.isfile(f"{sys.argv[1]}/esco_features.json"):
    TextDatasetForEscoRelationPrediction(file_path=f"{sys.argv[1]}/processed_esco_descriptions_all_new.json")
        # exit(1)

if __name__ == '__main__':
    main()
