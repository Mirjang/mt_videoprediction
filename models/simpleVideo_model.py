import torch
import torch.nn as nn
from util.image_pool import ImagePool
from .base_model import BaseModel
from . import networks
import numpy as np
import functools

from .networks import VGG16, UnetSkipConnectionBlock, ConvLSTMCell

################
###  HELPER  ###
################

INVALID_UV = -1.0


from torchvision import models
from collections import namedtuple


def gram_matrix(y):
    (b, ch, h, w) = y.size()
    features = y.view(b, ch, w * h)
    features_t = features.transpose(1, 2)
    gram = features.bmm(features_t) / (ch * h * w)
    return gram

class ConvLiftNet(nn.Module): 
    def __init__(self, nframes, image_nc=3):
        super(ConvLiftNet, self).__init__()
        self.nframes = nframes
        self.image_nc = image_nc
        #model = [nn.Conv2d(image_nc, image_nc*nframes, kernel_size=3, stride=1, bias=True, padding=1, padding_mode="mirror")]
        model = [nn.Conv3d(1, nframes, kernel_size=3, stride=1, bias=True, padding=1, padding_mode="mirror")]
        model += [nn.LeakyReLU(0.2)]
        model += [nn.Conv3d(nframes, nframes, kernel_size=3, stride=1, bias=True, padding=1, padding_mode="mirror")]
        model += [nn.LeakyReLU(0.2)]
        model += [nn.Conv3d(nframes, nframes, kernel_size=3, stride=1, bias=True, padding=1, padding_mode="mirror")]

        model += [nn.Tanh()]
        self.model = nn.Sequential(*model)

    def forward(self, x): 
        x = x * 2 - 1 #[0,1] -> [-1,1]
        N,C,H,W = x.shape 
        x = torch.unsqueeze(x, 1)#->(N,C,H,W)->(N,T=1,C,H,W)
        x = self.model(x)
        #x = torch.reshape(x, (N,self.nframes,C,H,W))
        x = (x+1) / 2.0 #[-1,1] -> [0,1] for vis 
        return x


class FwdConvNet(nn.Module):
    def __init__(self, nframes, image_nc=3):
        super(FwdConvNet, self).__init__()
        self.nframes = nframes
        self.image_nc = image_nc
        #model = [nn.Conv2d(image_nc, image_nc*nframes, kernel_size=3, stride=1, bias=True, padding=1, padding_mode="mirror")]
        self.model = ConvLSTMCell()
        model = [nn.Conv2d(image_nc, 8, kernel_size=3, stride=1, bias=True, padding=1, padding_mode="mirror")]
        model += [nn.LeakyReLU(0.2)]
        model += [nn.Conv2d(8, image_nc, kernel_size=3, stride=1, bias=True, padding=1, padding_mode="mirror")]
        model += [nn.Tanh()]
        self.model = nn.Sequential(*model)
        
    def forward(self, x): 
        x = x * 2 - 1 #[0,1] -> [-1,1]
        N,C,H,W = x.shape 
        out = torch.zeros((N,self.nframes,C,H,W), device = x.device)
        out[:,0] = x
        for i in range(1,self.nframes):

            x = self.model(x)
            out[:,i] = x
        #x = torch.reshape(x, (N,self.nframes,C,H,W))
        out = (out+1) / 2.0 #[-1,1] -> [0,1] for vis 
        return out

