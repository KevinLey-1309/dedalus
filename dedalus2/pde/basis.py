

import numpy as np
from scipy import sparse
from scipy.sparse import linalg
from scipy import fftpack as fft


class Basis:
    """Base class for all bases."""

    def __init__(self, grid_size, interval):

        # Inputs
        self.grid_size = grid_size
        self.interval = interval

    def _set_dtype(self, dtype):

        raise NotImplementedError()

    def forward(self, xdata, kdata, axis):

        raise NotImplementedError()

    def backward(self, kdata, xdata, axis):

        raise NotImplementedError()

    def differentiate(self, kdata, kderiv, axis):

        raise NotImplementedError()


class TauBasis(Basis):
    """Base class for bases supporting Tau solves."""

    def _build_tau_matrices(self):
        """Build matrices for constructing the Tau LHS."""

        self._Pre = self._build_Pre()
        self._Deriv = self._build_Diff()
        self._Left = self._build_Left()
        self._Right = self._build_Right()
        self._last = self._build_last()

    def _build_Pre(self):
        """Build preconditioning matrix."""

        # Construct sparse identity matrix
        Pre = sparse.identity(self.coeff_size, dtype=self.coeff_dtype)

        return Pre.tocsr()

    def _build_Diff(self):
        """Build differentiation matrix."""

        raise NotImplementedError()

    def _build_Left(self):
        """Build left-endpoint-evaluation matrix."""

        raise NotImplementedError()

    def _build_Right(self):
        """Build right-endpoint-evaluation matrix."""

        raise NotImplementedError()

    def _build_Mult(self, p):
        """Build p-element multiplication matrix."""

        raise NotImplementedError()

    def _build_last(self):
        """Build last-coefficient vector."""

        # Construct dense vector
        last = np.zeros(self.coeff_size, dtype=self.coeff_dtype)
        last[-1] = 1.

        return last


class Chebyshev(TauBasis):
    """Chebyshev polynomial basis on the extrema grid."""

    def __init__(self, grid_size, interval=[-1., 1.]):

        # Inherited initialization
        TauBasis.__init__(self, grid_size, interval)

        # Parameters
        self.coeff_size = grid_size
        self.N = grid_size - 1

        # Grid
        radius = (interval[1] - interval[0]) / 2.
        center = (interval[1] + interval[0]) / 2.
        i = np.arange(self.N + 1)
        native_grid = np.cos(np.pi * i / self.N)
        self.grid = center + radius * native_grid
        self._diff_scale = 1. / radius

    def _set_dtype(self, dtype):
        """Specify datatypes."""

        # Set datatypes
        self.grid_dtype = dtype
        self.coeff_dtype = dtype

        # Allocate scratch array
        self._math = np.zeros(self.coeff_size, dtype=dtype)

        # Set transforms
        if dtype is np.float64:
            self.forward = self._forward_r2r
            self.backward = self._backward_r2r
        elif dtype is np.complex128:
            self.forward = self._forward_c2c
            self.backward = self._backward_c2c
        else:
            raise ValueError("Unsupported dtype.")

        return self.coeff_dtype

    def _forward_r2r(self, xdata, kdata, axis):
        """Grid-to-coefficient transform on real data."""

        # Currently setup just for last axis
        if axis != -1:
            if axis != (len(xdata.shape) - 1):
                raise NotImplementedError()

        # DCT with adjusted coefficients
        N = self.N
        kdata.real = fft.dct(xdata.real, type=1, norm=None, axis=axis)
        kdata.imag = fft.dct(xdata.imag, type=1, norm=None, axis=axis)
        kdata /= N
        kdata[..., 0] /= 2.
        kdata[..., N] /= 2.


    def _forward_c2c(self, xdata, kdata, axis):
        """Grid-to-coefficient transfrom on complex data."""

        # Currently setup just for last axis
        if axis != -1:
            if axis != (len(xdata.shape) - 1):
                raise NotImplementedError()

        # DCT with adjusted coefficients
        N = self.N
        kdata[:] = fft.dct(xdata, type=1, norm=None, axis=axis)
        kdata /= N
        kdata[..., 0] /= 2.
        kdata[..., N] /= 2.

    def _backward_r2r(self, kdata, xdata, axis):
        """Coefficient-to-grid transform on real data."""

        # Currently setup just for last axis
        if axis != -1:
            if axis != (len(kdata.shape) - 1):
                raise NotImplementedError()

        # DCT with adjusted coefficients
        N = self.N
        self._math[..., :] = kdata
        self._math[..., 1:N] /= 2.
        xdata[:] = fft.dct(self._math, type=1, norm=None, axis=axis)

    def _backward_c2c(self, kdata, xdata, axis):
        """Coefficient-to-grid transform on complex data."""

        # Currently setup just for last axis
        if axis != -1:
            if axis != (len(kdata.shape) - 1):
                raise NotImplementedError()

        # DCT with adjusted coefficients
        N = self.N
        self._math[..., :] = kdata
        self._math[..., 1:N] /= 2.
        xdata.real = fft.dct(self._math.real, type=1, norm=None, axis=axis)
        xdata.imag = fft.dct(self._math.imag, type=1, norm=None, axis=axis)

    def differentiate(self, kdata, kderiv, axis):
        """Differentiation by recursion on coefficients."""

        # Currently setup just for last axis
        if axis != -1:
            if axis != (len(kdata.shape) - 1):
                raise NotImplementedError()

        # Referencess
        a = kdata
        b = kderiv
        N = self.N

        # Apply recursive differentiation
        b[..., N] = 0.
        b[..., N-1] = 2. * N * a[..., N]
        for i in range(N-2, 0, -1):
            b[..., i] = 2 * (i+1) * a[..., i+1] + b[..., i+2]
        b[..., 0] = a[..., 1] + b[..., 2] / 2.

        # Scale for grid
        kderiv *= self._diff_scale

    def _build_Pre(self):
        """
        Build preconditioning matrix.

        T_n = (U_n - U_(n-2)) / 2
        U_(-n) = -U_(n-2)

        """

        size = self.coeff_size

        # Initialize sparse matrix
        Pre = sparse.lil_matrix((size, size), dtype=self.coeff_dtype)

        # Add elements
        for n in range(size):

            # Diagonal
            if n == 0:
                Pre[n, n] = 1.
            else:
                Pre[n, n] = 0.5

            # 2nd superdiagonal
            if n >= 2:
                Pre[n-2, n] = -0.5

        return Pre.tocsr()

    def _build_Diff(self):
        """
        DEBUG
        Build T-to-U differentiation matrix.

        d_x(T_n) = n U_(n-1)

        """

        size = self.coeff_size

        # Initialize sparse matrix
        Deriv = sparse.lil_matrix((size, size), dtype=self.coeff_dtype)

        # Add elements
        for n in range(1, size):

            # 1st superdiagonal
            Deriv[n-1, n] = n * self._diff_scale

        return Deriv.tocsr()

    def _build_Left(self):
        """
        Build left-endpoint-evaluation matrix.

        T_n(-1) = (-1)**n

        """

        size = self.coeff_size

        # Initialize sparse matrix
        Left = sparse.lil_matrix((size, size), dtype=self.coeff_dtype)

        # Add elements
        for n in range(size):

            # Last row
            if (n % 2) == 0:
                Left[-1, n] = 1.
            else:
                Left[-1, n] = -1.

        return Left.tocsr()

    def _build_Right(self):
        """
        Build right-endpoint-evaluation matrix.

        T_n(1) = 1

        """

        size = self.coeff_size

        # Initialize sparse matrix
        Right = sparse.lil_matrix((size, size), dtype=self.coeff_dtype)

        # Add elements
        for n in range(size):

            # Last row
            Right[-1, n] = 1.

        return Right.tocsr()

    def _build_Mult(self, p):
        """
        Build p-element multiplication matrix

        T_p * T_n = (T_(n+p) + T_(n-p)) / 2
        T_(-n) = T_n

        """

        size = self.coeff_size

        # Construct sparse matrix
        Mult = sparse.lil_matrix((size, size), dtype=self.coeff_dtype)

        # Add elements
        for n in range(size):

            # Upper product
            i = n + p
            if i < size:
                Mult[i, n] += 0.5

            # Lower product
            i = abs(n - p)
            if i < size:
                Mult[i, n] += 0.5

        return Mult.tocsr()


