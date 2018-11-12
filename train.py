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
import util
import numpy as np
import matplotlib.pyplot as plt

from constants import *
from tensorboardX import SummaryWriter
import visualize

def evaluate_split(model, model_name, split_loader, device):
    total_correct = 0
    total_loss = 0
    total_pixels = 0
    loss_fn = loss_fns.get_loss_fn(model_name)
    for inputs, targets in split_loader:
        with torch.set_grad_enabled(False):
            inputs.to(device)
            targets.to(device)
            preds = model(inputs)   
            batch_loss, batch_correct, num_pixels = evaluate(preds, targets, loss_fn, reduction="sum")
            total_loss += batch_loss.item()
            total_correct += batch_correct
            total_pixels += num_pixels

    return total_loss / total_pixels, total_correct / total_pixels

def evaluate(preds, labels, loss_fn, reduction):
    """ Evalautes the model on the inputs using the labels and loss fn.

    Args:
        preds - (tf tensor) the inputs the model should use
        labels - (npy array / tf tensor) the labels for the inputs
        loss_fn - (function) function that takes preds and labels and outputs some metric

    Returns:
        loss - (float) the loss the model incurs
        TO BE EXPANDED
    """
    f1 = metrics.get_f1score(preds, labels)
    cm = metrics.get_cm(preds, labels)

    if reduction == "avg":
        loss = loss_fn(labels, preds, reduction)
        accuracy = metrics.get_accuracy(preds, labels, reduction=reduction)
        return loss, cm, f1, accuracy
    else:
        loss, _ = loss_fn(labels, preds, reduction)
        total_correct, num_pixels = metrics.get_accuracy(preds, labels, reduction=reduction)
        return loss, cm, f1, total_correct, num_pixels

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
        vis_data = {'train_loss': [], 'val_loss': [], 'train_acc': [], 'val_acc': [], 'train_f1': [], 'val_f1': []}
        vis = visualize.setup_visdom(args.env_name, args.model_name)

        loss_fn = loss_fns.get_loss_fn(args.model_name)
        optimizer = loss_fns.get_optimizer(model.parameters(), args.optimizer, args.lr, args.momentum, args.weight_decay, args.lrdecay)
        
        best_val_acc = 0

        for i in range(args.epochs):
            
            val_loss = 0
            val_acc = 0
            val_num_pixels = 0
            
            metrics = {'train_loss': [], 'train_acc': [], 'train_f1': [], 
                       'train_cm': np.zeros((args.num_classes, args.num_classes)).astype(int),
                       'val_loss': [], 'val_acc': [], 'val_f1': [],
                       'val_cm': np.zeros((args.num_classes, args.num_classes)).astype(int)}

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
                        preds = model(inputs)   
                        
                        if split == 'train':
                            loss, cm_cur, f1, accuracy = evaluate(preds, targets, loss_fn, reduction="avg")
                            
                            if cm_cur is not None:
                                metrics['train_cm'] += cm_cur
                                metrics['train_loss'].append(loss.data)
                                metrics['train_acc'].append(accuracy)
                                metrics['train_f1'].append(f1)

                                optimizer.zero_grad()
                                loss.backward()
                                optimizer.step()
                        
                        elif split == 'val':
                            loss, cm_cur, f1, total_correct, num_pixels = evaluate(preds, targets, loss_fn, reduction="sum")
                            
                            if cm_cur is not None:
                                metrics['val_cm'] += cm_cur
                                metrics['val_loss'].append(loss.item() / num_pixels)
                                metrics['val_acc'].append(total_correct / num_pixels)
                                metrics['val_f1'].append(f1)
                    
                                val_loss += loss.item()
                                val_acc += total_correct
                                val_num_pixels += num_pixels
        
                    batch_num += 1

		    # Create and show mask for labeled areas
                    label_mask = np.sum(targets.numpy(), axis=1)
                    label_mask = np.expand_dims(label_mask, axis=1)
                    visualize.vis_plot_images(vis, label_mask, 'Label Masks')

	            # Show targets (labels)
                    disp_targets = np.concatenate((np.zeros_like(label_mask), targets.numpy()), axis=1)
                    disp_targets = np.argmax(disp_targets, axis=1) 
                    disp_targets = np.expand_dims(disp_targets, axis=1)
                    disp_targets = visualize.visualize_rgb(disp_targets, args.num_classes)
                    visualize.vis_plot_images(vis, disp_targets, 'Target Images')

		    # Show predictions, masked with label mask
                    disp_preds = np.argmax(preds.detach().cpu().numpy(), axis=1) + 1
                    disp_preds = np.expand_dims(disp_preds, axis=1)
                    disp_preds = visualize.visualize_rgb(disp_preds, args.num_classes) 
                    disp_preds_w_mask = disp_preds * label_mask

                    visualize.vis_plot_images(vis, disp_preds, 'Predicted Images')    
                    visualize.vis_plot_images(vis, disp_preds_w_mask, 'Predicted Images with Label Mask')
                
                if split == 'train':
                    train_loss_batch = np.mean(metrics['train_loss'])
                    train_acc_batch = np.mean(metrics['train_acc'])
                    train_f1_batch = np.mean(metrics['train_f1'])
                    vis_data['train_loss'].append(train_loss_batch)
                    vis_data['train_acc'].append(train_acc_batch) 
                    vis_data['train_f1'].append(train_f1_batch) 

                    # For each epoch, update in visdom
                    vis.line(Y=np.array(vis_data['train_loss']), 
            	             X=np.array(range(len(vis_data['train_loss']))),
			     win='Train Loss',
			     opts={'legend': ['train_loss'], 
                                   'markers': False,
				   'title': 'Train loss curve',
				   'xlabel': 'Epoch',
				   'ylabel': 'Loss'})
                        
                    vis.line(Y=np.array(vis_data['train_acc']), 
                	     X=np.array(range(len(vis_data['train_acc']))), 
			     win='Train Accuracy',
			     opts={'legend': ['train_acc'], 
				   'markers': False,
				   'title': 'Training Accuracy',
				   'xlabel': 'Epoch',
				   'ylabel': 'Accuracy'})
               
                    vis.line(Y=np.array(vis_data['train_f1']), 
                	     X=np.array(range(len(vis_data['train_f1']))), 
			     win='Train f1-score',
			     opts={'legend': ['train_f1'], 
				   'markers': False,
				   'title': 'Training f1-score',
				   'xlabel': 'Epoch',
				   'ylabel': 'f1-score'})
                    
                    fig = util.plot_confusion_matrix(metrics['train_cm'], CM_CLASSES, 
                                                normalize=False,
                                                title='Train Confusion matrix, epoch {}'.format(i),
                                                cmap=plt.cm.Blues)
                    vis.matplot(fig, win='Train CM')

                else:
                    val_loss = val_loss / val_num_pixels
                    val_acc = val_acc / val_num_pixels
                    
                    if val_acc > best_val_acc:
                        torch.save(model.state_dict(), os.path.join(args.save_dir, args.name + "_best"))
                        best_val_acc = val_acc
                   
                    val_loss_batch = np.mean(metrics['val_loss'])
                    val_acc_batch = np.mean(metrics['val_acc'])
                    val_f1_batch = np.mean(metrics['val_f1'])
                    
                    vis_data['val_loss'].append(val_loss_batch)
                    vis_data['val_acc'].append(val_acc_batch)
                    vis_data['val_f1'].append(val_f1_batch)

                    vis.line(Y=np.array(vis_data['val_loss']), 
			     X=np.array(range(len(vis_data['val_loss']))), 
			     win='Val Loss',
                             opts={'legend': ['val_loss'], 
				   'markers': False,
				   'title': 'Validation loss curve',
			           'xlabel': 'Epoch',
                                   'ylabel': 'Loss'})
                        
                    vis.line(Y=np.array(vis_data['val_acc']), 
            	             X=np.array(range(len(vis_data['val_acc']))), 
			     win='Val Accuracy',
	                     opts={'legend': ['val_acc'], 
				   'markers': False,
			           'title': 'Validation Accuracy',
				   'xlabel': 'Batch number',
				   'ylabel': 'Accuracy'})

                    vis.line(Y=np.array(vis_data['val_f1']), 
                	     X=np.array(range(len(vis_data['val_f1']))), 
			     win='Val f1-score',
			     opts={'legend': ['val_f1'], 
				   'markers': False,
				   'title': 'Val f1-score',
				   'xlabel': 'Epoch',
				   'ylabel': 'f1-score'})
                    
                    fig = util.plot_confusion_matrix(metrics['val_cm'], CM_CLASSES, 
                                                normalize=False,
                                                title='Validation Confusion matrix, epoch {}'.format(i),
                                                cmap=plt.cm.Blues)
                    vis.matplot(fig, win='Val CM')

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

    if args.name is None:
        args.name = str(datetime.datetime.now()) + "_" + args.model_name

    # train model
    train(model, args.model_name, args, dataloaders=dataloaders)
    
    # evaluate model

    # save model
    if not os.path.exists(args.save_dir):
        os.mkdir(args.save_dir)

    if args.model_name in DL_MODELS:
        torch.save(model.state_dict(), os.path.join(args.save_dir, args.name))
        print("MODEL SAVED")
     
    
    
