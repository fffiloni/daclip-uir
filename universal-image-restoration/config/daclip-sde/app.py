import gradio as gr
import cv2
import argparse
import sys
import numpy as np
import torch

# Set max_split_size_mb to a suitable value, in megabytes (MB)
torch.cuda.set_per_process_memory_fraction(0.6, device=0)  # Adjust the fraction as needed

from PIL import Image
from torchvision.transforms import Compose, Resize, CenterCrop, ToTensor, Normalize, InterpolationMode

import options as option
from models import create_model

sys.path.insert(0, "../../")
import open_clip
import utils as util

# options
parser = argparse.ArgumentParser()
parser.add_argument("-opt", type=str, default='options/test.yml', help="Path to options YMAL file.")
opt = option.parse(parser.parse_args().opt, is_train=False)

opt = option.dict_to_nonedict(opt)

# load pretrained model by default
model = create_model(opt)
device = model.device

clip_model, preprocess = open_clip.create_model_from_pretrained('daclip_ViT-B-32', pretrained=opt['path']['daclip'])
clip_model = clip_model.to(device)

sde = util.IRSDE(max_sigma=opt["sde"]["max_sigma"], T=opt["sde"]["T"], schedule=opt["sde"]["schedule"], eps=opt["sde"]["eps"], device=device)
sde.set_model(model.model)

def clip_transform(np_image, resolution=224):
    pil_image = Image.fromarray((np_image * 255).astype(np.uint8))
    return Compose([
        Resize(resolution, interpolation=InterpolationMode.BICUBIC),
        CenterCrop(resolution),
        ToTensor(),
        Normalize((0.48145466, 0.4578275, 0.40821073), (0.26862954, 0.26130258, 0.27577711))])(pil_image)


def restore(image):
    torch.cuda.empty_cache()
    image = image / 255.
    img4clip = clip_transform(image).unsqueeze(0).to(device)
    with torch.no_grad(), torch.cuda.amp.autocast():
        image_context, degra_context = clip_model.encode_image(img4clip, control=True)
        image_context = image_context.float()
        degra_context = degra_context.float()

    LQ_tensor = torch.tensor(image, dtype=torch.float32).permute(2, 0, 1).unsqueeze(0)
    noisy_tensor = sde.noise_state(LQ_tensor)
    model.feed_data(noisy_tensor, LQ_tensor, text_context=degra_context, image_context=image_context)
    model.test(sde)
    visuals = model.get_current_visuals(need_GT=False)
    output = util.tensor2img(visuals["Output"].squeeze())
    torch.cuda.empty_cache()
    return output[:, :, [2, 1, 0]]

examples = ["da-clip-examples/da-clip-example-1.png", "da-clip-examples/da-clip-example-2.png", "da-clip-examples/da-clip-example-3.png"]
interface = gr.Interface(fn=restore, inputs="image", outputs="image", title="Image Restoration with DA-CLIP", examples=examples)
interface.launch()
