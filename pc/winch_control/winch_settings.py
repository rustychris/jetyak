"""
winch_settings

machine and mission specific settings

"""
# dynamically determine where we're running
import socket, sys, os
if socket.gethostname()=='depot-PC':
    location="lab"
elif socket.gethostname()=='thistle' or sys.platform=='darwin':
    location='thistle'
else:
    location='jetyak'
    
print "Location is ",location

# Defaults:
winch_is_real = True
gpio_is_real = True
hummingbird_is_real = True

# and choose settings based on that    
if location=='lab' or location == 'thistle':
    winch_com_port="COM1"
    hummingbird_is_real = False # triggers testing setup
    gpio_is_real = False
if location=='thistle':
    winch_is_real = False
    gpio_is_real= False
    hummingbird_is_real=False
    if 1: # bench testing
        # winch_com_port="/dev/cu.usbserial"
        winch_com_port="/dev/cu.usbserial-FTGUK02I"
        winch_is_real=True
elif location=='jetyak':
    winch_com_port="COM4" # jetyak

# hardware port is COM1, but if GPSGATE is running,
# repeats to 6,8,9,10
hummingbird_com_port='COM6'
gpio_com_port = 'COM10'
winch_baud=9600


#### logging
import logging
logging.basicConfig(format="[%s] [%%(asctime)-15s] %%(message)s"%location,
                    level=logging.INFO,
                    filename=os.path.join(os.path.dirname(__file__),'log.txt'))
