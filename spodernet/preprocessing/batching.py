from torch.autograd import Variable
from os.path import join
from Queue import Queue
from threading import Thread

import time
import datetime
import numpy as np
import torch
import cPickle as pickle

from spodernet.util import get_data_path, hdf2numpy

class Batcher(object):
    '''Takes data and creates batches over which one can iterate.'''

    def __init__(self, datasets, batch_size=128, transfer_to_gpu=False,
            num_print_thresholds=100, len_indices=None, data_indices=None, min_bin_count=10240):
        self.datasets = datasets
        self.batch_size = batch_size
        self.n = datasets[0].shape[0]
        self.idx = 0
        self.min_bin_count = min_bin_count
        self.batch_count = int(self.n/batch_size)
        self.transfer_to_gpu=transfer_to_gpu

        self.print_thresholds = np.int32((int(self.n/batch_size)) *
                np.arange(num_print_thresholds)/float(num_print_thresholds))
        self.threshold_time = np.zeros(num_print_thresholds)

        self.t0 = time.time()
        self.num_thresholds = num_print_thresholds
        self.epoch = 1
        self.hooks = []
        self.len_indices = len_indices
        self.data_indices = data_indices
        if len_indices != None:
            self.get_indices_for_bins()

    def get_indices_for_bins(self):
        idx_bin = []
        min_count = self.min_bin_count
        prev_indices = None
        for ds_idx in self.len_indices:
            if prev_indices != None:
                indices = []
                for idx in prev_indices:
                   subset = self.datasets[ds_idx][idx]
                   indices2, lens2 = self.make_bins(subset, min_bin_count=min_count)
                   for idx2 in indices2:
                       indices.append(idx[idx2])
            else:
                indices, lens = self.make_bins(self.datasets[ds_idx])

            prev_indices = indices
            min_count /= 10.0

        total_count_indices = 0.0
        fractions = []
        for idx in indices:
            total_count_indices += len(idx)
        for idx in indices:
            fractions.append(len(idx)/total_count_indices)

        max_lengths_level1 = []
        for idx in indices:
            max_lengths_level2 = []
            for ds_idx in self.len_indices:
                max_lengths_level2.append(np.max(self.datasets[ds_idx][idx]))
            max_lengths_level1.append(max_lengths_level2)

        self.indices = indices
        self.indices_fractions = np.array(fractions)
        self.max_lengths = max_lengths_level1


    def make_bins(self, x1, max_distance=5, discard_max_fraction=0.10, discard_threshold=0.01, min_bin_count=10240):
        for i in range(8, 100):
            counts, bin_borders = np.histogram(x1, bins=i)
            distance = bin_borders[1] - bin_borders[0]
            if distance > max_distance: continue
            counts = np.float32(counts)
            fractions = counts/np.sum(counts)
            idx = (fractions < discard_threshold) * (counts > min_bin_count)
            discard_fraction = np.sum(counts*idx)/ np.sum(counts)
            if discard_fraction > discard_max_fraction: continue
            bin_count = i


        counts, bin_borders = np.histogram(x1, bins=bin_count)
        fractions = counts/np.sum(counts)
        idx = (fractions < discard_threshold) * (counts > min_bin_count)
        bins_start = bin_borders[:-1][idx]
        bins_end = bin_borders[1:][idx]
        indices = []
        lens = []
        for start, end in zip(bins_start, bins_end):
            idx = np.where((x1 >= start) * (x1 <= end))[0]
            indices.append(idx)
            lens.append(x1[idx])
        return indices, lens

    def add_hook(self, hook):
        self.hooks.append(hook)

    def init_datasets(self, datasets, transfer_to_gpu):
        for ds in datasets:
            dtype = ds.dtype
            if dtype == np.int32 or dtype == np.int64:
                ds_torch = torch.LongTensor(np.int64(ds))
            elif dtype == np.float32 or dtype == np.float64:
                ds_torch = torch.FloatTensor(np.float32(ds))

            if transfer_to_gpu:
                ds_torch = ds_torch.cuda()

            self.datasets.append(ds_torch)


        # we ignore off-size batches
        self.batches = int(self.n / self.batch_size)

    def shuffle(self, seed=2343):
        rdm = np.random.RandomState(seed)
        idx = np.arange(self.n)
        rdm.shuffle(idx)
        for ds in self.datasets:
            ds = ds[idx]

    def __iter__(self):
        return self

    def print_ETA(self, time_idx):
        self.threshold_time[time_idx] -=\
                np.sum(self.threshold_time[:time_idx-1])
        m = np.mean(self.threshold_time[:time_idx])
        se = np.std(
                self.threshold_time[:time_idx])/np.sqrt(np.float64(time_idx+1))
        togo = self.num_thresholds-time_idx
        lower = m-(1.96*se)
        upper = m+(1.96*se)
        lower_time = datetime.timedelta(seconds=np.round(lower*togo))
        upper_time = datetime.timedelta(seconds=np.round(upper*togo))
        mean_time = datetime.timedelta(seconds=np.round(m*togo))
        print('Epoch ETA: {2}\t95% CI: ({0}, {1})'.format(
            lower_time, upper_time, mean_time))

    def add_to_hook_histories(self, targets, argmax, loss):
        for hook in self.hooks:
            hook.add_to_history(targets, argmax, loss)


    def sample_batch_from_bins(self):
        bin_idx = np.random.choice(len(self.indices), 1, p=self.indices_fractions)[0]
        len_bin = len(self.indices[bin_idx])
        bin_selection_idx = np.random.choice(len_bin, self.batch_size, replace=False)
        batch_idx = self.indices[bin_idx][bin_selection_idx]

        return self.get_batch_from_idx(batch_idx, bin_idx)

    def get_batch_from_idx(self, batch_idx, bin_idx=None):
        batch = []
        if self.len_indices != None:
            max_l1, max_l2 = self.max_lengths[bin_idx]
            data_idx1, data_idx2 = self.data_indices

        for ds_idx, ds in enumerate(self.datasets):
            data = ds[batch_idx]
            if self.len_indices != None:
                if ds_idx == data_idx1: data = data[:,:max_l1]
                if ds_idx == data_idx2: data = data[:,:max_l2]
            dtype = ds.dtype
            if dtype == np.int32 or dtype == np.int64:
                data_torch = Variable(torch.LongTensor(np.int64(data)))
            elif dtype == np.float32 or dtype == np.float64:
                data_torch = Variable(torch.FloatTensor(np.float32(data)))

            if self.transfer_to_gpu:
                batch.append(data_torch.cuda())
            else:
                batch.append(data_torch)
        return batch

    def get_batch_by_sequence(self):
        start = self.idx*self.batch_size
        end = (self.idx+1)*self.batch_size
        batch_idx = np.arange(start,end)

        return self.get_batch_from_idx(batch_idx)

    def next(self):
        if self.idx + 1 < self.batch_count:
            if np.sum(self.idx == self.print_thresholds) > 0:
                time_idx = np.where(self.idx == self.print_thresholds)[0][0]
                self.threshold_time[time_idx] = time.time()-self.t0
                if time_idx > 1:
                    self.print_ETA(time_idx)
                    for hook in self.hooks:
                        hook.print_statistic(self.epoch)

            if self.len_indices != None:
                batch = self.sample_batch_from_bins()
            else:
                batch = self.get_batch_by_sequence()

            self.idx += 1

            return batch
        else:
            for hook in self.hooks:
                hook.print_statistic(self.epoch)
            self.idx = 0
            self.epoch += 1
            self.threshold_time *= 0
            self.t0 = time.time()
            print('EPOCH: {0}'.format(self.epoch))
            raise StopIteration()

