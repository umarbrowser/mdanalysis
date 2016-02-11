# -*- Mode: python; tab-width: 4; indent-tabs-mode:nil; coding:utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
#
# MDAnalysis --- http://www.MDAnalysis.org
# Copyright (c) 2006-2015 Naveen Michaud-Agrawal, Elizabeth J. Denning, Oliver
# Beckstein and contributors (see AUTHORS for the full list)
#
# Released under the GNU Public Licence, v2 or any higher version
#
# Please cite your use of MDAnalysis in published work:
#
# N. Michaud-Agrawal, E. J. Denning, T. B. Woolf, and O. Beckstein.
# MDAnalysis: A Toolkit for the Analysis of Molecular Dynamics Simulations.
# J. Comput. Chem. 32 (2011), 2319--2327, doi:10.1002/jcc.21787
#
"""
Calculating root mean square quantities --- :mod:`MDAnalysis.analysis.rms`
==========================================================================

:Author: Oliver Beckstein, David L. Dotson
:Year: 2012
:Copyright: GNU Public License v2

.. versionadded:: 0.7.7
.. versionchanged:: 0.11.0
   Added :class:`RMSF` analysis.

The module contains code to analyze root mean square quantities such
as the coordinat root mean square distance (:class:`RMSD`) or the
per-residue root mean square fluctuations (:class:`RMSF`).

This module uses the fast QCP algorithm [Theobald2005]_ to calculate
the root mean square distance (RMSD) between two coordinate sets (as
implemented in
:func:`MDAnalysis.lib.qcprot.CalcRMSDRotationalMatrix`).

When using this module in published work please cite [Theobald2005]_.

.. SeeAlso::

   :mod:`MDAnalysis.analysis.align`
       aligning structures based on RMSD
   :mod:`MDAnalysis.lib.qcprot`
        implements the fast RMSD algorithm.

Examples
--------

Calculating RMSD for multiple domains
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In this example we will globally fit a protein to a reference
structure and investigate the relative movements of domains by
computing the RMSD of the domains to the reference. The example is a
DIMS trajectory of adenylate kinase, which samples a large
closed-to-open transition. The protein consists of the CORE, LID, and
NMP domain.

* superimpose on the closed structure (frame 0 of the trajectory),
  using backbone atoms

* calculate the backbone RMSD and RMSD for CORE, LID, NMP (backbone atoms)

The trajectory is included with the test data files. The data in
:attr:`RMSD.rmsd` is plotted with :func:`matplotlib.pyplot.plot`::

   import MDAnalysis
   from MDAnalysis.tests.datafiles import PSF,DCD,CRD
   u = MDAnalysis.Universe(PSF,DCD)
   ref = MDAnalysis.Universe(PSF,DCD)     # reference closed AdK (1AKE) (with the default ref_frame=0)
   #ref = MDAnalysis.Universe(PSF,CRD)    # reference open AdK (4AKE)

   import MDAnalysis.analysis.rms

   R = MDAnalysis.analysis.rms.RMSD(u, ref,
              select="backbone",             # superimpose on whole backbone of the whole protein
              groupselections=["backbone and (resid 1-29 or resid 60-121 or resid 160-214)",   # CORE
                               "backbone and resid 122-159",                                   # LID
                               "backbone and resid 30-59"],                                    # NMP
              filename="rmsd_all_CORE_LID_NMP.dat")
   R.run()
   R.save()

   import matplotlib.pyplot as plt
   rmsd = R.rmsd.T   # transpose makes it easier for plotting
   time = rmsd[1]
   fig = plt.figure(figsize=(4,4))
   ax = fig.add_subplot(111)
   ax.plot(time, rmsd[2], 'k-',  label="all")
   ax.plot(time, rmsd[3], 'k--', label="CORE")
   ax.plot(time, rmsd[4], 'r--', label="LID")
   ax.plot(time, rmsd[5], 'b--', label="NMP")
   ax.legend(loc="best")
   ax.set_xlabel("time (ps)")
   ax.set_ylabel(r"RMSD ($\AA$)")
   fig.savefig("rmsd_all_CORE_LID_NMP_ref1AKE.pdf")



Functions
---------

.. autofunction:: rmsd

Analysis classes
----------------

.. autoclass:: RMSD
   :members:

   .. attribute:: rmsd

      Results are stored in this N×3 :class:`numpy.ndarray` array,
      (frame, time (ps), RMSD (Å)).

.. autoclass:: RMSF
   :members:

   .. attribute:: rmsf

      Results are stored in this N-length :class:`numpy.ndarray` array,
      giving RMSFs for each of the given atoms.

"""

