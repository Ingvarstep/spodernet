from enum import IntEnum
from os.path import join
from spodernet.util import  get_logger_path, make_dirs_if_not_exists

import datetime

import numpy as np

class LogLevel(IntEnum):
    STATISTICAL = 0
    DEBUG = 1
    INFO = 2
    WARNING = 3
    ERROR = 4

class Logger:
    GLOBAL_LOG_LEVEL = LogLevel.INFO
    LOG_PROPABILITY = 0.05

    def __init__(self, folder_name, file_name, write_type='w'):
        folder = join(get_logger_path(), folder_name)
        path = join(folder, file_name)
        path_statistical = join(folder, 'statistical_' + file_name)
        self.path = path
        make_dirs_if_not_exists(folder)
        self.f = open(path, write_type)
        self.f_statistical = open(path_statistical, write_type)
        self.rdm = np.random.RandomState(234234)
        self.debug('Created log file at: {0} with write type: {1}'.format(path, write_type))

    def __del__(self):
        self.f.close()
        self.f_statistical.close()

    def wrap_message(self, message, log_level, *args):
        return '{0} ({2}): {1}'.format(datetime.datetime.now(), message.format(*args), log_level.name)

    def statistical(self, message, *args):
        self._log(message, LogLevel.STATISTICAL, *args)

    def debug(self, message, *args):
        self._log(message, LogLevel.DEBUG, *args)

    def info(self, message, *args):
        self._log(message, LogLevel.INFO, *args)

    def warning(self, message, *args):
        self._log(message, LogLevel.WARNING, *args)

    def error(self, message, *args):
        self._log(message, LogLevel.ERROR, *args)

    def _log_statistical(self, message, *args):
        rdm_num = self.rdm.rand()
        if rdm_num < Logger.LOG_PROPABILITY:
            message = self.wrap_message(message, LogLevel.STATISTICAL, *args)
            self.f_statistical.write(message + '\n')

    def _log(self, message, log_level=LogLevel.INFO, *args):
        if log_level >= Logger.GLOBAL_LOG_LEVEL:
            if log_level == LogLevel.STATISTICAL:
                self._log_statistical(message, *args)
            else:
                message = self.wrap_message(message, log_level, *args)
                print(message)
                self.f.write(message + '\n')


