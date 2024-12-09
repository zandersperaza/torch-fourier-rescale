from __future__ import annotations

from math import ceil, floor

import numpy as np
import torch
import torch.nn.functional as F
from .utils import get_target_fftfreq

torch.set_printoptions(threshold=float('inf'))

def fourier_rescale_2d(
    image: torch.Tensor,
    source_spacing: float | tuple[float, float],
    target_spacing: float | tuple[float, float],
) -> tuple[torch.Tensor, tuple[float, float]]:
    """Rescale 2D image(s) from `source_spacing` to `target_spacing`.

    Rescaling is performed in Fourier space by either cropping or padding the
    discrete Fourier transform (DFT).

    Parameters
    ----------
    image: torch.Tensor
        `(..., h, w)` array of image data
    source_spacing: float | tuple[float, float]
        Pixel spacing in the input image.
    target_spacing: float | tuple[float, float]
        Pixel spacing in the output image.

    Returns
    -------
    rescaled_image, (new_spacing_h, new_spacing_w)
    """
    if isinstance(source_spacing, int | float):
        source_spacing = (source_spacing, source_spacing)
    if isinstance(target_spacing, int | float):
        target_spacing = (target_spacing, target_spacing)
    if source_spacing == target_spacing:
        return image, source_spacing
   
    import matplotlib.pyplot as plt
    def showme(image):
        plt.imshow(image.squeeze(0),cmap='grey')
        plt.show()

    # place image center at array indices [0, 0] and compute centered rfft2
    image = torch.fft.fftshift(image, dim=(-2, -1))
    dft = torch.fft.rfftn(image, dim=(-2, -1))
    dft = torch.fft.fftshift(dft, dim=(-2,))
    # Fourier pad/crop
    dft, new_nyquist = fourier_rescale_rfft_2d(
        dft=dft,
        image_shape=image.shape[-2:],
        source_spacing=source_spacing,
        target_spacing=target_spacing
    )
    # transform back to real space and recenter
    dft = torch.fft.ifftshift(dft, dim=(-2,))
    rescaled_image = torch.fft.irfftn(dft, dim=(-2, -1))
    rescaled_image = torch.fft.ifftshift(rescaled_image, dim=(-2, -1))

    # Calculate new spacing after rescaling
    source_spacing = np.array(source_spacing, dtype=np.float32)
    new_nyquist = np.array(new_nyquist, dtype=np.float32)
    new_spacing = 1 / (2 * new_nyquist * (1 / np.array(source_spacing)))

    return rescaled_image, tuple(new_spacing)


def fourier_rescale_rfft_2d(
    dft: torch.Tensor,
    image_shape: tuple[int, int],
    source_spacing: tuple[float, float],
    target_spacing: tuple[float, float],
) -> tuple[torch.Tensor, tuple[float, float]]:
    h, w = image_shape
    freq_h, freq_w = get_target_fftfreq(source_spacing, target_spacing)
    if freq_h > 0.5:
        dft, nyquist_h = _fourier_pad_h(dft, image_height=h, target_fftfreq=freq_h)
    else:
        dft, nyquist_h = _fourier_crop_h(dft, image_height=h, target_fftfreq=freq_h)
    if freq_w > 0.5:
        dft, nyquist_w = _fourier_pad_w(dft, image_width=w, target_fftfreq=freq_w)
    else:
        dft, nyquist_w = _fourier_crop_w(dft, image_width=w, target_fftfreq=freq_w)
    return dft, (nyquist_h, nyquist_w)


def custom_fftfreq_with_double_zero(N):
    # Shift frequencies
    freqs = torch.fft.fftshift(torch.fft.fftfreq(N))
    # Add an extra zero in the center manually and remove most negative frequency (maintain symmetry)
    mid_idx = len(freqs) // 2
    freqs = torch.cat([freqs[:mid_idx], torch.tensor([0.0]), freqs[mid_idx:]])[1:]
    return freqs


def _fourier_crop_h(dft: torch.Tensor, image_height: int, target_fftfreq: float):
    '''
    frequencies = torch.fft.fftfreq(image_height)
    frequencies = torch.fft.fftshift(frequencies)
    '''
    frequencies = custom_fftfreq_with_double_zero(image_height)
    idx_nyquist = torch.argmin(torch.abs(frequencies - target_fftfreq))
    new_nyquist = frequencies[idx_nyquist]
    idx_h = torch.abs(frequencies) < new_nyquist
    return dft[..., idx_h, :], new_nyquist


def _fourier_crop_w(dft: torch.Tensor, image_width: int, target_fftfreq: float):
    frequencies = torch.fft.rfftfreq(image_width)
    idx_nyquist = torch.argmin(torch.abs(frequencies - target_fftfreq))
    new_nyquist = frequencies[idx_nyquist]
    idx_w = frequencies <= new_nyquist
    return dft[..., :, idx_w], new_nyquist


def _fourier_pad_h(dft: torch.Tensor, image_height: int, target_fftfreq: float):
    delta_fftfreq = 1 / image_height
    idx_nyquist = target_fftfreq / delta_fftfreq
    idx_nyquist = ceil(idx_nyquist) if ceil(idx_nyquist) % 2 == 0 else floor(idx_nyquist)
    new_nyquist = idx_nyquist * delta_fftfreq
    n_frequencies = (dft.shape[-2] // 2) + 1
    pad_h = idx_nyquist - (n_frequencies - 1)
    dft = F.pad(dft, pad=(0, 0, pad_h, pad_h), mode='constant', value=0)
    return dft, new_nyquist


def _fourier_pad_w(dft: torch.Tensor, image_width: int, target_fftfreq: float):
    delta_fftfreq = 1 / image_width
    idx_nyquist = target_fftfreq / delta_fftfreq
    idx_nyquist = ceil(idx_nyquist) if ceil(idx_nyquist) % 2 == 0 else floor(
        idx_nyquist)
    new_nyquist = idx_nyquist * delta_fftfreq
    n_frequencies = dft.shape[-1]
    pad_w = idx_nyquist - (n_frequencies - 1)
    dft = F.pad(dft, pad=(0, pad_w), mode='constant', value=0)
    return dft, new_nyquist
