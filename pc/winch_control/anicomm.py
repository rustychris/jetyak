"""
A lower latency, message-based layer
for talking to the animatics winch

probably this will get merged in with aniwinch.py

for lowest latency communication, best to know what delimiter
to look for, rather than waiting for a timeout.
"""

import serial,time

port="COM1"
ser = serial.Serial(port, 19200, timeout=1)

ser.write("RVA\r")   # maybe RPA instead for newer firmware?
while 1:
    t = time.time()
    char = ser.read(1)
    elapsed = time.time() - t
    print "[%5ims] %s"%(elapsed*1000,repr(char))
    if char == '':
        break
    
ser.close()