from six.moves import zip
import numpy as np
import logging
import warnings

import MDAnalysis.lib.qcprot as qcp
from MDAnalysis.exceptions import SelectionError, NoDataError
from MDAnalysis.lib.log import ProgressMeter
from MDAnalysis.lib.util import asiterable


logger = logging.getLogger('MDAnalysis.analysis.rmsd')


def rmsd(a, b, weights=None, center=False):
    """Returns RMSD between two coordinate sets *a* and *b*.

    *a* and *b* are arrays of the coordinates of N atoms of shape N*3
    as generated by, e.g.,
    :meth:`MDAnalysis.core.AtomGroup.AtomGroup.coordinates`.

    An implicit optimal superposition is performed, which minimizes
    the RMSD between *a* and *b* although both *a* and *b* must be
    centered on the origin before performing the RMSD calculation so
    that translations are removed.

    One can use the *center* = ``True`` keyword, which subtracts the
    center of geometry (for *weights* = ``None``) before the
    superposition. With *weights*, a weighted average is computed as
    the center.

    The *weights* can be an array of length N, containing e.g. masses
    for a weighted RMSD calculation.

    The function uses Douglas Theobald's fast QCP algorithm
    [Theobald2005]_ to calculate the RMSD.

    Example::
     >>> u = Universe(PSF,DCD)
     >>> bb = u.select_atoms('backbone')
     >>> A = bb.coordinates()  # coordinates of first frame
     >>> u.trajectory[-1]      # forward to last frame
     >>> B = bb.coordinates()  # coordinates of last frame
     >>> rmsd(A,B)
     6.8342494129169804

     .. versionchanged: 0.8.1
        *center* keyword added
    """
    if weights is not None:
        # weights are constructed as relative to the mean
        relative_weights = np.asarray(weights) / np.mean(weights)
    else:
        relative_weights = None
    if center:
        # make copies (do not change the user data!)
        # weights=None is equivalent to all weights 1
        a = a - np.average(a, axis=0, weights=weights)
        b = b - np.average(b, axis=0, weights=weights)
    return qcp.CalcRMSDRotationalMatrix(a.T.astype(np.float64),
                                        b.T.astype(np.float64),
                                        a.shape[0], None, relative_weights)


def _process_selection(select):
    """Return a canonical selection dictionary.

    :Arguments:
      *select*
         - any valid selection string for
           :meth:`~MDAnalysis.core.AtomGroup.AtomGroup.select_atoms` that produces identical
           selections in *mobile* and *reference*; or
         - dictionary ``{'mobile':sel1, 'reference':sel2}``.
           The :func:`fasta2select` function returns such a
           dictionary based on a ClustalW_ or STAMP_ sequence alignment.
         - tuple ``(sel1, sel2)``

    :Returns: dict with keys `reference` and `mobile`; the values are guaranteed to
              be iterable (so that one can provide selections that retain order)
    """
    if type(select) is str:
        select = {'reference': select, 'mobile': select}
    elif type(select) is tuple:
        try:
            select = {'mobile': select[0], 'reference': select[1]}
        except IndexError:
            raise IndexError("select must contain two selection strings "
                             "(reference, mobile)")
    elif type(select) is dict:
        # compatability hack to use new nomenclature
        try:
            select['mobile'] = select['target']
            warnings.warn("use key 'mobile' instead of deprecated 'target'; "
                          "'target' will be removed in 0.8",
                          DeprecationWarning)
        except KeyError:
            pass
        try:
            select['mobile']
            select['reference']
        except KeyError:
            raise KeyError("select dictionary must contain entries for keys "
                           "'mobile' and 'reference'.")
    else:
        raise TypeError("'select' must be either a string, 2-tuple, or dict")
    select['mobile'] = asiterable(select['mobile'])
    select['reference'] = asiterable(select['reference'])
    return select