class LSTMGeneratorNet(nn.Module): 
    def __init__(self, nframes, image_nc=3, hidden_dims = 1):
        super(LSTMGeneratorNet, self).__init__()
        self.nframes = nframes
        self.image_nc = image_nc
        self.hidden_dims = hidden_dims

        self.lstm = ConvLSTMCell((640,360),image_nc, hidden_dims, (3,3), True)
        decoder = [nn.Conv2d(hidden_dims, image_nc, kernel_size=3, stride=1, bias=True, padding=1, padding_mode="mirror")]
        decoder += [nn.Tanh()]
        self.decoder = nn.Sequential(*decoder)

    def forward(self, x): 
        x = x * 2 - 1 #[0,1] -> [-1,1]
        N,C,H,W = x.shape 
        out = torch.zeros((N,self.nframes,C,H,W), device = x.device)
        out[:,0] = x

        h = torch.zeros((N,self.hidden_dims,H,W)).to(x.device)
        c = torch.zeros((N,self.hidden_dims,H,W)).to(x.device)

        for i in range(1,self.nframes):
            h, c = self.lstm(x, (h,c))
            out[:,i] = self.decoder(h)
        #x = torch.reshape(x, (N,self.nframes,C,H,W))
        out = (out+1) / 2.0 #[-1,1] -> [0,1] for vis 
        return out

class LSTMEncoderDecoderNet(nn.Module): 
    def __init__(self, nframes, image_nc=3, hidden_dims = 16):
        super(LSTMEncoderDecoderNet, self).__init__()
        self.nframes = nframes
        self.image_nc = image_nc
        self.hidden_dims = hidden_dims  

        encoder = []

        encoder += [nn.Conv2d(image_nc, 8, kernel_size=3, stride=1, dilation=1, bias=True, padding=1, padding_mode="mirror")]
        encoder += [nn.LeakyReLU(0.2)]
        encoder += [nn.AvgPool2d((2,2), stride = 2)]
        encoder += [nn.Conv2d(8, hidden_dims, kernel_size=3, stride=1, dilation=1, bias=True, padding=1, padding_mode="mirror")]
        encoder += [nn.BatchNorm2d(hidden_dims)]
        encoder += [nn.LeakyReLU(0.2)]
        encoder += [nn.AvgPool2d((2,2), stride = 2)]

        self.encoder = nn.Sequential(*encoder)

        self.lstm = ConvLSTMCell((640,360), hidden_dims, hidden_dims, (3,3), True)
        decoder = []
        decoder += [nn.Upsample(scale_factor=2)]
        decoder += [nn.Conv2d(hidden_dims, 4, kernel_size=3, stride=1, bias=True, padding=1, padding_mode="mirror")]
        decoder += [nn.LeakyReLU(0.2)]
        decoder += [nn.Upsample(scale_factor=2)]
        #decoder += [nn.ConvTranspose2d(hidden_dims, 8, kernel_size=3, stride=1, bias=True)]
        decoder += [nn.Conv2d(4, image_nc, kernel_size=3, stride=1, bias=True, padding=1, padding_mode="mirror")]
        decoder += [nn.Tanh()]
        self.decoder = nn.Sequential(*decoder)

    def forward(self, x): 
        x = x * 2 - 1 #[0,1] -> [-1,1]
        N,C,H,W = x.shape 
        out = torch.zeros((N,self.nframes,C,H,W), device = x.device)
        out[:,0] = x


        x = self.encoder(x)
        N,C,H,W = x.shape 

        # h = torch.zeros((N,self.hidden_dims,H,W)).to(x.device)
        # c = torch.zeros((N,self.hidden_dims,H,W)).to(x.device)
        #h,c = x,x

        h = torch.rand((N,self.hidden_dims,H,W)).to(x.device) *2 - 1
        c = torch.rand((N,self.hidden_dims,H,W)).to(x.device) *2 - 1


        for i in range(1,self.nframes):
            h, c = self.lstm(x, (h,c))
            out[:,i] = self.decoder(h)
        #x = torch.reshape(x, (N,self.nframes,C,H,W))
        out = (out+1) / 2.0 #[-1,1] -> [0,1] for vis 
        return out

