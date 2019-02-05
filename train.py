"""
Based on code by xternalz: https://github.com/xternalz/WideResNet-pytorch
Wide ResNet by Sergey Zagoruyko and Nikos Komodakis
"""

import argparse
import os
import shutil
import time

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.nn.parallel
import torch.backends.cudnn as cudnn
import torch.optim
import torch.utils.data
import torchvision.transforms as transforms
import torchvision.datasets as datasets
from torch.autograd import Variable

from model import WideResNet
from utils.cutout import Cutout
from tensorboard_logger import configure, log_value


parser = argparse.ArgumentParser(description="PyTorch WideResNet Training")
parser.add_argument("--dataset", default="cifar10", type=str,
                    help="dataset (cifar10 [default] or cifar100)")
parser.add_argument("--epochs", default=200, type=int,
                    help="number of total epochs to run")
parser.add_argument("--start-epoch", default=0, type=int,
                    help="manual epoch number (useful on restarts)")
parser.add_argument("-b", "--batch-size", default=128, type=int,
                    help="mini-batch size (default: 128)")
parser.add_argument("--lr", "--learning-rate", default=0.1, type=float,
                    help="initial learning rate")
parser.add_argument("--momentum", default=0.9, type=float, help="momentum")
parser.add_argument("--nesterov", default=True, type=bool, help="nesterov momentum")
parser.add_argument("--weight-decay", "--wd", default=5e-4, type=float,
                    help="weight decay (default: 5e-4)")
parser.add_argument("--print-freq", "-p", default=10, type=int,
                    help="print frequency (default: 10)")
parser.add_argument("--layers", default=28, type=int,
                    help="total number of layers (default: 28)")
parser.add_argument("--widen-factor", default=10, type=int,
                    help="widen factor (default: 10)")
parser.add_argument("--batchnorm", default=True, type=bool,
                    help="apply BatchNorm")
parser.add_argument("--fixup", default=True, type=bool,
                    help="apply Fixup")
parser.add_argument("--droprate", default=0, type=float,
                    help="dropout probability (default: 0.0)")
parser.add_argument("--cutout", default=False, type=bool,
                    help="apply cutout")
parser.add_argument("--n_holes", default=1, type=int,
                    help="number of holes to cut out from image")
parser.add_argument("--length", default=16, type=int,
                    help="length of the holes")
parser.add_argument("--no-augment", dest="augment", action="store_false",
                    help="whether to use standard augmentation (default: True)")
parser.add_argument("--resume", default="", type=str,
                    help="path to latest checkpoint (default: none)")
parser.add_argument("--name", default="WideResNet-28-10", type=str,
                    help="name of experiment")
parser.add_argument("--tensorboard",
                    help="Log progress to TensorBoard", action="store_true")
parser.set_defaults(augment=True)

best_prec1 = 0


