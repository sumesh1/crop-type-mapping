"""

Script for training and evaluating a model

"""
import os
import argparse
import h5py
import loss_fns
import models
import datetime
import torch
import datasets
import metrics
import visdom
import util

from constants import *
from tensorboardX import SummaryWriter
import visualize

def evaluate(preds, labels, loss_fn):
    """ Evalautes the model on the inputs using the labels and loss fn.

    Args:
        preds - (tf tensor) the inputs the model should use
        labels - (npy array / tf tensor) the labels for the inputs
        loss_fn - (function) function that takes preds and labels and outputs some metric

    Returns:
        loss - (float) the loss the model incurs
        TO BE EXPANDED
    """
    preds = model.forward(inputs)
    loss = loss_fn(labels, preds)

    accuracy = metrics.get_accuracy(preds, labels, reduction='avg')
    
    return preds, loss, accuracy

def train(model, model_name, args=None, dataloaders=None, X=None, y=None):
    """ Trains the model on the inputs
    
    Args:
        model - trainable model
        model_name - (str) name of the model
        args - (argparse object) args parsed in from main; used only for DL models
        dataloaders - (dict of dataloaders) used only for DL models
        X - (npy arr) data for non-dl models
        y - (npy arr) labels for non-dl models
    """
    if model_name in NON_DL_MODELS:
        if X is None: raise ValueError("X not provided!")
        if  y is None: raise ValueError("y nor provided!")
        model.fit(X, y)

    elif model_name in DL_MODELS:
        if dataloaders is None: raise ValueError("DATA GENERATOR IS NONE")
        if args is None: raise ValueError("Args is NONE")

        # set up information lists for visdom    
        # TODO: Add args to visdom envs default name
        vis_data = {'train_loss': [], 'val_loss': [], 'train_acc': [], 'val_acc': []}
        n_row = NROW
        if not args.env_name:
            env_name = "{}".format(args.model_name)
        else:
            env_name = args.env_name
        vis = visdom.Visdom(port=8097, env=env_name)

        loss_fn = loss_fns.get_loss_fn(args.model_name)
        optimizer = loss_fns.get_optimizer(model.parameters(), args.optimizer, args.lr, args.momentum, args.lrdecay)
        
        for i in range(args.epochs):
            for split in ['train', 'val']:
                dl = dataloaders[split]
                batch_num = 0
                # TODO: Currently hardcoded to use padded inputs for an RNN model
                #       consider generalizing somehow so the training script can be
                #       more generic
                for inputs, targets in dl:
                    with torch.set_grad_enabled(True):
                        inputs.to(args.device)
                        targets.to(args.device)
                        
                        preds, loss, accuracy = evaluate(model, inputs, targets, loss_fn)

                        if split == 'train':
                            vis_data['train_loss'].append(loss.data)
                            vis_data['train_acc'].append(accuracy) 
                            optimizer.zero_grad()
                            loss.backward()
                            optimizer.step()
                        
                        elif split == 'val':
                            vis_data['val_loss'].append(loss.data)
                            vis_data['val_acc'].append(accuracy)

                    batch_num += 1

                    if split == 'train':
                        # For each epoch, update in visdom
                        vis.line(Y=np.array(vis_data['train_loss']), 
                	         X=np.array(range(len(vis_data['train_loss']))), 
			         win='Train Loss',
			         opts={'legend': ['train_loss'], 
				       'markers': False,
				       'title': 'Train loss curve',
				       'xlabel': 'Batch number',
				       'ylabel': 'Loss'})
                        
                        vis.line(Y=np.array(vis_data['train_acc']), 
                	         X=np.array(range(len(vis_data['train_acc']))), 
			         win='Train Accuracy',
			         opts={'legend': ['train_acc'], 
				       'markers': False,
				       'title': 'Training Accuracy',
				       'xlabel': 'Batch number',
				       'ylabel': 'Accuracy'})
                    else:
                        vis.line(Y=np.array(vis_data['val_loss']), 
			         X=np.array(range(len(vis_data['val_loss']))), 
			         win='Val Loss',
                                 opts={'legend': ['val_loss'], 
				       'markers': False,
				       'title': 'Validation loss curve',
				       'xlabel': 'Batch number',
                                       'ylabel': 'Loss'})
                        
                        vis.line(Y=np.array(vis_data['val_acc']), 
                	         X=np.array(range(len(vis_data['val_acc']))), 
			         win='Val Accuracy',
			         opts={'legend': ['val_acc'], 
				       'markers': False,
				       'title': 'Validation Accuracy',
				       'xlabel': 'Batch number',
				       'ylabel': 'Accuracy'})

		    # Create and show mask for labeled areas
                    label_mask = np.sum(targets.numpy(), axis=1)
                    label_mask = np.expand_dims(label_mask, axis=1)
                    vis.images(label_mask,
				nrow=n_row,
				win='Label Masks',
				opts={'title': 'Label Masks'})

	            # Show targets (labels)
                    disp_targets = np.concatenate((np.zeros_like(label_mask), targets.numpy()), axis=1)
                    disp_targets = np.argmax(disp_targets, axis=1) 
                    disp_targets = np.expand_dims(disp_targets, axis=1)
                    disp_targets = visualize.visualize_rgb(disp_targets, args.num_classes)
                    vis.images(disp_targets,
				nrow=n_row,
				win='Target Images',
				opts={'title': 'Target Images'})

		    # Show predictions, masked with label mask
                    disp_preds = np.argmax(preds.detach().cpu().numpy(), axis=1)
                    disp_preds = np.expand_dims(disp_preds, axis=1)
                    disp_preds = visualize.visualize_rgb(disp_preds, args.num_classes) 
                    disp_preds_w_mask = disp_preds * label_mask
                    vis.images(disp_preds,
				nrow=n_row,
				win='Predicted Images',
				opts={'title': 'Predicted Images'})
                    vis.images(disp_preds_w_mask,
				nrow=n_row,
				win='Predicted Images with Label Mask',
				opts={'title': 'Predicted Images with Label Mask'})

    else:
        raise ValueError(f"Unsupported model name: {model_name}")

    return model

if __name__ == "__main__":
    # parse args
    parser = util.get_train_parser()

    args = parser.parse_args()

    # load in data generator
    dataloaders = datasets.get_dataloaders(args.grid_dir, args.country, args.dataset, args)
    
    # load in model
    model = models.get_model(**vars(args))
    if args.model_name in DL_MODELS and args.device == 'cuda' and torch.cuda.is_available():
        model.to(args.device)


    # train model
    train(model, args.model_name, args, dataloaders=dataloaders)
    
    # evaluate model

    # save model
    if not os.path.exists(args.save_dir):
        os.mkdir(args.save_dir)

    if args.model_name in DL_MODELS:
        if args.name is None:
            args.name = str(datetime.datetime.now()) + "_" + args.model_name
        torch.save(model.state_dict(), os.path.join(args.save_dir, args.name))
        print("MODEL SAVED")
     
    
    
