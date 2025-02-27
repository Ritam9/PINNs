import scipy.io
import numpy as np
import tensorflow as tf
import time
from datetime import datetime
from pyDOE import lhs
import os
import sys
import matplotlib.pyplot as plt
from mpl_toolkits import mplot3d
from scipy.interpolate import griddata
import matplotlib.gridspec as gridspec
from mpl_toolkits.axes_grid1 import make_axes_locatable

# "." for Colab/VSCode, and ".." for GitHub
repoPath = os.path.join(".", "PINNs")
# repoPath = os.path.join("..", "PINNs")
utilsPath = os.path.join(repoPath, "Utilities")
dataPath = os.path.join(repoPath, "main", "Data")
appDataPath = os.path.join(repoPath, "appendix", "Data")

sys.path.append("utils")
from plotting import newfig, savefig, saveResultDir


def prep_data(path, N_u=None, N_f=None, N_n=None, q=None, ub=None, lb=None, noise=0.0, idx_t_0=None, idx_t_1=None,
              N_0=None, N_1=None):
    # Reading external data [t is 100x1, usol is 256x100 (solution), x is 256x1]
    data = scipy.io.loadmat(path)

    # Flatten makes [[]] into [], [:,None] makes it a column vector-1D
    #t = data['t'].flatten()[:, None]  # T x 1
    #x = data['x'].flatten()[:, None]  # N x 1

    # Flatten makes [[]] into [], [:,None] makes it a column vector-2D
    t = data['y_star'].flatten()[:, None]  # T x 1
    x = data['x_star'].flatten()[:, None]  # N x 1

    # Keeping the 2D data for the solution data (real() is maybe to make it float by default, in case of zeroes)
    #Exact_u = np.real(data['train']).T  # T x N
    Exact_u = np.real(data['T_star']).T  # T x N-2D

    # x = np.load("1d-burgers/data/burgers_x.npy")[:, None]
    # t = np.load("1d-burgers/data/burgers_t.npy")[:, None]
    # Exact_u = np.load("1d-burgers/data/burgers_u.npy").T

    if N_n != None and q != None and ub != None and lb != None and idx_t_0 != None and idx_t_1 != None:
        dt = t[idx_t_1] - t[idx_t_0]
        idx_x = np.random.choice(Exact_u.shape[1], N_n, replace=False)
        x_0 = x[idx_x, :]
        u_0 = Exact_u[idx_t_0:idx_t_0 + 1, idx_x].T
        u_0 = u_0 + noise * np.std(u_0) * np.random.randn(u_0.shape[0], u_0.shape[1])

        # Boudanry data
        x_1 = np.vstack((lb, ub))

        # Test data
        x_star = x
        u_star = Exact_u[idx_t_1, :]

        # Load IRK weights
        tmp = np.float32(np.loadtxt(os.path.join(utilsPath, "IRK_weights", "Butcher_IRK%d.txt" % (q)), ndmin=2))
        IRK_weights = np.reshape(tmp[0:q ** 2 + q], (q + 1, q))
        IRK_times = tmp[q ** 2 + q:]

        return x, t, dt, Exact_u, x_0, u_0, x_1, x_star, u_star, IRK_weights, IRK_times

    # Meshing x and t in 2D (256,100)
    X, T = np.meshgrid(x, t)

    # Preparing the inputs x and t (meshed as X, T) for predictions in one single array, as X_star
    X_star = np.hstack((X.flatten()[:, None], T.flatten()[:, None]))

    # Preparing the testing u_star
    u_star = Exact_u.flatten()[:, None]

    # Noiseless data TODO: add support for noisy data
    idx = np.random.choice(X_star.shape[0], N_u, replace=False)
    X_u_train = X_star[idx, :]
    u_train = u_star[idx, :]

    if N_0 != None and N_1 != None:
        Exact_u = Exact_u.T
        idx_x = np.random.choice(Exact_u.shape[0], N_0, replace=False)
        x_0 = x[idx_x, :]
        u_0 = Exact_u[idx_x, idx_t_0][:, None]
        u_0 = u_0 + noise * np.std(u_0) * np.random.randn(u_0.shape[0], u_0.shape[1])

        idx_x = np.random.choice(Exact_u.shape[0], N_1, replace=False)
        x_1 = x[idx_x, :]
        u_1 = Exact_u[idx_x, idx_t_1][:, None]
        u_1 = u_1 + noise * np.std(u_1) * np.random.randn(u_1.shape[0], u_1.shape[1])

        dt = np.asscalar(t[idx_t_1] - t[idx_t_0])
        q = int(np.ceil(0.5 * np.log(np.finfo(float).eps) / np.log(dt)))

        # Load IRK weights
        tmp = np.float32(np.loadtxt(os.path.join(utilsPath, "IRK_weights", "Butcher_IRK%d.txt" % (q)), ndmin=2))
        weights = np.reshape(tmp[0:q ** 2 + q], (q + 1, q))
        IRK_alpha = weights[0:-1, :]
        IRK_beta = weights[-1:, :]
        return x_0, u_0, x_1, u_1, x, t, dt, q, Exact_u, IRK_alpha, IRK_beta

    if N_f == None:
        lb = X_star.min(axis=0)
        ub = X_star.max(axis=0)
        return x, t, X, T, Exact_u, X_star, u_star, X_u_train, u_train, ub, lb

    # Domain bounds (lowerbounds upperbounds) [x, t], which are here ([-1.0, 0.0] and [1.0, 1.0])
    lb = X_star.min(axis=0)
    ub = X_star.max(axis=0)
    # Getting the initial conditions (t=0)
    xx1 = np.hstack((X[0:1, :].T, T[0:1, :].T))
    uu1 = Exact_u[0:1, :].T
    # Getting the initial conditions (t=1)
    xx4 = np.hstack((X[-1:, :].T, T[-1:, :].T))
    uu4 = Exact_u[-1:, :].T
    # Getting the lowest boundary conditions (x=-1)
    xx2 = np.hstack((X[:, 0:1], T[:, 0:1]))
    uu2 = Exact_u[:, 0:1]
    # Getting the highest boundary conditions (x=1)
    xx3 = np.hstack((X[:, -1:], T[:, -1:]))
    uu3 = Exact_u[:, -1:]
    # Stacking them in multidimensional tensors for training (X_u_train is for now the continuous boundaries)
    X_u_train = np.vstack([xx1, xx2, xx3, xx4])
    u_train = np.vstack([uu1, uu2, uu3, uu4])

    #  Generating the x and t collocation points for f, with each having a N_f size
    # We pointwise add and multiply to spread the LHS over the 2D domain
    X_f_train = lb + (ub - lb) * lhs(2, N_f)

    # Generating a uniform random sample from ints between 0, and the size of x_u_train, of size N_u (initial data size) and without replacement (unique)
    idx = np.random.choice(X_u_train.shape[0], N_u, replace=False)
    # Getting the corresponding X_u_train (which is now scarce boundary/initial coordinates)
    X_u_train = X_u_train[idx, :]
    #  Getting the corresponding u_train
    u_train = u_train[idx, :]

    return x, t, X, T, Exact_u, X_star, u_star, X_u_train, u_train, X_f_train, ub, lb


