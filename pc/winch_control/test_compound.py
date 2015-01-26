"""
A lower latency, message-based layer
for talking to the animatics winch

probably this will get merged in with aniwinch.py

for lowest latency communication, best to know what delimiter
to look for, rather than waiting for a timeout.
"""

import serial,time
import sys
import aniwinch
reload(aniwinch)

winch=aniwinch.AnimaticsWinch()


## 


winch.complete_position_move(1.0,block=True)

## 
def slow_fast(x):
    if x<0.5:
        return 0.1
    else:
        return 0.5

winch.complete_position_move(0.0,block=True)
winch.complete_position_move(2.0,block=True,velocity=slow_fast,accel=100)

# seems to decelerate with a jerk when the velocity is updated.
# might need to send the whole motion command again to get it to update
# position/velocity/acceleration curves

## 
    pos=winch.read_cable_out()
    if VT==VTslow and pos>0.75:
        VT=VTfast
        # this had no effect without G
        winch.msg("VT=%d G"%VT)
        print "Increased speed"
        break
    else:
        time.sleep(0.05)

## 
winch.close()
