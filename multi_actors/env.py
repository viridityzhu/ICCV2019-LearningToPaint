import sys
import json
import torch
import numpy as np
import argparse
import torchvision.transforms as transforms
import cv2
from DRL.ddpg import decode
from utils.util import *
from PIL import Image
from torchvision import transforms, utils
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

aug = transforms.Compose(
            [transforms.ToPILImage(),
             transforms.RandomHorizontalFlip(),
             ])

width = 128
convas_area = width * width

# img_train = []
# img_test = []
# train_num = 0
# test_num = 0

class Paint:
    def __init__(self, batch_size, max_step):
        self.batch_size = batch_size
        self.max_step = max_step
        self.action_space = (13)
        self.observation_space = (self.batch_size, width, width, 7)
        self.test = False
        self.img_train = []
        self.img_test = []
        self.train_num = 0
        self.test_num = 0
        
    def load_data(self, agent_num):
        '''
        loads data from CelebA dataset and separates it into training and testing sets.
        '''
        # global train_num, test_num
        for i in range(30000):
            img_id0 = str(i)
            img_id = '%05d' % i
            try:
                img = cv2.imread('../data/origin_img/' + img_id0 + '.jpg', cv2.IMREAD_UNCHANGED)
                msk = cv2.imread('../data/merged_mask/' + img_id + '.png', cv2.IMREAD_GRAYSCALE)
                # _, msk = cv2.threshold(msk, 127, 1, cv2.THRESH_BINARY)
                img = cv2.resize(img, (width, width))
                msk = cv2.resize(msk, (width, width))

                _, msk = cv2.threshold(msk, 127, 1, cv2.THRESH_BINARY)
                msk = msk[..., np.newaxis]
                msk1 = torch.tensor(msk)
                if agent_num:
                    msk1 = torch.logical_not(msk1).int()
                img1 = torch.tensor(img).float() * msk1
                img = img1.numpy().astype(np.uint8)
                # cv2.imwrite('./testout.png', img2.numpy())

                if i >= 2000:                
                    self.train_num += 1
                    self.img_train.append(img)
                    # msk_train.append(msk)
                else:
                    self.test_num += 1
                    self.img_test.append(img)
                    # msk_test.append(msk)
            finally:
                if (i + 1) % 500 == 0:                    
                    print('loaded {} images'.format(i + 1))
        print('finish loading data, {} training images and masks, {} testing images and masks'.format(str(self.train_num), str(self.test_num)))
        
    def pre_data(self, id, test):
        '''
        preprocesses an image by applying augmentations and transposing it.
        '''
        if test:
            img = self.img_test[id]
            # msk = msk_test[id]
        else:
            img = self.img_train[id]
            # msk = msk_train[id]
        if not test:
            img = aug(img)
            # msk = aug(msk)
        img = np.asarray(img)
        # msk = np.asarray(msk)
        # msk = msk[..., np.newaxis]
        return np.transpose(img, (2, 0, 1))
    
    def reset(self, test=False, begin_num=False):
        '''
        resets the environment to its initial state and returns the initial observation.
        '''
        self.test = test
        self.imgid = [0] * self.batch_size # a list containing the index of the current image in the batch
        self.gt = torch.zeros([self.batch_size, 3, width, width], dtype=torch.uint8).to(device)
        # self.msk = torch.zeros([self.batch_size, 1, width, width], dtype=torch.uint8).to(device)
        for i in range(self.batch_size):
            if test:
                id = (i + begin_num)  % self.test_num
            else:
                id = np.random.randint(self.train_num)
            self.imgid[i] = id
            self.gt[i] = torch.tensor(self.pre_data(id, test))
            # gt_i, msk_i = self.pre_data(id, test)
            # self.gt[i], self.msk[i] = torch.tensor(gt_i), torch.tensor(msk_i)
            # mask = self.msk[i]
            # if agent_id: # agent_id = 1: background; =0 foreground
            #     mask = torch.logical_not(self.msk[i]).int()
            # self.gt[i] = self.gt[i].float() * mask
            
        self.tot_reward = ((self.gt.float() / 255) ** 2).mean(1).mean(1).mean(1)
        self.stepnum = 0
        self.canvas = torch.zeros([self.batch_size, 3, width, width], dtype=torch.uint8).to(device)
        # self.canvases_for_actors = [torch.zeros([self.batch_size, 3, width, width], dtype=torch.uint8).to(device) for _ in range(self.ACTOR_NUM)]
        self.lastdis = self.ini_dis = self.cal_dis()
        return self.observation()
    
    def observation(self):
        # canvas B * 3 * width * width
        # gt B * 3 * width * width
        # T B * 1 * width * width
        ob = []
        T = torch.ones([self.batch_size, 1, width, width], dtype=torch.uint8) * self.stepnum
        return torch.cat((self.canvas, self.gt, T.to(device)), 1) # canvas, img, T

    def cal_trans(self, s, t):
        return (s.transpose(0, 3) * t).transpose(0, 3)
    
    def step(self, action):
        self.canvas = (decode(action, self.canvas.float() / 255) * 255).byte()
        self.stepnum += 1
        ob = self.observation()
        done = (self.stepnum == self.max_step)
        reward = self.cal_reward() # np.array([0.] * self.batch_size)
        return ob.detach(), reward, np.array([done] * self.batch_size), None

    def cal_dis(self):
        return (((self.canvas.float() - self.gt.float()) / 255) ** 2).mean(1).mean(1).mean(1)
    
    def cal_reward(self):
        dis = self.cal_dis()
        reward = (self.lastdis - dis) / (self.ini_dis + 1e-8)
        self.lastdis = dis
        return to_numpy(reward)