'''def plot_inf_cont_results(X_star, u_pred, X_u_train, u_train, Exact_u, X, T, x, t, save_path=None, save_hp=None):
    # For 1-D transient
    # Interpolating the results on the whole (x,t) domain.
    # griddata(points, values, points at which to interpolate, method)
    U_pred = griddata(X_star, u_pred, (X, T), method='cubic')

    # Creating the figures
    fig, ax = newfig(1.0, 1.1)
    ax.axis('off')

    ####### Row 0: u(t,x) ##################
    gs0 = gridspec.GridSpec(1, 2)
    gs0.update(top=1 - 0.06, bottom=1 - 1 / 3, left=0.15, right=0.85, wspace=0)
    ax = plt.subplot(gs0[:, :])

    h = ax.imshow(U_pred.T, interpolation='nearest', cmap='rainbow',
                  extent=[t.min(), t.max(), x.min(), x.max()],
                  origin='lower', aspect='auto')
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.05)
    fig.colorbar(h, cax=cax)

    ax.plot(X_u_train[:, 1], X_u_train[:, 0], 'kx', label='Data (%d points)' % (u_train.shape[0]), markersize=4,
            clip_on=False)

    line = np.linspace(x.min(), x.max(), 2)[:, None]
    ax.plot(t[25] * np.ones((2, 1)), line, 'w-', linewidth=1)
    ax.plot(t[50] * np.ones((2, 1)), line, 'w-', linewidth=1)
    ax.plot(t[75] * np.ones((2, 1)), line, 'w-', linewidth=1)

    ax.set_xlabel('$\\tau$')
    ax.set_ylabel('$\eta$')
    ax.legend(frameon=False, loc='best')
    ax.set_title('$\\theta(\\tau,\eta)$', fontsize=10)

    ####### Row 1: u(t,x) slices ##################
    gs1 = gridspec.GridSpec(1, 3)
    gs1.update(top=1 - 1 / 3, bottom=0, left=0.1, right=0.9, wspace=0.5)

    ax = plt.subplot(gs1[0, 0])
    ax.plot(x, Exact_u[25, :], 'b-', linewidth=2, label='Exact')
    ax.plot(x, U_pred[25, :], 'r--', linewidth=2, label='Prediction')
    ax.set_xlabel('$\\tau$')
    ax.set_ylabel('$\\theta(\\tau,\eta)$')
    ax.set_title('$\\tau = 0.25$', fontsize=10)
    ax.axis('square')
    ax.set_xlim([-1.1, 1.1])
    ax.set_ylim([-1.1, 1.1])

    ax = plt.subplot(gs1[0, 1])
    ax.plot(x, Exact_u[50, :], 'b-', linewidth=2, label='Exact')
    ax.plot(x, U_pred[50, :], 'r--', linewidth=2, label='Prediction')
    ax.set_xlabel('$\\tau$')
    ax.set_ylabel('$\\theta(\\tau,\eta)$')
    ax.axis('square')
    ax.set_xlim([-1.1, 1.1])
    ax.set_ylim([-1.1, 1.1])
    ax.set_title('$\\tau = 0.50$', fontsize=10)
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.35), ncol=5, frameon=False)

    ax = plt.subplot(gs1[0, 2])
    ax.plot(x, Exact_u[75, :], 'b-', linewidth=2, label='Exact')
    ax.plot(x, U_pred[75, :], 'r--', linewidth=2, label='Prediction')
    ax.set_xlabel('$\\tau$')
    ax.set_ylabel('$\\theta(\\tau,\eta)$')
    ax.axis('square')
    ax.set_xlim([-1.1, 1.1])
    ax.set_ylim([-1.1, 1.1])
    ax.set_title('$\\tau = 0.75$', fontsize=10)
    plt.show()

    if save_path != None and save_hp != None:
        saveResultDir(save_path, save_hp)

    else:
        plt.show()'''


