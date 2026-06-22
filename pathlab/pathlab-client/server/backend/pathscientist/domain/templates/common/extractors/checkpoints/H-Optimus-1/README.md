---
tags:
- image-feature-extraction
- timm
- pathology
- histology
- medical imaging
- self-supervised learning
- vision transformer
- foundation model
library_name: timm
license: cc-by-nc-nd-4.0
extra_gated_prompt: >-
  - This model and associated code are released under the CC-BY-NC-ND 4.0 license and may only be used for non-commercial, academic research purposes with proper attribution. 

  - Any commercial use, sale, or other monetization of the H-optimus-1 model and its derivatives, which include models trained on outputs from the H-optimus-1 model or datasets created from the H-optimus-1 model, is prohibited and requires prior approval. 

  - Please note that the primary email used to sign up for your Hugging Face account must match your institutional email to receive approval. By downloading the model, you attest that all information (affiliation, research use) is correct and up-to-date. Downloading the model requires prior registration on Hugging Face and agreeing to the terms of use. By downloading this model, you agree not to distribute, publish or reproduce a copy of the model. If another user within your organization wishes to use the H-optimus-1 model, they must register as an individual user and agree to comply with the terms of use. Users may not attempt to re-identify the deidentified data used to develop the underlying model. 

  - This model is provided “as-is” without warranties of any kind, express or implied. This model has not been reviewed, certified, or approved by any regulatory body, including but not limited to the FDA (U.S.), EMA (Europe), MHRA (UK), or other medical device authorities. Any application of this model in healthcare or biomedical settings must comply with relevant regulatory requirements and undergo independent validation. Users assume full responsibility for how they use this model and any resulting consequences. The authors, contributors, and distributors disclaim any liability for damages, direct or indirect, resulting from model use. Users are responsible for ensuring compliance with data protection regulations (e.g., GDPR, HIPAA) when using it in research that involves patient data.

  - If you are a commercial entity, please contact us at hello [at] bioptimus.com to discuss licensing options.
extra_gated_fields:
  Full name (first and last): text
  Current affiliation (no abbreviations): text
  Type of Affiliation:
    type: select
    options:
      - Academia
      - Life Sciences
      - Healthcare
      - Technology
      - Other
  Current and official institutional email (**this must match your primary email in your Hugging Face account, @gmail/@hotmail/@qq email domains will be denied**): text
  Main use-case:
    type: select
    options:
    - Models benchmarking on various tasks
    - Biomarker Discovery
    - Diagnostics
    - Pathology workflows acceleration (cell & tissue segmentation etc)
    - label: Other
      value: other
  Please add information on your intended research use: text
  I agree to all terms outlined above: checkbox
  I agree not to distribute the model, if another user within your organization wishes to use the H-Optimus-1 model, they must register as an individual user: checkbox
  I agree to use this model for non-commercial, academic purposes only: checkbox
  I am interested by receiving updates from Bioptimus: 
    type: checkbox
    optional: true
---

# Model card for H-optimus-1

<p align="center">
<img src="./logo.png" width="500" height="180" />
</p>

`H-optimus-1` foundation model for histology, developed by [Bioptimus](https://www.bioptimus.com/).

The model is a 1.1B parameter vision transformer trained with self-supervised learning on an extensive proprietary dataset
of billions of histology images sampled from over 1 million slides of more than 800,000 patients. 

`H-optimus-1` can be used to extract powerful features from histology images for various downstream applications, such as mutation prediction, survival analysis, or tissue classification/segmentation.

## How to use it to extract features.

The code below can be used to run inference. `H-optimus-1` expects images of size 224x224 that were extracted at 0.5 microns per pixel.
```python
from huggingface_hub import login
import torch
import timm 
from torchvision import transforms

# Login to the Hugging Face hub, using your user access token that can be found here:
# https://huggingface.co/settings/tokens.
login()

model = timm.create_model(
    "hf-hub:bioptimus/H-optimus-1", pretrained=True, init_values=1e-5, dynamic_img_size=False
)
model.to("cuda")
model.eval()

transform = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize(
        mean=(0.707223, 0.578729, 0.703617), 
        std=(0.211883, 0.230117, 0.177517)
    ),
])

input = torch.rand(3, 224, 224)
input = transforms.ToPILImage()(input)

# We recommend using mixed precision for faster inference.
with torch.autocast(device_type="cuda", dtype=torch.float16):
    with torch.inference_mode():
        features = model(transform(input).unsqueeze(0).to("cuda"))

assert features.shape == (1, 1536)
```

## Acknowledgments.

This project was provided with computing HPC and storage resources by GENCI at IDRIS thanks to the grant 2024-GC011015442 on the supercomputer Jean Zay's H100 partition.

## BibTeX entry and citation info.

If you find this repository useful, please consider citing our work:
```
@software{hoptimus1,
  author = {Bioptimus},
  title = {H-optimus-1},
  url = {https://huggingface.co/bioptimus/H-optimus-1},
  year = {2025},
}
```