class RMSD(object):
    """Class to perform RMSD analysis on a trajectory.

    Run the analysis with :meth:`RMSD.run`, which stores the results
    in the array :attr:`RMSD.rmsd`::

       frame    time (ps)    RMSD (A)

    This class uses Douglas Theobald's fast QCP algorithm
    [Theobald2005]_ to calculate the RMSD.

    .. versionadded:: 0.7.7
    """

    def __init__(self, traj, reference=None, select='all',
                 groupselections=None, filename="rmsd.dat",
                 mass_weighted=False, tol_mass=0.1, ref_frame=0):
        """Setting up the RMSD analysis.

        The RMSD will be computed between *select* and *reference* for
        all frames in the trajectory in *universe*.

        :Arguments:
          *traj*
             universe (:class:`MDAnalysis.Universe` object) that contains a
             trajectory
          *reference*
             reference coordinates; :class:`MDAnalysis.Universe` object; if ``None``
             the *traj* is used (uses the current time step of the object) [``None``]
          *select*
             The selection to operate on; can be one of:

             1. any valid selection string for
                :meth:`~MDAnalysis.core.AtomGroup.AtomGroup.select_atoms` that produces identical
                selections in *mobile* and *reference*; or
             2. a dictionary ``{'mobile':sel1, 'reference':sel2}`` (the
                :func:`MDAnalysis.analysis.align.fasta2select` function returns such a
                dictionary based on a ClustalW_ or STAMP_ sequence alignment); or
             3. a tuple ``(sel1, sel2)``

             When using 2. or 3. with *sel1* and *sel2* then these selections can also each be
             a list of selection strings (to generate a AtomGroup with defined atom order as
             described under :ref:`ordered-selections-label`).
          *groupselections*
             A list of selections as described for *select*. Each selection describes additional
             RMSDs to be computed *after the structures have be superpositioned* according to *select*.
             The output contains one additional column for each selection. [``None``]

             .. Note:: Experimental feature. Only limited error checking implemented.
          *filename*
             If set, *filename* can be used to write the results with :meth:`RMSD.save` [``None``]
          *mass_weighted*
             do a mass-weighted RMSD fit
          *tol_mass*
             Reject match if the atomic masses for matched atoms differ by more than
             *tol_mass* [0.1]
          *ref_frame*
             frame index to select frame from *reference* [0]

        .. _ClustalW: http://www.clustal.org/
        .. _STAMP: http://www.compbio.dundee.ac.uk/manuals/stamp.4.2/

        .. versionadded:: 0.7.7
        .. versionchanged:: 0.8
           *groupselections* added
        """
        self.universe = traj
        if reference is None:
            self.reference = self.universe
        else:
            self.reference = reference
        self.select = _process_selection(select)
        if groupselections is not None:
            self.groupselections = [_process_selection(s) for s in groupselections]
        else:
            self.groupselections = []
        self.mass_weighted = mass_weighted
        self.tol_mass = tol_mass
        self.ref_frame = ref_frame
        self.filename = filename

        self.ref_atoms = self.reference.select_atoms(*self.select['reference'])
        self.traj_atoms = self.universe.select_atoms(*self.select['mobile'])
        if len(self.ref_atoms) != len(self.traj_atoms):
            logger.exception()
            raise SelectionError("Reference and trajectory atom selections do "
                                 "not contain the same number of atoms: "
                                 "N_ref={0:d}, N_traj={1:d}".format(
                                     self.ref_atoms.n_atoms,
                                     self.traj_atoms.n_atoms))
        logger.info("RMS calculation for {0:d} atoms.".format(len(self.ref_atoms)))
        mass_mismatches = (np.absolute(self.ref_atoms.masses - self.traj_atoms.masses) > self.tol_mass)
        if np.any(mass_mismatches):
            # diagnostic output:
            logger.error("Atoms: reference | trajectory")
            for ar, at in zip(self.ref_atoms, self.traj_atoms):
                if ar.name != at.name:
                    logger.error("{0!s:>4} {1:3d} {2!s:>3} {3!s:>3} {4:6.3f}  |  {5!s:>4} {6:3d} {7!s:>3} {8!s:>3} {9:6.3f}".format(ar.segid, ar.resid, ar.resname, ar.name, ar.mass,
                                 at.segid, at.resid, at.resname, at.name, at.mass))
            errmsg = "Inconsistent selections, masses differ by more than {0:f}; mis-matching atoms are shown above.".format( \
                     self.tol_mass)
            logger.error(errmsg)
            raise SelectionError(errmsg)
        del mass_mismatches

        # TODO:
        # - make a group comparison a class that contains the checks above
        # - use this class for the *select* group and the additional
        #   *groupselections* groups each a dict with reference/mobile
        self.groupselections_atoms = [
            {
                'reference': self.reference.select_atoms(*s['reference']),
                'mobile': self.universe.select_atoms(*s['mobile']),
            }
            for s in self.groupselections]
        # sanity check
        for igroup, (sel, atoms) in enumerate(zip(self.groupselections,
                                                  self.groupselections_atoms)):
            if len(atoms['mobile']) != len(atoms['reference']):
                logger.exception()
                raise SelectionError(
                    "Group selection {0}: {1} | {2}: Reference and trajectory "
                    "atom selections do not contain the same number of atoms: "
                    "N_ref={3}, N_traj={4}".format(
                        igroup, sel['reference'], sel['mobile'],
                        len(atoms['reference']), len(atoms['mobile'])))

        self.rmsd = None

    def run(self, **kwargs):
        """Perform RMSD analysis on the trajectory.

        A number of parameters can be changed from the defaults. The
        result is stored as the array :attr:`RMSD.rmsd`.

        :Keywords:
          *start*, *stop*, *step*
             start and stop frame index with step size: analyse
             ``trajectory[start:stop:step]`` [``None``]
          *mass_weighted*
             do a mass-weighted RMSD fit
          *tol_mass*
             Reject match if the atomic masses for matched atoms differ by more than
             *tol_mass*
          *ref_frame*
             frame index to select frame from *reference*

        """
        start = kwargs.pop('start', None)
        stop = kwargs.pop('stop', None)
        step = kwargs.pop('step', None)
        mass_weighted = kwargs.pop('mass_weighted', self.mass_weighted)
        ref_frame = kwargs.pop('ref_frame', self.ref_frame)

        natoms = self.traj_atoms.n_atoms
        trajectory = self.universe.trajectory
        traj_atoms = self.traj_atoms

        if mass_weighted:
            # if performing a mass-weighted alignment/rmsd calculation
            weight = self.ref_atoms.masses / self.ref_atoms.masses.mean()
        else:
            weight = None

        # reference centre of mass system
        current_frame = self.reference.trajectory.ts.frame - 1
        try:
            # Move to the ref_frame
            # (coordinates MUST be stored in case the ref traj is advanced
            # elsewhere or if ref == mobile universe)
            self.reference.trajectory[ref_frame]
            ref_com = self.ref_atoms.center_of_mass()
            # makes a copy
            ref_coordinates = self.ref_atoms.positions - ref_com
            if self.groupselections_atoms:
                groupselections_ref_coords_T_64 = [
                    self.reference.select_atoms(*s['reference']).positions.T.astype(np.float64) for s in
                    self.groupselections]
        finally:
            # Move back to the original frame
            self.reference.trajectory[current_frame]
        ref_coordinates_T_64 = ref_coordinates.T.astype(np.float64)

        # allocate the array for selection atom coords
        traj_coordinates = traj_atoms.coordinates().copy()

        if self.groupselections_atoms:
            # Only carry out a rotation if we want to calculate secondary
            # RMSDs.
            # R: rotation matrix that aligns r-r_com, x~-x~com
            #    (x~: selected coordinates, x: all coordinates)
            # Final transformed traj coordinates: x' = (x-x~_com)*R + ref_com
            rot = np.zeros(9, dtype=np.float64)  # allocate space
            R = np.matrix(rot.reshape(3, 3))
        else:
            rot = None

        # RMSD timeseries
        nframes = len(np.arange(0, len(trajectory))[start:stop:step])
        rmsd = np.zeros((nframes, 3 + len(self.groupselections_atoms)))

        percentage = ProgressMeter(
            nframes, interval=10, format="RMSD %(rmsd)5.2f A at frame "
            "%(step)5d/%(numsteps)d  [%(percentage)5.1f%%]\r")

        for k, ts in enumerate(trajectory[start:stop:step]):
            # shift coordinates for rotation fitting
            # selection is updated with the time frame
            x_com = traj_atoms.center_of_mass().astype(np.float32)
            traj_coordinates[:] = traj_atoms.coordinates() - x_com

            rmsd[k, :2] = ts.frame, trajectory.time

            if self.groupselections_atoms:
                # 1) superposition structures Need to transpose coordinates
                # such that the coordinate array is 3xN instead of Nx3. Also
                # qcp requires that the dtype be float64 (I think we swapped
                # the position of ref and traj in CalcRMSDRotationalMatrix so
                # that R acts **to the left** and can be broadcasted; we're
                # saving one transpose. [orbeckst])
                rmsd[k, 2] = qcp.CalcRMSDRotationalMatrix(
                    ref_coordinates_T_64,
                    traj_coordinates.T.astype(np.float64), natoms, rot, weight)
                R[:, :] = rot.reshape(3, 3)

                # Transform each atom in the trajectory (use inplace ops to
                # avoid copying arrays) (Marginally (~3%) faster than
                # "ts.positions[:] = (ts.positions - x_com) * R + ref_com".)
                ts.positions -= x_com
                # R acts to the left & is broadcasted N times.
                ts.positions[:] = ts.positions * R
                ts.positions += ref_com

                # 2) calculate secondary RMSDs
                for igroup, (refpos, atoms) in enumerate(
                        zip(groupselections_ref_coords_T_64,
                            self.groupselections_atoms), 3):
                    rmsd[k, igroup] = qcp.CalcRMSDRotationalMatrix(
                        refpos, atoms['mobile'].positions.T.astype(np.float64),
                        atoms['mobile'].n_atoms, None, weight)
            else:
                # only calculate RMSD by setting the Rmatrix to None (no need
                # to carry out the rotation as we already get the optimum RMSD)
                rmsd[k, 2] = qcp.CalcRMSDRotationalMatrix(
                    ref_coordinates_T_64,
                    traj_coordinates.T.astype(np.float64),
                    natoms, None, weight)

            percentage.echo(ts.frame, rmsd=rmsd[k, 2])
        self.rmsd = rmsd

    def save(self, filename=None):
        """Save RMSD from :attr:`RMSD.rmsd` to text file *filename*.

        If *filename* is not supplied then the default provided to the
        constructor is used.

        The data are saved with :func:`np.savetxt`.
        """
        filename = filename or self.filename
        if filename is not None:
            if self.rmsd is None:
                raise NoDataError("rmsd has not been calculated yet")
            np.savetxt(filename, self.rmsd)
            logger.info("Wrote RMSD timeseries  to file %r", filename)
        return filename


