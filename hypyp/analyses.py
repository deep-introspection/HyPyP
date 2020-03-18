#!/usr/bin/env python
# coding=utf-8
# ==============================================================================
# title           : analyses.py
# description     : inter-brain connectivity functions
# author          : Phoebe Chen, Guillaume Dumas
# date            : 2020-03-18
# version         : 1
# python_version  : 3.7
# ==============================================================================

import numpy as np
import scipy.signal as signal
from astropy.stats import circcorrcoef
import mne


def simple_corr(data, frequencies, mode, epoch_wise=True, time_resolved=True):
    """Compute frequency- and time-frequency-domain connectivity measures.

    Note that it is computed for all possible electrode pairs between the dyad, but doesn't include intrabrain synchrony

    Parameters
    ----------
    data : array-like, shape is (2, n_epochs, n_channels, n_times)
        The data from which to compute connectivity between two subjects
    frequencies : dict | list
        frequencies of interest to compute connectivity with.
        If a dict, different frequency bands are used.
        e.g. {'alpha':[8,12],'beta':[12,20]}
        If a list, every integer frequency within the range is used.
        e.g. [5,30]
    mode : string
        Connectivity measure to compute.
        'envelope': envelope correlation
        'power': power correlation
        'plv': phase locking value
        'ccorr': circular correlation coefficient
        'coh': coherence
        'imagcoh': imaginary coherence
        'proj': projected power correlation
    epoch_wise : boolean
        whether to compute epoch-to-epoch synchrony. default is True.
        if False, complex values from epochs will be concatenated before computing synchrony
        if True, synchrony is computed from matched epochs
    time_resolved : boolean
        whether to collapse the time course, only effective when epoch_wise==True
        if False, synchrony won't be averaged over epochs, and the time course is maintained.
        if True, synchrony is averaged over epochs.

    Returns
    -------
    result : array
        Computed connectivity measure(s). The shape of each array is either (n_freq, n_epochs, n_channels, n_channels)
        if epoch_wise is True and time_resolved is False, or (n_freq, n_channels, n_channels) in other conditions.

    """
    # Data consists of two lists of np.array (n_epochs, n_channels, epoch_size)
    assert data[0].shape[0] == data[1].shape[0], "Two streams much have the same lengths."

    # compute correlation coefficient for all symmetrical channel pairs
    if type(frequencies) == list:
        values = compute_single_freq(data, frequencies)
    # generate a list of per-epoch end values
    elif type(frequencies) == dict:
        values = compute_freq_bands(data, frequencies)

    result = compute_sync(values, mode, epoch_wise, time_resolved)

    return result


