#!/usr/bin/env python
# Program: polyfold.py
# Version: 1.1
# Author: Paul S. Ray <paul.ray@nrl.navy.mil>/ Aous Abdo <aous.abdo@nrl.navy.mil>
# Description:
# Reads an FT1 file with geocentered event times and
# folds according to a polyco.dat file generated by tempo2 at the geocenter site ("coe")
# Then, fits TOAs and outputs them in tempo2 format.
from __future__ import division, print_function
import sys, math, os
from commands import getstatusoutput
from optparse import OptionParser
import numpy
import pylab
import astropy.io.fits as pyfits
import fftfit
import psr_utils
import scipy.stats
import datetime
import matplotlib.pyplot as plt
from astropy import log
from nicer.values import *

SECSPERDAY = 86400.0

desc="Read an FT1 file containing a PULSE_PHASE column and make a 2-d phaseogram"
parser=OptionParser(usage=" %prog [options] [FT1_FILENAME]",
                                        description=desc)
parser.add_option("-n","--ntoa",type="int",default=60,help="Number of TOAs to produce between TSTART and TSTOP.")
parser.add_option("-b","--nbins",type="int",default=32,help="Number of bins in each profile.")
parser.add_option("-e","--emin",type="float",default=0.3,help="Minimum energy to include.")
parser.add_option("-x","--emax",type="float",default=12.0,help="Maximum energy to include.")
parser.add_option("-o","--outfile",type="string",default=None,help="File name for plot file.  Type comes from extension.")
parser.add_option("-r","--radio",type="string",default=None,help="Radio profile to overplot.")
parser.add_option("-w","--weights",type="string",default=None,help="FITS column to use as photon weight.")
parser.add_option("-t","--tmin",type="float",default=0.0,help="Minimum time to include (MJD)")
#parser.add_option("-t","--tmax",type="float",default=0.0,help="Maximum time to include (MJD)")
parser.add_option("-s","--scale", type="string", default="linear", help="Scaling to use for the z-axis in the phaseogram plot: \'linear\' [default], \'log\', \'sqrt\', \'squared\'")
## Parse arguments
(options,args) = parser.parse_args()
if len(args) != 1:
        parser.error("event FILTS file argument is required.")

evname = args[0]

# Read FT1 file
hdulist = pyfits.open(evname)
evhdr=hdulist[1].header
evdat=hdulist[1].data

