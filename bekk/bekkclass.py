#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
BEKK model class
================

"""
from __future__ import print_function, division

import time

import numpy as np
from scipy.optimize import minimize

from bekk import ParamStandard, ParamSpatial
from .utils import estimate_h0, likelihood_python, filter_var_python
try:
    from .recursion import filter_var
    from .likelihood import likelihood_gauss
except:
    print('Failed to import cython modules. '
          + 'Temporary hack to compile documentation.')

__all__ = ['BEKK']


class BEKK(object):
    r"""BEKK model.

    .. math::
        u_t = e_t H_t^{1/2},\quad e_t \sim N(0,I),

    with variance matrix evolving accrding to the following recursion:

    .. math::
        H_t = CC^\prime + Au_{t-1}u_{t-1}^\prime A^\prime + BH_{t-1}B^\prime.

    Attributes
    ----------
    innov
        Return innovations
    log_file
        File name to write the results of estimation
    param_start
        Initial values of model parameters
    param_final
        Final values of model parameters
    opt_out
        Optimization results

    Methods
    -------
    estimate
        Estimate parameters of standard BEKK
    estimate_spatial
        Estimate parameters of spatial BEKK

    """

    def __init__(self, innov):
        """Initialize the class.

        Parameters
        ----------
        innov : (nobs, nstocks) array
            Return innovations

        """
        self.innov = innov
        self.log_file = None
        self.param_start = None
        self.param_final = None
        self.method = 'SLSQP'
        self.time_delta = None
        self.opt_out = None
        self.cython = True
        self.hvar = None

    def likelihood(self, theta):
        """Compute the conditional log-likelihood function.

        Parameters
        ----------
        theta : 1dim array
            Dimension depends on the model restriction

        Returns
        -------
        float
            The value of the minus log-likelihood function.
            If some regularity conditions are violated, then it returns
            some obscene number.

        """
        param = ParamStandard.from_theta(theta=theta, target=self.target,
                                         nstocks=self.innov.shape[1],
                                         restriction=self.restriction)

        if param.constraint() >= 1 or param.cmat is None:
            return 1e10

        args = [self.hvar, self.innov, param.amat, param.bmat, param.cmat]

        if self.cython:
            filter_var(*args)
            return likelihood_gauss(self.hvar, self.innov)
        else:
            filter_var_python(*args)
            return likelihood_python(self.hvar, self.innov)

    def likelihood_spatial(self, theta):
        """Compute the conditional log-likelihood function for spatial case.

        Parameters
        ----------
        theta : 1dim array
            Dimension depends on the model restriction

        Returns
        -------
        float
            The value of the minus log-likelihood function.
            If some regularity conditions are violated, then it returns
            some obscene number.

        """
        param = ParamSpatial.from_theta_spatial(theta=theta,
                                                target=self.target,
                                                weights=self.weights)

        if param.constraint() >= 1 or param.cmat is None:
            return 1e10

        args = [self.hvar, self.innov, param.amat, param.bmat, param.cmat]

        if self.cython:
            filter_var(*args)
            return likelihood_gauss(self.hvar, self.innov)
        else:
            filter_var_python(*args)
            return likelihood_python(self.hvar, self.innov)

    def callback(self, theta):
        """Empty callback function.

        Parameters
        ----------
        theta : 1dim array
            Parameter vector

        """
        pass

    def print_results(self, **kwargs):
        """Print stuff after estimation.

        Parameters
        ----------
        kwargs : dict, optional
            Keyword arguments

        """
        if 'param_true' in kwargs:
            like_true = self.likelihood(kwargs['param_true'].theta, kwargs)
        like_start = self.likelihood(self.param_start.theta, kwargs)
        like_final = self.likelihood(self.param_final.theta, kwargs)
        # Form the string
        string = ['\n']
        string.append('Method = ' + self.method)
        string.append('Total time (minutes) = %.2f' % self.time_delta)
        if 'theta_true' in kwargs:
            string.append('True likelihood = %.2f' % like_true)
        string.append('Initial likelihood = %.2f' % like_start)
        string.append('Final likelihood = %.2f' % like_final)
        string.append('Likelihood difference = %.2f' %
                      (like_start - like_final))
        string.append('Success = ' + str(self.opt_out.success))
        string.append('Message = ' + str(self.opt_out.message))
        string.append('Iterations = ' + str(self.opt_out.nit))
        string.extend(self.param_final.log_string())
        string.append('\nH0 target =\n'
                      + np.array_str(estimate_h0(self.innov)))
        # Save results to the log file
        with open(self.log_file, 'a') as texfile:
            for istring in string:
                texfile.write(istring + '\n')

    def estimate(self, param_start=None, restriction='scalar', var_target=True,
                 method='SLSQP', cython=True):
        """Estimate parameters of the BEKK model.

        Updates several attributes of the class.

        Parameters
        ----------
        param_start : BEKKParams instance
            Starting parameters
        restriction : str
            Can be
                - 'full'
                - 'diagonal'
                - 'scalar'
        var_target : bool
            Variance targeting flag. If True, then cmat is not returned.
        method : str
            Optimization method. See scipy.optimize.minimize
        cython : bool
            Whether to use Cython optimizations (True) or not (False)

        """
        # Update default settings
        nobs, nstocks = self.innov.shape
        target = estimate_h0(self.innov)
        self.restriction = restriction
        self.cython = cython

        if param_start is not None:
            theta_start = param_start.get_theta(restriction=restriction,
                                                var_target=var_target)
        else:
            param_start = BEKKParams.from_target(target=target)
            theta_start = param_start.get_theta(restriction=restriction,
                                                var_target=var_target)

        if var_target:
            self.target = target
        else:
            self.target = None

        self.hvar = np.zeros((nobs, nstocks, nstocks), dtype=float)
        self.hvar[0] = target.copy()

        # Optimization options
        options = {'disp': False, 'maxiter': int(1e6)}
        # Check for existence of initial guess among arguments.
        # Otherwise, initialize.

        # Start timer for the whole optimization
        time_start = time.time()
        # Run optimization
        self.opt_out = minimize(self.likelihood, theta_start, method=method,
                                options=options)
        # How much time did it take in minutes?
        self.time_delta = (time.time() - time_start) / 60
        # Store optimal parameters in the corresponding class
        self.param_final = BEKKParams.from_theta(theta=self.opt_out.x,
                                                 restriction=restriction,
                                                 target=self.target,
                                                 nstocks=nstocks)

    def estimate_spatial(self, param_start=None, var_target=True, weights=None,
                         method='SLSQP', cython=True):
        """Estimate parameters of the BEKK model.

        Updates several attributes of the class.

        Parameters
        ----------
        param_start : BEKKParams instance
            Starting parameters
        var_target : bool
            Variance targeting flag. If True, then cmat is not returned.
        weights : (ncat, nstocks, nstocks) array
            Weight matrices
        method : str
            Optimization method. See scipy.optimize.minimize
        cython : bool
            Whether to use Cython optimizations (True) or not (False)

        """
        # Update default settings
        nobs, nstocks = self.innov.shape
        target = estimate_h0(self.innov)
        self.cython = cython
        self.weights = weights

        if param_start is not None:
            theta_start = param_start.get_theta_spatial(var_target=var_target)
        else:
            msg = 'Automatic initial parameter is not yet implemented!'
            raise NotImplementedError(msg)

        if var_target:
            self.target = target
        else:
            self.target = None

        self.hvar = np.zeros((nobs, nstocks, nstocks), dtype=float)
        self.hvar[0] = target.copy()

        # Optimization options
        options = {'disp': False, 'maxiter': int(1e6)}
        # Check for existence of initial guess among arguments.
        # Otherwise, initialize.

        # Start timer for the whole optimization
        time_start = time.time()
        # Run optimization
        self.opt_out = minimize(self.likelihood_spatial, theta_start,
                                method=method, options=options)
        # How much time did it take in minutes?
        self.time_delta = (time.time() - time_start) / 60
        # Store optimal parameters in the corresponding class
        self.param_final = BEKKParams.from_theta_spatial(theta=self.opt_out.x,
                                                         target=self.target,
                                                         weights=weights)


if __name__ == '__main__':
    pass
    #from usage_example import test_bekk
    #test_bekk(nstocks=1, nobs=500, var_target=False)
