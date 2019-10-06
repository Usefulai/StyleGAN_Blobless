# Copyright 2019 Stanislav Pidhorskyi
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

import os
import sys
import argparse
import logging
import torch
import torch.multiprocessing as mp
from torch import distributed


def setup(rank, world_size):
    os.environ['MASTER_ADDR'] = 'localhost'
    os.environ['MASTER_PORT'] = '12355'
    distributed.init_process_group("nccl", rank=rank, world_size=world_size)


def cleanup():
    distributed.destroy_process_group()


def _run(rank, world_size, fn, defaults, args):
    if world_size > 1:
        setup(rank, world_size)
    torch.cuda.set_device(rank)

    cfg = defaults
    cfg.merge_from_file(args.config_file)
    cfg.merge_from_list(args.opts)
    cfg.freeze()

    logger = logging.getLogger("logger")
    logger.setLevel(logging.DEBUG)

    output_dir = cfg.OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    if rank == 0:
        ch = logging.StreamHandler(stream=sys.stdout)
        ch.setLevel(logging.DEBUG)
        formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s: %(message)s")
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        fh = logging.FileHandler(os.path.join(output_dir, 'log.txt'))
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    logger.info(args)

    logger.info("Using {} GPUs".format(world_size))

    logger.info("Loaded configuration file {}".format(args.config_file))
    with open(args.config_file, "r") as cf:
        config_str = "\n" + cf.read()
        logger.info(config_str)
    logger.info("Running with config:\n{}".format(cfg))

    torch.set_default_tensor_type('torch.cuda.FloatTensor')
    device = torch.cuda.current_device()
    print("Running on ", torch.cuda.get_device_name(device))

    args.distributed = world_size > 1
    fn(cfg, logger, rank, world_size, args.distributed)


def run(fn, world_size, defaults, description='', default_config='configs/experiment.yaml'):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--config-file",
        default=default_config,
        metavar="FILE",
        help="path to config file",
        type=str,
    )
    parser.add_argument(
        "opts",
        help="Modify config options using the command-line",
        default=None,
        nargs=argparse.REMAINDER,
    )

    import multiprocessing
    cpu_count = multiprocessing.cpu_count()
    gpu_count = torch.cuda.device_count()
    os.environ["OMP_NUM_THREADS"] = str(max(1, int(cpu_count / gpu_count)))
    del multiprocessing

    args = parser.parse_args()

    try:
        if world_size > 1:
            mp.spawn(_run,
                     args=(world_size, fn, defaults, args),
                     nprocs=world_size,
                     join=True)
        else:
            _run(0, world_size, fn, defaults, args)
    finally:
        if world_size > 1:
            cleanup()