def plot_inf_cont_results(X_star, u_pred, X_u_train, u_train, Exact_u, X, T, x, t, save_path=None, save_hp=None):
    # For 2-D steady
    # Interpolating the results on the whole (x,t) domain.
    # griddata(points, values, points at which to interpolate, method)
    U_pred = griddata(X_star, u_pred, (X, T), method='cubic')

    # Creating the figures
    fig, ax = newfig(1.0, 1.1)
    ax.axis('off')

    ####### Row 0: u(t,x) ##################
    gs0 = gridspec.GridSpec(1, 2)
    gs0.update(top=1 - 0.06, bottom=1 - 0.5, left=0.15, right=0.85, wspace=0)
    ax = plt.subplot(gs0[:, :])

    # h = ax.imshow(U_pred.T, interpolation='nearest', cmap='rainbow',
    #               extent=[t.min(), t.max(), x.min(), x.max()],
    #               origin='lower', aspect='auto')
    h = ax.imshow(U_pred.T, interpolation='nearest', cmap='rainbow',
                  extent=[t.min(), t.max(), x.min(), x.max()],
                  origin='lower')
    # ax.set_position([0.15, 0.7, 0.9, 0.44])
    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.1)
    fig.colorbar(h, cax=cax)

    ax.plot(X_u_train[:, 1], X_u_train[:, 0], 'kx', label='Data (%d points)' % (u_train.shape[0]), markersize=4,
            clip_on=False)

    line = np.linspace(x.min(), x.max(), 2)[:, None]
    ax.plot(t[25] * np.ones((2, 1)), line, 'w-', linewidth=1)
    ax.plot(t[50] * np.ones((2, 1)), line, 'w-', linewidth=1)
    ax.plot(t[75] * np.ones((2, 1)), line, 'w-', linewidth=1)

    ax.set_xlabel('$x/W$')
    ax.set_ylabel('$y/L$')
    ax.legend(frameon=False, loc='best')
    ax.set_title('$\\theta(x,y)$', fontsize=10)

    ####### Row 1: u(t,x) slices ##################
    gs1 = gridspec.GridSpec(1, 3)
    gs1.update(top=1-0.7, bottom=0.1, left=0.1, right=0.9, wspace=0.5)

    ax = plt.subplot(gs1[0, 0])
    ax.plot(x, Exact_u[25, :], 'b-', linewidth=2, label='Exact')
    ax.plot(x, U_pred[25, :], 'r--', linewidth=2, label='Prediction')
    ax.set_xlabel('$y/L$', labelpad=1)
    ax.set_ylabel('$\\theta(x,y)$')
    ax.set_title('$x/W = 0.25$', fontsize=10)
    ax.axis('square')
    ax.set_xlim([0, 1])
    ax.set_ylim([0, 1])
  

    ax = plt.subplot(gs1[0, 1])
    ax.plot(x, Exact_u[50, :], 'b-', linewidth=2, label='Exact')
    ax.plot(x, U_pred[50, :], 'r--', linewidth=2, label='Prediction')
    ax.set_xlabel('$y/L$', y=0.5)
    ax.set_ylabel('$\\theta(x,y)$')
    ax.axis('square')
    ax.set_xlim([0, 1])
    ax.set_ylim([0, 1])
    ax.set_title('$x/W = 0.50$', fontsize=10)
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.35), ncol=5, frameon=False)

    ax = plt.subplot(gs1[0, 2])
    ax.plot(x, Exact_u[75, :], 'b-', linewidth=2, label='Exact')
    ax.plot(x, U_pred[75, :], 'r--', linewidth=2, label='Prediction')
    ax.set_xlabel('$y/L$', y=0.2)
    ax.set_ylabel('$\\theta(x,y)$')
    ax.axis('square')
    ax.set_xlim([0, 1])
    ax.set_ylim([0, 1])
    ax.set_title('$x/W = 0.75$', fontsize=10)
    plt.show()