class DataLoaderSlave(Thread):
    def __init__(self, stream_batcher, batchidx2paths, batchidx2start_end, randomize=False):
        super(DataLoaderSlave, self).__init__()
        self.daemon = True
        self.stream_batcher = stream_batcher
        self.batchidx2paths = batchidx2paths
        self.batchidx2start_end = batchidx2start_end
        self.current_data = {}

        if randomize:
            raise NotImplementedError('Randomized sampling from files not yet implemented!')


    def load_files_if_needed(self, current_paths):
        if isinstance(current_paths[0], list):
            for paths in current_paths:
                for path in paths:
                    if path not in self.current_data:
                        self.current_data[path] = hdf2numpy(path)
        else:
            for path in current_paths:
                if path not in self.current_data:
                    self.current_data[path] = hdf2numpy(path)

    def create_batch_parts(self, current_paths, start, end):
        # index loaded data for minibatch
        batch_parts = []
        if isinstance(current_paths[0], list):
            start = start[0]
            end = end[1]
            for i in range(len(current_paths[0])):
                x1 = self.current_data[current_paths[0][i]][start:]
                x2 = self.current_data[current_paths[1][i]][:end]
                if len(x1.shape) == 1:
                    x = np.hstack([x1, x2])
                else:
                    x = np.vstack([x1, x2])
                batch_parts.append(x)
        else:
            for path in current_paths:
                batch_parts.append(self.current_data[path][start:end])

        return batch_parts

    def clean_cache(self, current_paths):
        # delete unused cached data
        if isinstance(current_paths[0], list):
            current_paths = current_paths[0] + current_paths[1]


        for old_path in self.current_data.keys():
            if old_path not in current_paths:
                self.current_data.pop(old_path, None)


    def run(self):
        while True:
            batch_idx = self.stream_batcher.work.get()
            current_paths = self.batchidx2paths[batch_idx]
            start, end = self.batchidx2start_end[batch_idx]

            self.load_files_if_needed(current_paths)
            batch_parts = self.create_batch_parts(current_paths, start, end)

            # pass data to streambatcher
            self.stream_batcher.prepared_batches[batch_idx] = batch_parts
            self.stream_batcher.prepared_batchidx.put(batch_idx)

            self.clean_cache(current_paths)