class Fourier(Basis):
    """Fourier complex exponential basis."""

    def __init__(self, grid_size, interval=[0., 2.*np.pi]):

        # Inherited initialization
        Basis.__init__(self, grid_size, interval)

        # Grid
        length = interval[1] - interval[0]
        start = interval[0]
        native_grid = np.linspace(0., 1., grid_size, endpoint=False)
        self.grid = start + length * native_grid
        self._diff_scale = 2. * np.pi / length

    def _set_dtype(self, dtype):
        """Specify datatypes."""

        # Set datatypes
        self.grid_dtype = dtype
        self.coeff_dtype = np.complex128

        # Set transforms
        n = self.grid_size
        if dtype is np.float64:
            self.forward = self._forward_r2c
            self.backward = self._backward_c2r
            self.coeff_size = n//2 + 1
            self.wavenumbers = np.arange(0, n//2 + 1)
        elif dtype is np.complex128:
            self.forward = self._forward_c2c
            self.backward = self._backward_c2c
            self.coeff_size = n
            self.wavenumbers = np.hstack((np.arange(0, n//2+1),
                                          np.arange((-n)//2+1, 0)))
        else:
            raise ValueError("Unsupported dtype.")

        self.wavenumbers *= self._diff_scale

        return self._coeff_dtype

    def _forward_r2c(self, xdata, kdata, axis):
        """Grid-to-coefficient transform on real data."""

        kdata[:] = fft.rfft(xdata, axis=axis)
        kdata /= self.grid_size

    def _forward_c2c(self, xdata, kdata, axis):
        """Grid-to-coefficient transform on complex data."""

        kdata[:] = fft.fft(xdata, axis=axis)
        kdata /= self.grid_size

    def _backward_c2r(self, kdata, xdata, axis):
        """Coefficient-to-grid transform on real data."""

        xdata[:] = fft.irfft(kdata, axis=axis)
        xdata *= self.grid_size

    def _backward_c2c(self, kdata, xdata, axis):
        """Coefficient-to-grid transform on complex data."""

        xdata[:] = fft.ifft(kdata, axis=axis)
        xdata *= self.grid_size

    def differentiate(self, kdata, kderiv, axis):
        """Differentiation by wavenumber multiplication."""

        # Wavenumber array
        shape = [1] * len(kdata.shape)
        shape[axis] = self.coeff_size
        ik = 1j * self.wavenumbers.reshape(shape)

        # Multiplication
        kderiv[:] = kdata * ik

