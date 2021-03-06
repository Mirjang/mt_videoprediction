import argparse
import os
from util import util
import torch
import models
import data


class BaseOptions():
    def __init__(self):
        self.initialized = False

    def initialize(self, parser):
      #  parser.add_argument('--dataroot', required=True, help='path to images (should have subfolders trainA, trainB, valA, valB, etc)')
        parser.add_argument('--dataroot',type=str, default = "../datasets", help='path to images (should have subfolders trainA, trainB, valA, valB, etc)')

        parser.add_argument('--batch_size', type=int, default=1, help='input batch size')
        parser.add_argument('--display_winsize', type=int, default=256, help='display window size for both visdom and HTML')
        parser.add_argument('--num_display_frames', type=int, default=8, help='display first n frames of predicted video')

        parser.add_argument('--input_nc', type=int, default=3, help='# of input image channels')
        parser.add_argument('--output_nc', type=int, default=3, help='# of output image channels')
        parser.add_argument('--ngf', type=int, default=64, help='# of gen filters in first conv layer')
     
        parser.add_argument('--gpu_ids', type=str, default='0', help='gpu ids: e.g. 0  0,1,2, 0,2. use -1 for CPU')
        parser.add_argument('--name', type=str, default='experiment_name', help='name of the experiment. It decides where to store samples and models')
        parser.add_argument('--dataset_mode', type=str, default='video', help='chooses how datasets are loaded.')
        parser.add_argument('--model', type=str, default='simpleVideo', help='chooses which model to use.')
        parser.add_argument('--epoch', type=str, default='latest', help='which epoch to load? set to latest to use latest cached model')
        parser.add_argument('--load_iter', type=int, default='0', help='which iteration to load? if load_iter > 0, the code will load models by iter_[load_iter]; otherwise, the code will load models by [epoch]')
        parser.add_argument('--num_threads', default=6, type=int, help='# threads for loading data')
        parser.add_argument('--checkpoints_dir', type=str, default='../checkpoints', help='models are saved here')
        parser.add_argument('--norm', type=str, default='instance', help='instance normalization or batch normalization')
        parser.add_argument('--serial_batches', action='store_true', help='if true, takes images in order to make batches, otherwise takes them randomly')
        parser.add_argument('--max_dataset_size', type=int, default=float("inf"), help='Maximum number of samples allowed per dataset. If the dataset directory contains more than max_dataset_size, only a subset is loaded.')
        parser.add_argument('--resize_or_crop', type=str, default='resize_and_crop', help='scaling and cropping of images at load time [resize_and_crop|crop|scale_width|scale_width_and_crop|none]')
        parser.add_argument('--init_type', type=str, default='none', help='network initialization [normal|xavier|kaiming|orthogonal]')
        parser.add_argument('--init_gain', type=float, default=0.02, help='scaling factor for normal, xavier and orthogonal.')
        parser.add_argument('--verbose', action='store_true', help='if specified, print more debugging information')
        parser.add_argument('--suffix', default='', type=str, help='customized suffix: opt.name = opt.name + suffix: e.g., {model}_{netG}_size{loadSize}')
        parser.add_argument('--lossType', type=str, default='L1', help='loss type for the final output')

        parser.add_argument('--skip_frames', type=int, default=1, help='only use every n frames')

        parser.add_argument('--fps', type=int, default=30, help='video fps')
        parser.add_argument('--clips_file', type=str, default="info.csv", help='csv file containing dataset details')
        parser.add_argument('--max_clip_length', type=float, default=2.0, help='max length of video clip in seconds')
        parser.add_argument('--max_per_frame_losses', type=int, default=10, help='display last n per frame losses')

        parser.add_argument('--train_mode', type=str, default="frame", help='train nn to only predict next frame given current frame (default: predict entire vid from single frame')

        parser.add_argument('--sanity_check', action='store_true', help='perform sanity check before running model')
        parser.add_argument('--reparse_data', action='store_true', help='reparse data set when applicable (e.g for new clip length)')
        parser.add_argument('--resolution', type=int, default=64, help='spatial resolution')
        parser.add_argument('--unroll_frames', type=int, default=1, help='compute N frames per GRU unroll')

        parser.add_argument('--generator', type=str, default="dvdgansimple", help='generator type: dvdgansimple|dvdgan|trajgru|lhc')
        parser.add_argument('--parallell_batch_size', type=int, default=None, help='number of samples processed in parallell, must be <= batch_size')
        parser.add_argument('--use_segmentation', action='store_true', help='Use DeepLab V3 (cocostuff) precomputed semantic segmentation as additional input')
        parser.add_argument('--num_segmentation_classes',  type=int, default=1, help='number of classes if sem seg is used')
        parser.add_argument('--motion_seg_eps',  type=float, default=15, help='theshold for detecing motion via diff frames (images are in (0,256)')

        parser.add_argument('--no_augmentation', action='store_true', help='disable augmentation')
        parser.add_argument('--no_wgan', action='store_true', help='use classic gan')
        parser.add_argument('--no_bn', action='store_true', help='disable batchnorm')
        parser.add_argument('--no_noise', action='store_true', help='disable noise input')
        parser.add_argument('--no_dt_prepool', action='store_true', help='disable avg pool to dt input')

        parser.add_argument('--conditional', action='store_true', help='condition Ds on input frame')
        parser.add_argument('--ch_g', type=int, default=None, help='gen. channel multiplier')
        parser.add_argument('--ch_ds', type=int, default=None, help='ds. channel multiplier')
        parser.add_argument('--ch_dt', type=int, default=None, help='dt. channel multiplier')
        parser.add_argument('--gru_layers', type=int, default=1, help='number of gru cells per GRU')
        parser.add_argument('--max_fp', type=int, default=5, help='max. levels for dvdgan-FP')
        parser.add_argument('--start_fp', type=int, default=3, help='lowest level has 2eK resolution(default=3)')

        parser.add_argument('--up_blocks_per_rnn', type=int, default=1, help='go up K resolutions before rnn')

        parser.add_argument('--masked_update', action='store_true', help='only generate new content in masked areas')
        parser.add_argument('--validation_set', type=str, default="test", help='name of the validation set (default: test, bc. i didnt define a validation set for most datasets)')


        self.initialized = True
        return parser

    def gather_options(self):
        # initialize parser with basic options
        if not self.initialized:
            parser = argparse.ArgumentParser(
                formatter_class=argparse.ArgumentDefaultsHelpFormatter)
            parser = self.initialize(parser)

        # get the basic options
        opt, _ = parser.parse_known_args()

        # modify model-related parser options
        model_name = opt.model
        model_option_setter = models.get_option_setter(model_name)
        parser = model_option_setter(parser, self.isTrain)
        opt, _ = parser.parse_known_args()  # parse again with the new defaults

        # modify dataset-related parser options
        dataset_name = opt.dataset_mode
        dataset_option_setter = data.get_option_setter(dataset_name)
        parser = dataset_option_setter(parser, self.isTrain)

        self.parser = parser

        return parser.parse_args()

    def print_options(self, opt):
        message = ''
        message += '----------------- Options ---------------\n'
        for k, v in sorted(vars(opt).items()):
            comment = ''
            default = self.parser.get_default(k)
            if v != default:
                comment = '\t[default: %s]' % str(default)
            message += '{:>25}: {:<30}{}\n'.format(str(k), str(v), comment)
        message += '----------------- End -------------------'
        print(message)

        # save to the disk
        expr_dir = os.path.join(opt.checkpoints_dir, opt.name)
        util.mkdirs(expr_dir)
        file_name = os.path.join(expr_dir, 'opt.txt')
        with open(file_name, 'wt') as opt_file:
            opt_file.write(message)
            opt_file.write('\n')

    def parse(self):

        opt = self.gather_options()
        opt.isTrain = self.isTrain   # train or test

        # process opt.suffix
        if opt.suffix:
            suffix = ('_' + opt.suffix.format(**vars(opt))) if opt.suffix != '' else ''
            opt.name = opt.name + suffix

        self.print_options(opt)

        # set gpu ids
        if opt.gpu_ids != "xla": 

            str_ids = opt.gpu_ids.split(',')
            opt.gpu_ids = []
            for str_id in str_ids:
                id = int(str_id)
                if id >= 0:
                    opt.gpu_ids.append(id)
            if len(opt.gpu_ids) > 0:
                torch.cuda.set_device(opt.gpu_ids[0])

        self.opt = opt
        return self.opt
