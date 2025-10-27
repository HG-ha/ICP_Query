# -*- coding: utf-8 -*-
import numbers
import numpy as np
import onnxruntime as ort
from PIL import Image
from load_config import config
import os
import sys

def crop(img, i, j, h, w):
    """Crop the given PIL Image.

    Args:
        img (PIL Image): Image to be cropped.
        i (int): i in (i,j) i.e coordinates of the upper left corner.
        j (int): j in (i,j) i.e coordinates of the upper left corner.
        h (int): Height of the cropped image.
        w (int): Width of the cropped image.

    Returns:
        PIL Image: Cropped image.
    """
    return img.crop((j, i, j + w, i + h))

def preprocess_input(x):
    x /= 255.0
    return x

def cvtColor(image):
    if len(np.shape(image)) == 3 and np.shape(image)[2] == 3:
        return image 
    else:
        image = image.convert('RGB')
        return image 
    
def resize(img, size, interpolation=Image.BILINEAR):
    r"""Resize the input PIL Image to the given size.

    Args:
        img (PIL Image): Image to be resized.
        size (sequence or int): Desired output size. If size is a sequence like
            (h, w), the output size will be matched to this. If size is an int,
            the smaller edge of the image will be matched to this number maintaing
            the aspect ratio. i.e, if height > width, then image will be rescaled to
            :math:`\left(\text{size} \times \frac{\text{height}}{\text{width}}, \text{size}\right)`
        interpolation (int, optional): Desired interpolation. Default is
            ``PIL.Image.BILINEAR``

    Returns:
        PIL Image: Resized image.
    """
    if isinstance(size, int):
        w, h = img.size
        if (w <= h and w == size) or (h <= w and h == size):
            return img
        if w < h:
            ow = size
            oh = int(size * h / w)
            return img.resize((ow, oh), interpolation)
        else:
            oh = size
            ow = int(size * w / h)
            return img.resize((ow, oh), interpolation)
    else:
        return img.resize(size[::-1], interpolation)
    
def center_crop(img, output_size):
    if isinstance(output_size, numbers.Number):
        output_size = (int(output_size), int(output_size))
    w, h = img.size
    th, tw = output_size
    i = int(round((h - th) / 2.))
    j = int(round((w - tw) / 2.))
    return crop(img, i, j, th, tw)


def letterbox_image(image, size, letterbox_image):
    w, h = size
    iw, ih = image.size
    if letterbox_image:
        '''resize image with unchanged aspect ratio using padding'''
        scale = min(w/iw, h/ih)
        nw = int(iw*scale)
        nh = int(ih*scale)

        image = image.resize((nw,nh), Image.BICUBIC)
        new_image = Image.new('RGB', size, (128,128,128))
        new_image.paste(image, ((w-nw)//2, (h-nh)//2))
    else:
        if h == w:
            new_image = resize(image, h)
        else:
            new_image = resize(image, [h ,w])
        new_image = center_crop(new_image, [h ,w])

    return new_image


def get_resource_path(relative_path):
    """获取打包后的可执行文件中的资源文件路径"""
    if getattr(sys, 'frozen', False):  # 如果是打包后的程序
        app_path = os.path.dirname(sys.executable)
    else:
        app_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(app_path, relative_path)



class Siamese(object):

    def __init__(self):
        self.model_path = get_resource_path('model_data/isma.onnx')
        self.input_shape = [32, 32]
        providers = []
        if "CUDA" in config.captcha.device:
            providers.append("CUDAExecutionProvider")
        if "CPU" in config.captcha.device:
            providers.append("CPUExecutionProvider")
        if len(config.captcha.device) == 0 or len(providers) == 0:
            providers = ['CPUExecutionProvider']

        self.session = ort.InferenceSession(self.model_path, providers=providers)       

    def letterbox_image(self, image, size):
        image = image.convert("RGB")
        iw, ih = image.size
        w, h = size
        scale = min(w / iw, h / ih)
        nw = int(iw * scale)
        nh = int(ih * scale)

        image = image.resize((nw, nh), Image.BICUBIC)
        new_image = Image.new('RGB', size, (128, 128, 128))
        new_image.paste(image, ((w - nw) // 2, (h - nh) // 2))
        if self.input_shape[-1] == 1:
            new_image = new_image.convert("L")
        return new_image

    def detect_image(self, image_1, image_2):
        image_1 = cvtColor(image_1)
        image_2 = cvtColor(image_2)

        image_1 = letterbox_image(image_1, [self.input_shape[1], self.input_shape[0]], self.letterbox_image)
        image_2 = letterbox_image(image_2, [self.input_shape[1], self.input_shape[0]], self.letterbox_image)


        photo_1 = preprocess_input(np.array(image_1, np.float32))
        photo_2 = preprocess_input(np.array(image_2, np.float32))

        photo_1 = np.expand_dims(np.transpose(photo_1, (2, 0, 1)), axis=0).astype(np.float32)
        photo_2 = np.expand_dims(np.transpose(photo_2, (2, 0, 1)), axis=0).astype(np.float32)

        input_names = [input.name for input in self.session.get_inputs()]
        output_names = [output.name for output in self.session.get_outputs()]
        outputs = self.session.run(output_names, {input_names[0]: photo_1, input_names[1]: photo_2})
        output = outputs[0]
        similarity = output[0][0]
        return similarity