if evhdr['TIMESYS'] != 'TT':
    log.info("# !!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    log.info("# !!!!!!!!! WARNING !!!!!!!!!! TIMESYS is not TT.  We are expecting TT times!")
    log.info("# !!!!!!!!!!!!!!!!!!!!!!!!!!!!")

    # Collect TIMEZERO and MJDREF
try:
    TIMEZERO = float(evhdr['TIMEZERO'])
except KeyError:
    TIMEZERO = float(evhdr['TIMEZERI']) + float(evhdr['TIMEZERF'])
log.info("# TIMEZERO = {0}".format(TIMEZERO))
try:
    MJDREF = float(evhdr['MJDREF'])
except KeyError:
    # Here I have to work around an issue where the MJDREFF key is stored
    # as a string in the header and uses the "1.234D-5" syntax for floats, which
    # is not supported by Python
    if (type(evhdr['MJDREFF']) == str):
        MJDREF = float(evhdr['MJDREFI']) + \
            float(evhdr['MJDREFF'].replace('D','E'))
    else:
        MJDREF = float(evhdr['MJDREFI']) + float(evhdr['MJDREFF'])
log.info("# MJDREF = {0}".format(MJDREF))
mjds_tt = evdat.field('TIME')/86400.0 + MJDREF + TIMEZERO
evtimes = Time(mjds_tt,format='mjd',scale='tt')
mjds = evtimes.utc.mjd
log.info('Evtimes {0}'.format(evtimes[:10]))
phases = evdat.field('PULSE_PHASE')
if options.weights is not None:
    weights = evdat.field(options.weights)

# FILTER ON ENERGY
en = evdat.field('PI')*PI_TO_KEV
idx = numpy.where(numpy.logical_and((en>=options.emin),(en<=options.emax)))
mjds = mjds[idx]
phases = phases[idx]
log.info("Energy cuts left %d out of %d events." % (len(mjds),len(mjds_tt)))

TSTART = float(evhdr['TSTART'])
TSTARTtime = Time(TSTART/86400.0 + MJDREF + TIMEZERO,format='mjd',scale='tt')
TSTOP = float(evhdr['TSTOP'])
TSTOPtime = Time(TSTOP/86400.0 + MJDREF + TIMEZERO,format='mjd',scale='tt')

# Compute MJDSTART and MJDSTOP in MJD(UTC)
MJDSTART = TSTARTtime.utc.mjd
MJDSTOP = TSTOPtime.utc.mjd

if options.tmin !=0:
    MJDSTART = options.tmin

# Compute observation duration for each TOA
toadur = (MJDSTOP-MJDSTART)/options.ntoa
log.info('MJDSTART {0}, MJDSTOP {1}, toadur {2}'.format(MJDSTART,MJDSTOP,toadur))

mjdstarts = MJDSTART + toadur*numpy.arange(options.ntoa,dtype=numpy.float_)
mjdstops = mjdstarts + toadur

# Make profile array
profile = numpy.zeros(options.nbins,dtype=numpy.float_)
fullprof = numpy.zeros(options.nbins,dtype=numpy.float_)
err  = numpy.zeros(options.nbins,dtype=numpy.float_)

# Loop over blocks to process
a = []
for tstart,tstop in zip(mjdstarts,mjdstops):

    if options.tmin != 0 and tstart<options.tmin:
        continue

    # Clear profile array
    profile = profile*0.0

    idx = (mjds>tstart)&(mjds<tstop)

    if options.weights is not None:
        for ph,ww in zip(phases[idx],weights[idx]):
            bin = int(ph*options.nbins)
            profile[bin] += ww
            fullprof[bin] += ww
            err[bin] += ww**2
    else:
        for ph in phases[idx]:
            bin = int(ph*options.nbins)
            profile[bin] += 1
            fullprof[bin] += 1

    for i in xrange(options.nbins):
        a.append(profile[i])

a = numpy.array(a)

if options.scale == 'linear':
    a = a
elif options.scale == 'log':
    a = numpy.log(a)
elif options.scale == 'sqrt':
    a = numpy.sqrt(a)
elif options.scale == 'squared':
    a = a*a
else:
    log.error("\tYour selection for the scaling of the z-axis of the phaseogram \'%s\' is not understood" %(options.scale))
    log.error("\tPlease select from the following options: \'linear\' [default option], \'log\', \'sqrt\', \'squared\' ")
    sys.exit()
b = a.reshape(options.ntoa,options.nbins)

c = numpy.hstack([b,b])

pylab.figure(1,figsize=(6.0,8.0))
#pylab.subplot(2,1,1)
ax1 = pylab.axes([0.15,0.05,0.75,0.6])
ax1.imshow(c, interpolation='nearest', origin='lower', cmap=pylab.cm.binary,
             extent=(0,2.0,MJDSTART,MJDSTOP),aspect=2.0/(MJDSTOP-MJDSTART))
#             extent=(0,2.0,0,options.ntoa), aspect=2.5/(options.ntoa))
pylab.xlabel('Pulse Phase')
pylab.ylabel('Time (MJD)')
#pylab.title('Phaseogram')
#pylab.grid(1)
#pylab.colorbar()

#pylab.subplot(2,1,2)
ax2 = pylab.axes([0.15,0.65,0.75,0.3])
bbins = numpy.arange(2.0*len(fullprof)+1)/len(fullprof)
ax2.step(bbins,numpy.concatenate((fullprof,fullprof,numpy.array([fullprof[0]]))),where='post',color='k',lw=1.5)
pbins = numpy.arange(2.0*len(fullprof))/len(fullprof) + 0.5/len(fullprof)
py = numpy.concatenate((fullprof,fullprof))
if options.weights is not None:
    pe = numpy.sqrt(numpy.concatenate((err,err)))
else:
    pe = numpy.sqrt(py)
ax2.errorbar(pbins,py,yerr=pe,linestyle='None',capsize=0.0,ecolor='k')
pylab.ylabel('Photons')
pylab.setp(ax2.get_xticklabels(), visible=False)
pylab.ylim(ymin=0.0)
pylab.xlim((0.0,2.0))
#ax2.set_xticks(numpy.arange(20.0)/10.0)
ax2.minorticks_on()
#pylab.xlabel('Pulse Phase')

# Add radio profile
if options.radio is not None:
    x,y = numpy.loadtxt(options.radio,unpack=True)
    #x = numpy.arange(len(y))/len(y)
    #y = psr_utils.fft_rotate(y,0.2498*len(x))
    #y=y-y[20:50].mean()
    y=y*(py.max()/y.max())
    pylab.plot(numpy.arange(2.0*len(y))/len(y),numpy.concatenate((y,y)),linewidth=1.5,color='r')


#pylab.subplots_adjust(hspace=0)

if (options.outfile is not None):
    pylab.savefig(options.outfile)
else:
    pylab.show()
