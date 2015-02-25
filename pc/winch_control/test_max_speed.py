import winch_settings
winch_settings.set_location('workmac')
import aniwinch
import time
import sys

winch=aniwinch.AnimaticsWinch()
## 


target_velocity=0.2

freewheel_time=5.0 # how long to wait for it to freewheel up to speed


t_start=time.time()
winch.release_brake()
winch.start_force_move(0.0)
print "Start pulling!"
# 
while time.time() - t_start < freewheel_time:
    curr_vel=winch.read_motor_velocity()

    if curr_vel>0.75*target_velocity:
        print "Freewheeled up to speed - starting to servo"
        winch.start_velocity_move(target_velocity,accel=50)
        break

print "Let it servo for 5 second"
time.sleep(5.0) # for testing
winch.stop()
winch.enable_brake()


## 

# Unfortunately, there's a huge difference between a torque setting of 0 
# which is freewheeling and a torque setting of 0.01.
# so fall back to a torque-mode start

## 
import pickle
time.sleep(5)
try:
    # need an automatic way to figure out what good current/torque numbers are
    # so that for different speeds can choose a good slack current/torque threshold
    recs=[]
    speeds=arange(0.01,0.41,0.01)
    for mult in [1,-1]:
        for spd_ms in mult*speeds:
            spd_winch = winch.velocity_mps_to_winch(spd_ms,clip=True)
            print "Testing at speed=%.2f"%spd_ms

            winch.msg("MV VT ADT=100 VT=%i G "%spd_winch)
            time.sleep(0.5)

            for n in range(10):
                time.sleep(0.2)
                # Query current, torque, speed
                uia,va,rtrq,rpa=winch.msg("PRINT(UIA,#13,VA,#13)\rRTRQ\rRPA\r",nresp=4)
                rec= dict(uia=uia,rtrq=rtrq,rpa=rpa,
                          spd_ms=spd_ms,spd_winch=spd_winch,va=va) 
                recs.append(rec)
                print rec
    with open('small-load.pkl','wb') as fp:
        pickle.dump(recs,fp)
finally:
    winch.stop()


## 

import numpy as np
import matplotlib.pyplot as plt

groups=[]
for pkl_fn in ['no-load.pkl','small-load.pkl']:
    with open(pkl_fn,'rb') as fp:
        p_recs=pickle.load(fp)

    p_samples=np.zeros(len(p_recs),
                       [ (f,'f8') for f in p_recs[0].keys()] )
    for i,rec in enumerate(p_recs):
        for f,val in rec.iteritems():
            p_samples[i][f]=val
    groups.append(p_samples)
## 

plt.figure(1).clf()
fig,axs=plt.subplots(2,1,num=1)

for grp,style in zip(groups,
                     ['r.','b.']):
    axs[0].plot(grp['spd_winch'],
                grp['uia'],style,alpha=0.5,ms=12,mew=0)
    axs[1].plot(grp['spd_winch'],
                grp['rtrq'],style,alpha=0.5,ms=12,mew=0)

# oddly, the current reading is fairly constant across 
# speeds, with a slight increase with higher speed but
# a large increase (and large variance) at speeds 
# lower than 0.10m/s

# What we want is for any given speed reeling out,
# compute a good threshold for current/torque that 
# will detect when we are essentially freewheeling.

# With a minor load, the torque on wire-out is often
# near zero, and scattered when the velocity is above
# 0.25m/s
# The current is all over the place when there is
# a load.
# existing settings: max_current=deploy_slack_current=220
# deploy_slack_torque=15000
# 
axs[0].axhline(220,color='k')
axs[1].axhline(15000,color='k')

# Fit a line to the wire-out torque:
sel=groups[0]['spd_winch']>0
wire_out_coeffs=np.polyfit( groups[0]['spd_winch'][sel],
                            groups[0]['rtrq'][sel],
                            1)
spd_winch_range=np.array( [0,groups[0]['spd_winch'].max()] )
axs[1].plot(spd_winch_range,
            np.polyval(wire_out_coeffs,spd_winch_range),'g-')




## 

def torque_thresh(spd_winch):
    wire_out_coeffs=np.array([  2.84593843e-02,   1.06744338e+03])
    return max(500,np.polyval(wire_out_coeffs,spd_winch))

def velocity_torque_move(velocity,max_pause=2.0):
    """
    A velocity move, but starts as a freewheel, and watches
    for slack current/torque conditions
    """
    target_vel=winch.velocity_mps_to_winch(velocity)

    try:
        winch.release_brake()
        winch.start_force_move(0.0)
        winch.log.info('Start free velocity move')
        mode='free'

        # track how long it's been idle:
        t_idle=time.time()

        while 1: 
            if mode=='free':
                # has it free-wheeled up to speed?
                curr_trq=winch.read_motor_torque()
                if curr_trq!=0.0:
                    winch.log.info('Wait for true free-wheel')
                    continue
                curr_vel=winch.read_motor_velocity()
                if curr_vel>0.5*target_velocity:
                    winch.log.info('Free-wheeled up to %.2f, switch to servo'%curr_vel)
                    mode='servo'
                    winch.msg('MV VT=%d ADT=100 G '%target_vel)
                    continue
                elif time.time() - t_idle > max_pause:
                    winch.log.info('Idle too long.')
                    break
            elif mode=='servo':
                va,uia,rtrq=[float(s) for s in winch.msg('PRINT(VA,#13,UIA,#13,TRQ,#13) ',nresp=3)]
                thresh=torque_thresh(va)
                # if it's working to go this fast, then revert to free-wheel
                # to avoid overhauling the line.
                if uia>winch.slack_current_threshold and rtrq>thresh:
                    winch.log.info('Line appears slack')
                    mode='free'
                    winch.msg('MT T=0 G ')
                    t_idle=time.time()
                    continue
                else:
                    print "VA: %7d  UIA: %7d [%d]  TRQ: %7d [%d]"%(va,uia,
                                                                   winch.slack_current_threshold,
                                                                   trq,thresh)

    finally:
        winch.stop()
        winch.enable_brake()

velocity_torque_move(0.05,max_pause=5.0)