class SimpleVideoModel(BaseModel):
    def name(self):
        return 'SimpleVideoModel'

    @staticmethod
    def modify_commandline_options(parser, is_train=True):

        # changing the default values to match the pix2pix paper
        # (https://phillipi.github.io/pix2pix/)
        #parser.set_defaults(norm='batch', netG='unet_256')
        parser.set_defaults(norm='instance', netG='unet_256')
        #parser.set_defaults(dataset_mode='aligned')
        if is_train:
            parser.set_defaults(pool_size=0, no_lsgan=True)
            parser.add_argument('--lambda_L1', type=float, default=100.0, help='weight for L1 loss')

        return parser

    def initialize(self, opt):
        BaseModel.initialize(self, opt)
        self.isTrain = opt.isTrain
        self.num_display_frames = opt.num_display_frames
        self.nframes = int(opt.max_clip_length * opt.fps / opt.skip_frames)
        self.opt = opt
        print(self.device)  
        # specify the training losses you want to print out. The program will call base_model.get_current_losses
        self.loss_names = ['L1']

        # specify the images you want to save/display. The program will call base_model.get_current_visuals
        self.visual_names = ["predicted_video", "target_video", "lossperframe_plt"]
        self.lossperframe_plt = {"opts": {
                    'title': "Loss per frame",
                    #'legend': ["L1 loss per frame"],
                    'xlabel': 'frame',
                    'ylabel': 'loss',
                    } ,
                    "Y":np.array((1,1)), "X":np.array((1,1))
            }

        for i in range(self.num_display_frames): 
            self.visual_names += [f"frame_{i}"]

        # specify the models you want to save to the disk. The program will call base_model.save_networks and base_model.load_networks
        if self.isTrain:
            self.model_names = ['netG']
        else:  # during test time, only load Gs
            self.model_names = ['netG']

        # load/define networks

        netG = LSTMEncoderDecoderNet(self.nframes,opt.input_nc, hidden_dims=16)
        self.netG = networks.init_net(netG, opt.init_type, opt.init_gain, self.gpu_ids)

        if self.isTrain:
            # define loss functions
            self.criterionL1 = torch.nn.L1Loss()
            self.criterionL1Smooth = torch.nn.SmoothL1Loss()
            self.criterionL2 = torch.nn.MSELoss()

            # initialize optimizers
            self.optimizers = []
            #self.optimizer = torch.optim.SGD(self.netG.parameters(), opt.lr)
            self.optimizer = torch.optim.Adam(self.netG.parameters(), lr=opt.lr, betas=(opt.beta1, 0.999))
            self.optimizers.append(self.optimizer)



    def set_input(self, input):
        self.target_video = input['VIDEO'].to(self.device).permute(0,1,4,2,3).float() / 255.0 #normalize to [0,1] for vis and stuff 
        self.input = self.target_video[:,0,...]#first frame
        _, T, *_ = self.target_video.shape
        self.target_video = self.target_video[:, :min(T,self.nframes),...]

    def forward(self, frame_length = -1):
        if hasattr(self.netG, "nFrames"):
            self.netG.nFrames = frame_length if frame_length>0 else self.nframes
        video = self.netG(self.input)
        self.predicted_video = video
        
        for i in range(self.num_display_frames//2):
            setattr(self,f"frame_{i}", self.predicted_video[:,i,...] )
        for i in range(self.num_display_frames//2):
            ith_last = self.num_display_frames//2 -i +1
            setattr(self,f"frame_{i + self.num_display_frames//2}", self.predicted_video[:,-ith_last,...] )
        video = video * 256
        return video.permute(0,1,3,4,2)


    def epoch_frame_length(self, epoch): 
        increase_intervals = 10
        iter_per_interval = 20
        return max(8,min(self.nframes // increase_intervals * (epoch // iter_per_interval +1), self.nframes))


    def backward_D(self):
        # Fake
        # stop backprop to the generator by detaching fake_B
        fake_AB = self.fake_AB_pool.query(torch.cat((self.input_uv, self.fake), 1))
        pred_fake = self.netD(fake_AB.detach())
        self.loss_D_fake = self.criterionGAN(pred_fake, False)

        # Real
        real_AB = torch.cat((self.input_uv, self.target), 1)
        pred_real = self.netD(real_AB)
        self.loss_D_real = self.criterionGAN(pred_real, True)

        # Combined loss
        self.loss_D = (self.loss_D_fake + self.loss_D_real) * 0.5

        self.loss_D.backward()

    def criterionVGG(self, fake, target):
        vgg_fake = self.vgg(fake)
        vgg_target = self.vgg(target)

        content_weight = 1.0
        style_weight = 1.0

        content_loss = self.criterionL2(vgg_target.relu2_2, vgg_fake.relu2_2)

        # gram_matrix
        gram_style = [gram_matrix(y) for y in vgg_target]
        style_loss = 0.0
        for ft_y, gm_s in zip(vgg_fake, gram_style):
            gm_y = gram_matrix(ft_y)
            style_loss += self.criterionL2(gm_y, gm_s)

        total_loss = content_weight * content_loss + style_weight * style_loss
        return total_loss


    def backward_G(self, epoch):

        # First, G(A) should fake the discriminator
        fake_AB = torch.cat((self.input_uv, self.fake), 1)
        pred_fake = self.netD(fake_AB)
        #self.loss_G_GAN = self.criterionGAN(pred_fake, True) * 0.0#0.1 ##<<<<<
        self.loss_G_GAN = self.criterionGAN(pred_fake, True) * 0.01
       

        # Second, G(A) = B
        if self.opt.lossType == 'L1':
            self.loss_G_L1 =  self.criterionL1(self.fake, self.target) * self.opt.lambda_L1
        elif self.opt.lossType == 'VGG':
            self.loss_G_VGG = self.criterionVGG(self.fake, self.target) * self.opt.lambda_L1 * 0.001 # vgg loss is quite high
        else:
            self.loss_G_L2 = self.criterionL2(self.fake, self.target) * self.opt.lambda_L1

        # col tex loss
        self.loss_G_L1 += self.criterionL1(self.sampled_texture_col, self.target) * self.opt.lambda_L1

        self.loss_G = self.loss_G_GAN + self.loss_G_L1 + self.regularizerTex

        self.loss_G.backward()

    def optimize_parameters(self, epoch_iter):
        Te = self.epoch_frame_length(epoch_iter)
        self.forward(frame_length=Te)

        if epoch_iter == 20: #restart adam to clear momemtum from poor init
            self.optimizers = []
            #self.optimizer = torch.optim.SGD(self.netG.parameters(), opt.lr)
            self.optimizer = torch.optim.Adam(self.netG.parameters(), lr=self.opt.lr, betas=(self.opt.beta1, 0.999))
            self.optimizers.append(self.optimizer)

        self.optimizer.zero_grad()
        _, T,*_ = self.predicted_video.shape
        _, TT,*_ = self.target_video.shape

        T = min(T,TT,Te) # just making sure to cut target if we didnt predict all the frames and to cut prediction, if we predicted more than target (i.e. we already messed up somewhere)
        ## loss = L1(prediction - target) 
        #print(torch.min(self.target_video), torch.max(self.target_video))
        self.loss_L1 = torch.zeros([1], device = self.device)
        lpf=[]
        for i in range(1,T):
            l_i = self.criterionL1(self.predicted_video[:,i,...], self.target_video[:,i,...])
            self.loss_L1 += l_i
            lpf.append(l_i.item())
        self.loss_L1 = self.loss_L1/T
        self.lossperframe_plt["Y"] = lpf
        self.lossperframe_plt["X"] =list(range(1, len(lpf)+1))


        #self.loss_L1 = self.criterionL1(self.predicted_video[:,:T,...], self.target_video[:,:T,...])
        self.loss_L1.backward()
        self.optimizer.step()
        # if self.trainRenderer:
        #     # update Discriminator
        #     self.set_requires_grad(self.netD, True)
        #     self.optimizer_D.zero_grad()
        #     self.backward_D()
        #     self.optimizer_D.step()

        #     # update Generator
        #     self.set_requires_grad(self.netD, False)
        #     self.optimizer_G.zero_grad()


        #     self.backward_G(epoch_iter)

        #     self.optimizer_G.step()
