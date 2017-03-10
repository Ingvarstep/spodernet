'''Tokenizes and indexes words or character and thus converts a spoder file
into a hdf5 file.'''
from collections import Counter

from spodernet.preprocessing.vocab import Vocab
from spodernet.util import write_to_hdf

import os

import numpy as np
import nltk
import simplejson as json

SINGLE_INPUT_SINGLE_SUPPORT_CLASSIFICATION = 0
data_dir = os.path.join(os.environ['HOME'], '.data')
if not os.path.exists(data_dir):
    os.mkdir(data_dir)

def generate_label_idx_maps(label_set):
    '''Maps labels as string to an index; returns label2idx hashtable'''
    label2idx = {}
    idx2label = {}
    for i, word in enumerate(label_set):
        label2idx[word] = i
        idx2label[i] = word
    return label2idx, idx2label


def not_implemented(filetype):
    '''Checks if options are selected which are not implemented'''
    assert filetype == SINGLE_INPUT_SINGLE_SUPPORT_CLASSIFICATION, \
        'File type not supported yet.'


def tokenize_file(paths, lower_list=None, add_to_vocab_list=None,
                  filetype=SINGLE_INPUT_SINGLE_SUPPORT_CLASSIFICATION):
    '''Tokenizes the data, calcs the max length, and creates a vocab.'''

    if lower_list is None:
        lower_list = [True for p in paths]
    if add_to_vocab_list is None:
        add_to_vocab_list = [True for p in paths]

    not_implemented(filetype)
    tokenizer = nltk.tokenize.WordPunctTokenizer()
    vocab_counter = Counter()
    target2idx = {}
    idx2target = {}
    target_idx = 0
    max_length_input = 0
    max_length_support = 0
    input_datasets = []
    support_datasets = []
    target_datasets = []
    input_length_ds = []
    support_length_ds = []
    for path, lower, add_vocab in zip(paths, lower_list, add_to_vocab_list):
        print('Tokenizing file {0}'.format(path))
        inputs = []
        supports = []
        targets = []
        input_lengths = []
        support_lengths = []
        for line in open(path):
            if lower:
                line = line.lower()

            # we have comma separated files
            inp, support, target = json.loads(line)
            if filetype == SINGLE_INPUT_SINGLE_SUPPORT_CLASSIFICATION:
                # our targets are just labels
                if target not in target2idx:
                    target2idx[target] = target_idx
                    idx2target[target_idx] = target
                    target_idx += 1
                targets.append(target)

                # tokenize the sentences
                inp_tokenized = tokenizer.tokenize(inp)
                support_tokenized = tokenizer.tokenize(support)
                inputs.append(inp_tokenized)
                supports.append(support_tokenized)
                # add lengths
                input_lengths.append(len(inp_tokenized))
                support_lengths.append(len(support_tokenized))

                if len(inp_tokenized) > max_length_input:
                    max_length_input = len(inp_tokenized)

                if len(support_tokenized) > max_length_support:
                    max_length_support = len(support_tokenized)

                if add_vocab:
                    # count everything
                    vocab_counter.update(inp_tokenized)
                    vocab_counter.update(support_tokenized)
        input_datasets.append(inputs)
        support_datasets.append(supports)
        target_datasets.append(targets)
        support_length_ds.append(support_lengths)
        input_length_ds.append(input_lengths)

    vocab_path = os.path.join(os.path.dirname(paths[0]), 'vocab.p')
    vocab = Vocab(vocab_counter, vocab_path)
    vocab.idx2label = idx2target
    vocab.label2idx = target2idx
    vocab.save_to_disk()
    return [input_datasets, support_datasets, target_datasets,
            input_length_ds, support_length_ds,
            max_length_input, max_length_support,
            vocab]


def file2hdf(paths, names, lower_list=None, add_to_vocab_list=None,
             filetype=SINGLE_INPUT_SINGLE_SUPPORT_CLASSIFICATION):
    '''Converts a spoder file to hdf5 file with some preprocessing options
    Args:
        paths: Paths to the spoder files.
        names: Name bases for the output files, e.g. "train", "dev" etc.
        lower_list: A list of True/False. Will lowercase the data
        add_to_vocab_list: A list of True/False; whether to add words to vocab
        filetype: The filetype, see constants in this file
    Returns:
        List of filenames to the hdf5 files.
    '''

    write_paths = [os.path.join(os.path.dirname(path), name)
                   for path, name in zip(paths, names)]

    return_file_names = [(write_path + '_inputs.hdf5',
                          write_path + '_support.hdf5',
                          write_path + '_input_lengths.hdf5',
                          write_path + '_support_lengths.hdf5',
                          write_path + '_targets.hdf5')
                         for write_path in write_paths]

    if os.path.exists(return_file_names[0][0]):
        vocab_path = os.path.join(os.path.dirname(paths[0]), 'vocab.p')
        vocab = Vocab(Counter(), vocab_path)
        vocab.load_from_disk()
        return [return_file_names, vocab]

    ret = tokenize_file(paths, lower_list, add_to_vocab_list, filetype)
    input_sets, support_sets, target_sets, input_len_sets, support_len_sets, length_inp, length_support, vocab = ret

    for path, name, inputs, supports, input_lens, support_lens, targets in zip(paths, names,
                                            input_sets, support_sets,
                                            input_len_sets, support_len_sets, 
                                            target_sets,):
        assert len(inputs) == len(supports), ('Number of supports and inputs',
                                              'must be the same')
        assert len(inputs) == len(targets), ('Number of targets and inputs',
                                             'must be the same')

        X = np.zeros((len(inputs), length_inp), dtype=np.int32)
        S = np.zeros((len(supports), length_support), dtype=np.int32)
        T = np.zeros((len(targets),), dtype=np.int32)
        Xs = np.zeros((len(input_lens),), dtype=np.int32)
        Sups = np.zeros((len(support_lens),), dtype=np.int32)

        for row, (inp, sup, label) in enumerate(zip(inputs, supports, targets)):
            for col, word in enumerate(inp):
                idx = vocab.get_idx(word)
                X[row, col] = idx

            for col, word in enumerate(sup):
                idx = vocab.get_idx(word)
                S[row, col] = idx

            T[row] = vocab.label2idx[label]
            Xs[row] = input_lens[row]
            Sups[row] = support_lens[row]

        write_path = os.path.join(os.path.dirname(path), name)
        write_to_hdf(write_path + '_inputs.hdf5', X)
        write_to_hdf(write_path + '_support.hdf5', S)
        write_to_hdf(write_path + '_input_lengths.hdf5', Xs)
        write_to_hdf(write_path + '_support_lengths.hdf5', Sups)
        write_to_hdf(write_path + '_targets.hdf5', T)

    return [return_file_names, vocab]