class StreamBatcher(object):
    def __init__(self, pipeline_name, name, batch_size, loader_threads=8, randomize=False):
        config_path = join(get_data_path(), pipeline_name, name, 'hdf5_config.pkl')
        config = pickle.load(open(config_path))
        self.paths = config['paths']
        self.fractions = config['fractions']
        self.num_batches = np.sum(config['counts']) / batch_size
        self.batch_size = batch_size
        self.batch_idx = 0
        self.prefetch_batch_idx = 0
        self.loaders = []
        self.prepared_batches = {}
        self.prepared_batchidx = Queue()
        self.work = Queue()
        self.cached_batches = {}

        batchidx2paths, batchidx2start_end = self.create_batchidx_maps(config['counts'])

        for i in range(loader_threads):
            self.loaders.append(DataLoaderSlave(self, batchidx2paths, batchidx2start_end, randomize))
            self.loaders[-1].start()

        while self.prefetch_batch_idx < loader_threads:
            self.work.put(self.prefetch_batch_idx)
            self.prefetch_batch_idx += 1

    def create_batchidx_maps(self, counts):
        counts_cumulative = np.cumsum(counts)
        counts_cumulative_offset = np.cumsum([0] + counts)
        batchidx2paths = {}
        batchidx2start_end = {}
        paths = self.paths
        file_idx = 0
        for i in range(self.num_batches):
            start = i*self.batch_size
            end = (i+1)*self.batch_size
            if end > counts_cumulative[file_idx] and file_idx+1 < len(paths):
                start_big_batch = start - counts_cumulative_offset[file_idx]
                end_big_batch = end - counts_cumulative_offset[file_idx+1]
                batchidx2start_end[i] = ((start_big_batch, None), (None, end_big_batch))
                batchidx2paths[i] = (paths[file_idx], paths[file_idx+1])
                file_idx += 1
            else:
                start_big_batch = start - counts_cumulative_offset[file_idx]
                end_big_batch = end - counts_cumulative_offset[file_idx]
                batchidx2start_end[i] = (start_big_batch, end_big_batch)
                batchidx2paths[i] = paths[file_idx]

        return batchidx2paths, batchidx2start_end


    def get_next_batch_parts(self):
        if self.batch_idx in self.cached_batches:
            return self.cached_batches.pop(self.batch_idx)
        else:
            batch_idx = self.prepared_batchidx.get()
            if self.batch_idx == batch_idx:
                return self.prepared_batches.pop(self.batch_idx)
            else:
                self.cached_batches[batch_idx] = self.prepared_batches.pop(batch_idx)
                return self.get_next_batch_parts()

    def __iter__(self):
        return self

    def next(self):
        if self.batch_idx + 1 < self.num_batches:
            batch_parts = self.get_next_batch_parts()
            print(self.num_batches)

            self.batch_idx += 1
            self.work.put(self.prefetch_batch_idx)
            self.prefetch_batch_idx +=1
            if self.prefetch_batch_idx == self.num_batches:
                self.prefetch_batch_idx = 0
            return batch_parts
        else:
            self.batch_idx = 0
            raise StopIteration()