class AverageMeter(object):
    """Computes and stores the average and current value"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count


def main():
    global args, best_prec1
    args = parser.parse_args()

    if args.tensorboard:
        configure(f"runs/{args.name}")

    normalize = transforms.Normalize(mean=[x / 255.0 for x in [125.3, 123.0, 113.9]],
                                     std=[x / 255.0 for x in [63.0, 62.1, 66.7]])
    
    if args.augment:
        transform_train = transforms.Compose([
        	transforms.ToTensor(),
        	transforms.Lambda(lambda x: F.pad(x.unsqueeze(0), (4,4,4,4), mode="reflect").squeeze()),
            transforms.ToPILImage(),
            transforms.RandomCrop(32),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            normalize,
            ])
    else:
        transform_train = transforms.Compose([
            transforms.ToTensor(),
            normalize,
            ])

    if args.cutout:
        transform_train.transforms.append(Cutout(n_holes=args.n_holes, length=args.length))

    transform_test = transforms.Compose([
        transforms.ToTensor(),
        normalize
        ])

    kwargs = {"num_workers": 1, "pin_memory": True}
    assert(args.dataset == "cifar10" or args.dataset == "cifar100")

    train_loader = torch.utils.data.DataLoader(
        datasets.__dict__[args.dataset.upper()]("../data", train=True, download=True,
        transform=transform_train), batch_size=args.batch_size, shuffle=True, **kwargs)
    val_loader = torch.utils.data.DataLoader(
        datasets.__dict__[args.dataset.upper()]("../data", train=False, transform=transform_test),
        batch_size=args.batch_size, shuffle=True, **kwargs)

    model = WideResNet(args.layers, args.dataset == "cifar10" and 10 or 100, 
                       args.widen_factor, droprate=args.droprate,
                       use_bn=args.batchnorm, use_fixup=args.fixup)

    param_num = sum([p.data.nelement() for p in model.parameters()])
    print(f"Number of model parameters: {param_num}")

    if torch.cuda.device_count() > 1:
        model = torch.nn.DataParallel(model)
    model = model.cuda()

    if args.resume:
        if os.path.isfile(args.resume):
            print(f"=> loading checkpoint {args.resume}")
            checkpoint = torch.load(args.resume)
            args.start_epoch = checkpoint["epoch"]
            best_prec1 = checkpoint["best_prec1"]
            model.load_state_dict(checkpoint["state_dict"])
            print(f"=> loaded checkpoint '{args.resume}' (epoch {checkpoint['epoch']})")
        else:
            print(f"=> no checkpoint found at {args.resume}")

    cudnn.benchmark = True
    criterion = nn.CrossEntropyLoss().cuda()
    optimizer = torch.optim.SGD(model.parameters(), args.lr,
                                momentum=args.momentum, nesterov=args.nesterov,
                                weight_decay=args.weight_decay)

    for epoch in range(args.start_epoch, args.epochs):
        adjust_learning_rate(optimizer, epoch+1)
        train(train_loader, model, criterion, optimizer, epoch)
        
        prec1 = validate(val_loader, model, criterion, epoch)
        is_best = prec1 > best_prec1
        best_prec1 = max(prec1, best_prec1)
        save_checkpoint({
            "epoch": epoch + 1,
            "state_dict": model.state_dict(),
            "best_prec1": best_prec1,
        }, is_best)

    print("Best accuracy: ", best_prec1)


def train(train_loader, model, criterion, optimizer, epoch):
    """Train for one epoch on the training set"""
    batch_time = AverageMeter()
    losses = AverageMeter()
    top1 = AverageMeter()

    model.train()

    end = time.time()
    for i, (input, target) in enumerate(train_loader):
        target = target.cuda(async=True)
        input = input.cuda()
        input_var = torch.autograd.Variable(input)
        target_var = torch.autograd.Variable(target)

        output = model(input_var)
        loss = criterion(output, target_var)

        prec1 = accuracy(output.data, target, topk=(1,))[0]
        losses.update(loss.data.item(), input.size(0))
        top1.update(prec1.item(), input.size(0))

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        batch_time.update(time.time() - end)
        end = time.time()

        if i % args.print_freq == 0:
            print("Epoch: [{0}][{1}/{2}]\t"
                  "Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t"
                  "Loss {loss.val:.4f} ({loss.avg:.4f})\t"
                  "Prec@1 {top1.val:.3f} ({top1.avg:.3f})".format(
                      epoch, i, len(train_loader), batch_time=batch_time,
                      loss=losses, top1=top1))
    
    if args.tensorboard:
        log_value("train_loss", losses.avg, epoch)
        log_value("train_acc", top1.avg, epoch)

def validate(val_loader, model, criterion, epoch):
    """Perform validation on the validation set"""
    batch_time = AverageMeter()
    losses = AverageMeter()
    top1 = AverageMeter()

    model.eval()

    end = time.time()
    for i, (input, target) in enumerate(val_loader):
        target = target.cuda(async=True)
        input = input.cuda()
        input_var = torch.autograd.Variable(input)
        target_var = torch.autograd.Variable(target)

        with torch.no_grad():
            output = model(input_var)
        loss = criterion(output, target_var)

        prec1 = accuracy(output.data, target, topk=(1,))[0]
        losses.update(loss.data.item(), input.size(0))
        top1.update(prec1.item(), input.size(0))

        batch_time.update(time.time() - end)
        end = time.time()

        if i % args.print_freq == 0:
            print("Test: [{0}/{1}]\t"
                  "Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t"
                  "Loss {loss.val:.4f} ({loss.avg:.4f})\t"
                  "Prec@1 {top1.val:.3f} ({top1.avg:.3f})".format(
                      i, len(val_loader), batch_time=batch_time, loss=losses,
                      top1=top1))

    print(" * Prec@1 {top1.avg:.3f}".format(top1=top1))

    if args.tensorboard:
        log_value("val_loss", losses.avg, epoch)
        log_value("val_acc", top1.avg, epoch)

    return top1.avg


def save_checkpoint(state, is_best, filename="checkpoint.pth.tar"):
    """Saves checkpoint to disk"""
    directory = "runs/%s/"%(args.name)

    if not os.path.exists(directory):
        os.makedirs(directory)

    filename = directory + filename
    torch.save(state, filename)

    if is_best:
        shutil.copyfile(filename, "runs/%s/"%(args.name) + "model_best.pth.tar")


def adjust_learning_rate(optimizer, epoch):
    """Sets the learning rate to the initial LR divided by 5 at 60th, 120th and 160th epochs"""
    lr = args.lr * ((0.2 ** int(epoch >= 60)) * (0.2 ** int(epoch >= 120))* (0.2 ** int(epoch >= 160)))
    
    if args.tensorboard:
        log_value("learning_rate", lr, epoch)

    for param_group in optimizer.param_groups:
        param_group["lr"] = lr


def accuracy(output, target, topk=(1,)):
    """Computes the precision@k for the specified values of k"""
    maxk = max(topk)
    batch_size = target.size(0)

    _, pred = output.topk(maxk, 1, True, True)
    pred = pred.t()
    correct = pred.eq(target.view(1, -1).expand_as(pred))

    res = []
    for k in topk:
        correct_k = correct[:k].view(-1).float().sum(0)
        res.append(correct_k.mul_(100.0 / batch_size))

    return res


if __name__ == "__main__":
    main()
