import torch
import torchvision
import pandas as pd
import sys
import os
import random
from data.base_dataset import BaseDataset
#expected header in info.csv: video_id,file_name,resolution,fps,start,end
class VideoDataset(BaseDataset): 

   #init when not using cyclegan framework
   # def init(self,root, clips_file ="info.csv",max_clip_length = 10.0, fps = 30, max_size = sys.maxsize, ): 
        #torchvision.set_video_backend("video_reader")

    def initialize(self, opt):
        self.root = os.path.join(opt.dataroot, opt.phase)
        #no train/test splits
        if not os.path.exists(os.path.join(opt.dataroot, opt.phase,opt.clips_file)) and os.path.exists(os.path.join(opt.dataroot, opt.clips_file)):
            self.root = opt.dataroot
        self.max_clip_length = opt.max_clip_length
        self.fps = opt.fps
        self.skip_frames = opt.skip_frames
        self.df = pd.read_csv(os.path.join(self.root,opt.clips_file))
        self.len = int(min(opt.max_dataset_size, self.df.shape[0]))

    def __len__(self): 
        return self.len

    def __getitem__(self, index):
        clip = self.df.iloc[index]
        start = random.uniform(clip['start'], clip['end'] - self.max_clip_length)
        end = min(start + self.max_clip_length, clip['end'])
        frames, _, info = torchvision.io.read_video(os.path.join(self.root,clip['file_name']), start, end, pts_unit="sec")
        if self.skip_frames>1: 
            T,C,H,W = frames.shape
            skipped = torch.zeros(T//self.skip_frames, C,H,W)
            for i in range(T//self.skip_frames):
                skipped[i] = frames[i*self.skip_frames]
            frames = skipped

        return {'VIDEO':frames}