class RMSF(object):
    """Class to perform RMSF analysis on a set of atoms across a trajectory.

    Run the analysis with :meth:`RMSF.run`, which stores the results
    in the array :attr:`RMSF.rmsf`.

    This class performs no coordinate transforms; RMSFs are obtained from atom
    coordinates as-is.

    .. versionadded:: 0.11.0
    """

    def __init__(self, atomgroup):
        """Calculate RMSF of given atoms across a trajectory.

        :Arguments:
            *atomgroup*
                AtomGroup to obtain RMSF for

        """
        self.atomgroup = atomgroup
        self._rmsf = None

    def run(self, start=0, stop=-1, step=1, progout=10, quiet=False):
        """Calculate RMSF of given atoms across a trajectory.

        This method implements an algorithm for computing sums of squares while
        avoiding overflows and underflows; please reference:

        .. [Welford1962] B. P. Welford (1962). "Note on a Method for
           Calculating Corrected Sums of Squares and Products."  Technometrics
           4(3):419-420.

        :Keywords:
            *start*
                starting frame [0]
            *stop*
                stopping frame [-1]
            *step*
                step between frames [1]
            *progout*
                number of frames to iterate through between updates to progress
                output; ``None`` for no updates [10]
            *quiet*
                if ``True``, suppress all output (implies *progout* = ``None``)
                [``False``]

        """
        sumsquares = np.zeros((self.atomgroup.n_atoms, 3))
        means = np.array(sumsquares)

        if quiet:
            progout = None

        # set up progress output
        if progout:
            percentage = ProgressMeter(self.atomgroup.universe.trajectory.n_frames,
                                       interval=progout)
        else:
            percentage = ProgressMeter(self.atomgroup.universe.trajectory.n_frames,
                                       quiet=True)

        for k, ts in enumerate(self.atomgroup.universe.trajectory[start:stop:step]):
            sumsquares += (k/(k + 1.0)) * (self.atomgroup.positions - means)**2
            means = (k * means + self.atomgroup.positions)/(k + 1)

            percentage.echo(ts.frame)

        rmsf = np.sqrt(sumsquares.sum(axis=1)/(k + 1))

        if not (rmsf >= 0).all():
            raise ValueError("Some RMSF values negative; overflow " +
                             "or underflow occurred")

        self._rmsf = rmsf

    @property
    def rmsf(self):
        """RMSF data; only available after using :meth:`RMSF.run`

        """
        return self._rmsf
