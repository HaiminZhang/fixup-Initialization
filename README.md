# Wide ResNet with optional Fixup initialization

The code presents the implementation of Fixup as an option for standard Wide ResNet. When BatchNorm and Fixup are enabled simultaneously, Fixup initialization and the standard structure of the residual block are used.

Usage example:

```sh
python train.py --layers 40 --widen-factor 10 --batchnorm False --fixup True
```

# Acknowledgment
Wide ResNet by Sergey Zagoruyko and Nikos Komodakis:
https://arxiv.org/abs/1605.07146

Fixup initialization by Hongyi Zhang, Yann N. Dauphin, Tengyu Ma:
https://arxiv.org/abs/1901.09321

WRN code by xternalz:
https://github.com/xternalz/WideResNet-pytorch

Fixup implementation was originally introduced by Andy Brock:
https://github.com/ajbrock/BoilerPlate
