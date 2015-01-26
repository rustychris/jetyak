"""
A lower latency, message-based layer
for talking to the animatics winch

probably this will get merged in with aniwinch.py

for lowest latency communication, best to know what delimiter
to look for, rather than waiting for a timeout.
"""

import serial,time
import sys

if sys.platform=='darwin':
    # port="/dev/cu.usbserial"
    port="/dev/cu.usbserial-FTGUK02I"
elif sys.platform=='windows':
    port="COM1"


for speed in [9600]:
    print "-"*20,speed,"-"*20
    try:
        ser = serial.Serial(port, speed, timeout=0.5)
        ser.write("\r")
        ser.write("RSP\r")   # maybe RPA instead for newer firmware?
        ser.write("RPA\r")   # maybe RPA instead for newer firmware?
        while 1:
            t = time.time()
            char = ser.read(1)
            elapsed = time.time() - t
            print "[%5ims] %s"%(elapsed*1000,repr(char))
            if char == '':
                break
        ser.close()
    except IOError:
        ser.close()
        