def compute_sync(complex_signal, mode, epoch_wise, time_resolved):
    """Compute synchrony from analytic signals.

    Parameters
    ----------
    complex_signal : array-like, shape is (2, n_epochs, n_channels, n_frequencies, n_times)
        complex array from which to compute synchrony for the two subjects.
    mode: str
        Connectivity measure to compute.
    epoch_wise : boolean
        whether to compute epoch-to-epoch synchrony. default is True.
    time_resolved : boolean
        whether to collapse the time course, only effective when epoch_wise==True

    Returns
    -------
    result : array
        Computed connectivity measure(s). The shape of each array is either (n_freq, n_epochs, n_channels, n_channels)
        if epoch_wise is True and time_resolved is False, or (n_freq, n_channels, n_channels) in other conditions.
    """

    n_epoch, n_ch, n_freq, n_samp = complex_signal.shape[1], complex_signal.shape[2], \
        complex_signal.shape[3], complex_signal.shape[4]

    # epoch wise synchrony
    if epoch_wise:
        if mode is 'envelope':
            values = np.abs(complex_signal)
            result = np.array([[[[_corrcoef(values[0, epoch, ch_i, freq, :], values[1, epoch, ch_j, freq, :]) for ch_i in range(n_ch)]
                                 for ch_j in range(n_ch)]
                                for epoch in range(n_epoch)]
                               for freq in range(n_freq)])  # shape = (n_freq, n_epoch, n_ch, n_ch)
        elif mode is 'power':
            values = np.abs(complex_signal)**2
            result = np.array([[[[_corrcoef(values[0, epoch, ch_i, freq, :], values[1, epoch, ch_j, freq, :]) for ch_i in range(n_ch)]
                                 for ch_j in range(n_ch)]
                                for epoch in range(n_epoch)]
                               for freq in range(n_freq)])  # shape = (n_freq, n_epoch, n_ch, n_ch)

        elif mode is 'plv':
            values = complex_signal / np.abs(complex_signal)
            result = np.array([[[[_plv(values[0, epoch, ch_i, freq, :], values[1, epoch, ch_j, freq, :]) for ch_i in range(n_ch)]
                                 for ch_j in range(n_ch)]
                                for epoch in range(n_epoch)]
                               for freq in range(n_freq)])  # shape = (n_freq, n_epoch, n_ch, n_ch)
        elif mode is 'ccorr':
            values = np.angle(complex_signal)
            result = np.array([[[[circcorrcoef(values[0, epoch, ch_i, freq, :], values[1, epoch, ch_j, freq, :]) for ch_i in range(n_ch)]
                                 for ch_j in range(n_ch)]
                                for epoch in range(n_epoch)]
                               for freq in range(n_freq)])  # shape = (n_freq, n_epoch, n_ch, n_ch)
        elif mode is 'proj':
            values = complex_signal
            result = np.array([[[[_proj_power_corr(values[0, epoch, ch_i, freq, :], values[1, epoch, ch_j, freq, :]) for ch_i in range(n_ch)]
                                 for ch_j in range(n_ch)]
                                for epoch in range(n_epoch)]
                               for freq in range(n_freq)])

        elif mode is 'imagcoh':
            values = complex_signal
            result = np.array([[[[_icoh(values[0, epoch, ch_i, freq, :], values[1, epoch, ch_j, freq, :]) for ch_i in range(n_ch)]
                                 for ch_j in range(n_ch)]
                                for epoch in range(n_epoch)]
                               for freq in range(n_freq)])
        elif mode is 'coh':
            values = complex_signal
            result = np.array([[[[_coh(values[0, epoch, ch_i, freq, :], values[1, epoch, ch_j, freq, :]) for ch_i in range(n_ch)]
                                 for ch_j in range(n_ch)]
                                for epoch in range(n_epoch)]
                               for freq in range(n_freq)])
        else:
            raise NameError('Sychrony metric ' + mode + ' not supported.')

        # whether averaging across epochs
        if time_resolved:
            result = np.nanmean(result, axis=1)

    # generate a single connectivity value from two concatenated time series
    else:
        if mode is 'envelope':
            values = np.abs(complex_signal)
            strands = np.array(
                [np.concatenate(values[n], axis=2) for n in range(2)])  # concatenate values from all epochs
            result = np.array([[[_corrcoef(strands[0, ch_i, freq, :], strands[1, ch_j, freq, :]) for ch_i in range(n_ch)]
                                for ch_j in range(n_ch)]
                               for freq in range(n_freq)])  # shape = (n_freq, n_epoch, n_ch, n_ch)
        elif mode is 'power':
            values = np.abs(complex_signal)**2
            strands = np.array(
                [np.concatenate(values[n], axis=2) for n in range(2)])  # concatenate values from all epochs
            result = np.array([[[_corrcoef(strands[0, ch_i, freq, :], strands[1, ch_j, freq, :]) for ch_i in range(n_ch)]
                                for ch_j in range(n_ch)]
                               for freq in range(n_freq)])  # shape = (n_freq, n_epoch, n_ch, n_ch)
        elif mode is 'plv':
            # should be np.angle
            values = complex_signal / np.abs(complex_signal)  # phase
            strands = np.array(
                [np.concatenate(values[n], axis=2) for n in range(2)])  # concatenate values from all epochs
            result = np.array([[[_plv(strands[0, ch_i, freq, :], strands[1, ch_j, freq, :]) for ch_i in range(n_ch)]
                                for ch_j in range(n_ch)]
                               for freq in range(n_freq)])
        elif mode is 'ccorr':
            values = np.angle(complex_signal)
            strands = np.array(
                [np.concatenate(values[n], axis=2) for n in range(2)])  # concatenate values from all epochs
            result = np.array([[[circcorrcoef(strands[0, ch_i, freq, :], strands[1, ch_j, freq, :]) for ch_i in range(n_ch)]
                                for ch_j in range(n_ch)]
                               for freq in range(n_freq)])
        elif mode is 'proj':
            values = complex_signal
            strands = np.array(
                [np.concatenate(values[n], axis=2) for n in range(2)])  # concatenate values from all epochs
            result = np.array([[[_proj_power_corr(strands[0, ch_i, freq, :], strands[1, ch_j, freq, :]) for ch_i in range(n_ch)]
                                for ch_j in range(n_ch)]
                               for freq in range(n_freq)])
        elif mode is 'imagcoh':
            values = complex_signal
            strands = np.array(
                [np.concatenate(values[n], axis=2) for n in range(2)])  # concatenate values from all epochs
            result = np.array([[[_icoh(strands[0, ch_i, freq, :], strands[1, ch_j, freq, :]) for ch_i in range(n_ch)]
                                for ch_j in range(n_ch)]
                               for freq in range(n_freq)])
        elif mode is 'coh':
            values = complex_signal
            strands = np.array(
                [np.concatenate(values[n], axis=2) for n in range(2)])  # concatenate values from all epochs
            result = np.array([[[_coh(strands[0, ch_i, freq, :], strands[1, ch_j, freq, :]) for ch_i in range(n_ch)]
                                for ch_j in range(n_ch)]
                               for freq in range(n_freq)])
        else:
            raise NameError('Sychrony metric '+mode+' not supported.')

    return result


