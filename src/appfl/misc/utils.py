import torch
import os
from omegaconf import DictConfig
import logging
import random
import numpy as np
import copy
import os.path as osp
import pickle as pkl
import string


def validation(self, dataloader, metric):
    if self.loss_fn is None or dataloader is None:
        return 0.0, 0.0

    device = "cuda" if torch.cuda.is_available() else "cpu"
    validation_model = copy.deepcopy(self.model)
    validation_model.to(device)
    validation_model.eval()

    loss, tmpcnt = 0, 0
    with torch.no_grad():
        for img, target in dataloader:
            tmpcnt += 1
            img = img.to(device)
            target = target.to(device)
            output = validation_model(img)
            loss += self.loss_fn(output, target).item()
    loss = loss / tmpcnt
    accuracy = _evaluate_model_on_tests(validation_model, dataloader, metric)
    return loss, accuracy

def _evaluate_model_on_tests(model, test_dataloader, metric):
    if metric is None:
        metric = _default_metric
    model.eval()
    with torch.no_grad():
        test_dataloader_iterator = iter(test_dataloader)
        y_pred_final = []
        y_true_final = []
        for (X, y) in test_dataloader_iterator:
            if torch.cuda.is_available():
                X = X.cuda()
                y = y.cuda()
            y_pred = model(X).detach().cpu()
            y = y.detach().cpu()
            y_pred_final.append(y_pred.numpy())
            y_true_final.append(y.numpy())

        y_true_final = np.concatenate(y_true_final)
        y_pred_final = np.concatenate(y_pred_final)
        accuracy = float(metric(y_true_final, y_pred_final))
    return accuracy

def _default_metric(y_true, y_pred):
    if len(y_pred.shape) == 1:
        y_pred = np.round(y_pred)
    else:
        y_pred = y_pred.argmax(axis=1, keepdims=False)
    return 100*np.sum(y_pred==y_true)/y_pred.shape[0]

def create_custom_logger(logger, cfg: DictConfig):

    dir = cfg.output_dirname
    if os.path.isdir(dir) == False:
        os.makedirs(dir, exist_ok=True)
    output_filename = cfg.output_filename + "_server"

    file_ext = ".txt"
    filename = dir + "/%s%s" % (output_filename, file_ext)
    uniq = 1
    while os.path.exists(filename):
        filename = dir + "/%s_%d%s" % (output_filename, uniq, file_ext)
        uniq += 1

    logger.setLevel(logging.INFO)
    # Create handlers
    c_handler = logging.StreamHandler()
    f_handler = logging.FileHandler(filename)
    c_handler.setLevel(logging.INFO)
    f_handler.setLevel(logging.INFO)

    # Add handlers to the logger
    logger.addHandler(c_handler)
    logger.addHandler(f_handler)

    return logger


def client_log(dir, output_filename):

    if os.path.isdir(dir) == False:
        os.mkdir(dir)

    file_ext = ".txt"
    filename = dir + "/%s%s" % (output_filename, file_ext)
    uniq = 1
    while os.path.exists(filename):
        filename = dir + "/%s_%d%s" % (output_filename, uniq, file_ext)
        uniq += 1

    outfile = open(filename, "a")

    return outfile


def load_model(cfg: DictConfig):
    file = cfg.load_model_dirname + "/%s%s" % (cfg.load_model_filename, ".pt")
    model = torch.load(file)
    model.eval()
    return model


def save_model_iteration(t, model, cfg: DictConfig):
    dir = cfg.save_model_dirname
    if os.path.isdir(dir) == False:
        os.mkdir(dir)

    file_ext = ".pt"
    file = dir + "/%s_Round_%s%s" % (cfg.save_model_filename, t, file_ext)
    uniq = 1
    while os.path.exists(file):
        file = dir + "/%s_Round_%s_%d%s" % (cfg.save_model_filename, t, uniq, file_ext)
        uniq += 1

    torch.save(model, file)
 

def set_seed(seed=233):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def get_executable_func(func_cfg):
    if func_cfg.module != "":
        import importlib
        mdl = importlib.import_module(func_cfg.module)
        return getattr(mdl, func_cfg.call)
    elif func_cfg.source != "":
        exec(func_cfg.source, globals())
        return eval(func_cfg.call)
    
def mse_loss(pred, y):
    return torch.nn.MSELoss()(pred.float(), y.float().unsqueeze(-1))

def get_loss_func(cfg):
    if cfg.loss == "":
        return get_executable_func(cfg.get_loss)()
    elif cfg.loss == "CrossEntropy":
        return torch.nn.CrossEntropyLoss()
    elif cfg.loss == "MSE":
        return mse_loss

TORCH_EXT = ['.pt', '.pth']
PICKLE_EXT= ['.pkl']

def load_data_from_file(file_path: str, to_device=None):
    """Read data from file using the corresponding readers"""
    # Load files to memory
    file_ext = osp.splitext(osp.basename(file_path))[-1]
    if  file_ext in TORCH_EXT:
        results = torch.load(file_path, map_location=to_device)
    elif file_ext in PICKLE_EXT:
        with open(file_path, "rb") as fi:
            results = pkl.load(fi)
    else:
        raise RuntimeError("File extension %s is not supported" % file_ext)
    return results

def dump_data_to_file(obj, file_path: str):
    """Write data to file using the corresponding readers"""
    file_ext = osp.splitext(osp.basename(file_path))[-1]
    if file_ext in TORCH_EXT:
        torch.save(obj, file_path)
    elif file_ext in PICKLE_EXT:
        with open(file_path, "wb") as fo:
            pkl.dump(obj, fo)
    else:
        raise RuntimeError("File extension %s is not supported" % file_ext)
    return True

from torch.utils.data import DataLoader
def get_dataloader(cfg, dataset, mode):
    """ Create a data loader object from the dataset and config file"""
    if dataset is None:
        return None
    if len(dataset) == 0:
        return None
    assert mode in ['train', 'val', 'test']
    if mode == 'train':
        ## Configure training at client
        batch_size = cfg.train_data_batch_size
        shuffle    = cfg.train_data_shuffle
    else:
        batch_size = cfg.test_data_batch_size
        shuffle    = cfg.test_data_shuffle

    return DataLoader(
            dataset,
            batch_size  = batch_size,
            num_workers = cfg.num_workers,
            shuffle     = shuffle,
            pin_memory  = True
        )

def load_source_file(file_path):
    with open(file_path) as fi:
        source = fi.read()
    return source

def id_generator(size=6, chars=string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))
