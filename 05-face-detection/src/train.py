# imports
import os
import pathlib

import albumentations as A
import numpy as np

from pytorch_lightning import Trainer
from pytorch_lightning.loggers import CSVLogger
from pytorch_lightning import seed_everything
from pytorch_lightning.callbacks import ModelCheckpoint, LearningRateMonitor, EarlyStopping
from torch.utils.data import DataLoader

from src.dataset import FaceDataset
from src.model import FasterRCNNLitModule, get_fasterRCNN_resnet
from src.transformations import Clip, ComposeDouble, AlbumentationWrapper, FunctionWrapperDouble, normalize_01
from src.utils import get_filenames_of_path, collate_double

import torchvision


# hyper-parameters
params = {'BATCH_SIZE': 8,
          'OWNER': 'johschmidt42',  # set your name here, e.g. johndoe22
          'SAVE_DIR': None,  # checkpoints will be saved to cwd
          'LOG_MODEL': False,  # whether to log the model to neptune after training
          'GPU': 0,  # set to None for cpu training
          'LR': 0.001,
          'PRECISION': 32,
          'CLASSES': 2,
          'SEED': 42,
          'PROJECT': 'Heads',
          'EXPERIMENT': 'heads',
          'MAXEPOCHS': 500,
          'PATIENCE': 50,
          'BACKBONE': 'resnet34',
          'FPN': False,
          'ANCHOR_SIZE': ((32, 64, 128, 256, 512),),
          'ASPECT_RATIOS': ((0.5, 1.0, 2.0),),
          'MIN_SIZE': 1024,
          'MAX_SIZE': 1024,
          'IMG_MEAN': [0.485, 0.456, 0.406],
          'IMG_STD': [0.229, 0.224, 0.225],
          'IOU_THRESHOLD': 0.5
          }


def empty(*args, **kwargs):
    pass


def main():
    # save directory
    save_dir = os.getcwd() if not params['SAVE_DIR'] else params['SAVE_DIR']

    # root directory
    root = pathlib.Path('data/heads')

    # input and target files
    inputs = get_filenames_of_path(root / 'input')
    targets = get_filenames_of_path(root / 'target')

    inputs.sort()
    targets.sort()

    # mapping
    mapping = {
        'head': 1,
    }

    # training transformations and augmentations
    transforms_training = ComposeDouble([
        Clip(),
        AlbumentationWrapper(albumentation=A.HorizontalFlip(p=0.5)),
        AlbumentationWrapper(albumentation=A.RandomScale(p=0.5, scale_limit=0.5)),
        # AlbuWrapper(albu=A.VerticalFlip(p=0.5)),
        FunctionWrapperDouble(np.moveaxis, source=-1, destination=0),
        FunctionWrapperDouble(normalize_01)
    ])

    # validation transformations
    transforms_validation = ComposeDouble([
        Clip(),
        FunctionWrapperDouble(np.moveaxis, source=-1, destination=0),
        FunctionWrapperDouble(normalize_01)
    ])

    # test transformations
    transforms_test = ComposeDouble([
        Clip(),
        FunctionWrapperDouble(np.moveaxis, source=-1, destination=0),
        FunctionWrapperDouble(normalize_01)
    ])

    # random seed
    seed_everything(params['SEED'])

    # training validation test split
    inputs_train, inputs_valid, inputs_test = inputs[:12], inputs[12:16], inputs[16:]
    targets_train, targets_valid, targets_test = targets[:12], targets[12:16], targets[16:]

    # dataset training
    dataset_train = FaceDataset(inputs=inputs_train,
                                targets=targets_train,
                                transform=transforms_training,
                                use_cache=True,
                                convert_to_format=None,
                                mapping=mapping)

    # dataset validation
    dataset_valid = FaceDataset(inputs=inputs_valid,
                                targets=targets_valid,
                                transform=transforms_validation,
                                use_cache=True,
                                convert_to_format=None,
                                mapping=mapping)

    # dataset test
    dataset_test = FaceDataset(inputs=inputs_test,
                               targets=targets_test,
                               transform=transforms_test,
                               use_cache=True,
                               convert_to_format=None,
                               mapping=mapping)

    # dataloader training
    dataloader_train = DataLoader(dataset=dataset_train,
                                  batch_size=params['BATCH_SIZE'],
                                  shuffle=True,
                                  num_workers=0,
                                  collate_fn=collate_double)

    # dataloader validation
    dataloader_valid = DataLoader(dataset=dataset_valid,
                                  batch_size=1,
                                  shuffle=False,
                                  num_workers=0,
                                  collate_fn=collate_double)

    # dataloader test
    dataloader_test = DataLoader(dataset=dataset_test,
                                 batch_size=1,
                                 shuffle=False,
                                 num_workers=0,
                                 collate_fn=collate_double)

    # model init
    model = get_fasterRCNN_resnet(num_classes=params['CLASSES'],
                                  backbone_name=params['BACKBONE'],
                                  anchor_size=params['ANCHOR_SIZE'],
                                  aspect_ratios=params['ASPECT_RATIOS'],
                                  fpn=params['FPN'],
                                  min_size=params['MIN_SIZE'],
                                  max_size=params['MAX_SIZE'])
    #model = torchvision.models.detection.ssd300_vgg16(num_classes=params['CLASSES'], pretrained_backbone=True)

    # lightning init
    task = FasterRCNNLitModule(model=model, lr=params['LR'], iou_threshold=params['IOU_THRESHOLD'])


    # callbacks
    checkpoint_callback = ModelCheckpoint(monitor='Validation_mAP', mode='max')
    learningrate_callback = LearningRateMonitor(logging_interval='step', log_momentum=False)
    early_stopping_callback = EarlyStopping(monitor='Validation_mAP', patience=params['PATIENCE'], mode='max')

    # trainer init
    trainer = Trainer(gpus=1,
                      precision=params['PRECISION'],  # try 16 with enable_pl_optimizer=False
                      callbacks=[checkpoint_callback, learningrate_callback, early_stopping_callback],
                      default_root_dir=save_dir,  # where checkpoints are saved to
                      log_every_n_steps=1,
                      num_sanity_val_steps=0,
                      logger=[
                          CSVLogger("logs", name="my_exp_name")
                      ]
                      )
    trainer.logger.log_hyperparams = empty

    # start training
    trainer.max_epochs = params['MAXEPOCHS']
    print('trainer.fit')
    trainer.fit(task,
                train_dataloader=dataloader_train,
                val_dataloaders=dataloader_valid)

    # start testing
    trainer.test(ckpt_path='best', test_dataloaders=dataloader_test)

    print('Finished')


if __name__ == '__main__':
    main()