def compute_single_freq(data, freq_range):
    """Compute analytic signal per frequency bin using a multitaper method implemented in mne

    Parameters
    ----------
    data : array-like, shape is (2, n_epochs, n_channels, n_times)
        real-valued data to compute analytic signal from.
    freq_range : list
        a list of two specifying the frequency range

    Returns
    -------
    complex_signal : array, shape is (2, n_epochs, n_channels, n_frequencies, n_times)

    """
    n_samp = data[0].shape[2]

    complex_signal = np.array([mne.time_frequency.tfr_array_multitaper(data[subject], sfreq=n_samp,
                                                                       freqs=np.arange(
                                                                           freq_range[0], freq_range[1], 1),
                                                                       n_cycles=4,
                                                                       zero_mean=False, use_fft=True, decim=1, output='complex')
                               for subject in range(2)])

    return complex_signal


def compute_freq_bands(data, freq_bands):
    """Compute analytic signal per frequency band using filtering and hilbert transform

    Parameters
    ----------
    data : array-like, shape is (2, n_epochs, n_channels, n_times)
        real-valued data to compute analytic signal from.
    freq_bands : dict
        a dict specifying names and corresponding frequency ranges

    Returns
    -------
    complex_signal : array, shape is (2, n_epochs, n_channels, n_freq_bands, n_times)

    """
    assert data[0].shape[0] == data[1].shape[0]
    n_epoch = data[0].shape[0]
    n_ch = data[0].shape[1]
    n_samp = data[0].shape[2]
    data = np.array(data)

    # filtering and hilbert transform
    complex_signal = []
    for freq_band in freq_bands.values():
        filtered = np.array([mne.filter.filter_data(data[subject], n_samp, freq_band[0], freq_band[1], verbose=False)
                             for subject in range(2)  # for each subject
                             ])
        hilb = signal.hilbert(filtered)
        complex_signal.append(hilb)

    complex_signal = np.moveaxis(np.array(complex_signal), [0], [3])
    assert complex_signal.shape == (2, n_epoch, n_ch, len(freq_bands), n_samp)

    return complex_signal


## Synchrony metrics

def _plv(X, Y):
    """Phase Locking Value
    takes two vectors (phase) and compute their plv

    """
    return np.abs(np.sum(np.exp(1j * (X - Y)))) / len(X)


def _coh(X, Y):
    """Coherence
    instantaneous coherence computed from hilbert transformed signal, then averaged across time points

            |A1·A2·e^(i*delta_phase)|
    Coh = -----------------------------
               sqrt(A1^2 * A2^2)

    A1: envelope of X
    A2: envelope of Y
    reference: Kida, Tetsuo, Emi Tanaka, and Ryusuke Kakigi. “Multi-Dimensional Dynamics of Human Electromagnetic Brain Activity.” Frontiers in Human Neuroscience 9 (January 19, 2016). https://doi.org/10.3389/fnhum.2015.00713.

    """

    # use np.angle
    X_phase = X / np.abs(X)
    Y_phase = Y / np.abs(Y)

    Sxy = np.abs(X) * np.abs(Y) * np.exp(1j * (X_phase - Y_phase))
    Sxx = np.abs(X)**2
    Syy = np.abs(Y)**2

    coh = np.abs(Sxy/(np.sqrt(Sxx*Syy)))
    return np.nanmean(coh)


def _icoh(X, Y):
    """Coherence
    instantaneous imaginary coherence computed from hilbert transformed signal, then averaged across time points

            |A1·A2·sin(delta_phase)|
    iCoh = -----------------------------
               sqrt(A1^2 * A2^2)
    """

    X_phase = X / np.abs(X)
    Y_phase = Y / np.abs(Y)

    iSxy = np.abs(X) * np.abs(Y) * np.sin(X_phase - Y_phase)
    Sxx = np.abs(X)**2
    Syy = np.abs(Y)**2

    icoh = np.abs(iSxy/(np.sqrt(Sxx*Syy)))
    return np.nanmean(icoh)


def _corrcoef(X, Y):
    """
    just pearson correlation coefficient
    """
    return np.corrcoef([X, Y])[0][1]


def _proj_power_corr(X, Y):
    # compute power proj corr using two complex signals
    # adapted from Georgios Michalareas' MATLAB script
    X_abs = np.abs(X)
    Y_abs = np.abs(Y)

    X_unit = X / X_abs
    Y_unit = Y / Y_abs

    X_abs_norm = (X_abs - np.nanmean(X_abs)) / np.nanstd(X_abs)
    Y_abs_norm = (Y_abs - np.nanmean(Y_abs)) / np.nanstd(Y_abs)

    X_ = X_abs / np.nanstd(X_abs)
    Y_ = Y_abs / np.nanstd(Y_abs)

    X_z = X_ * X_unit
    Y_z = Y_ * Y_unit
    projX = np.imag(X_z * np.conjugate(Y_unit))
    projY = np.imag(Y_z * np.conjugate(X_unit))

    projX_norm = (projX - np.nanmean(projX)) / np.nanstd(projX)
    projY_norm = (projY - np.nanmean(projY)) / np.nanstd(projY)

    proj_corr = (np.nanmean(projX_norm * Y_abs_norm) +
                 np.nanmean(projY_norm * X_abs_norm)) / 2

    return proj_corr