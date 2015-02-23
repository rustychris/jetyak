"""
winch_settings

machine and mission specific settings

"""
# dynamically determine where we're running
import sys, os
import logging
from datetime import datetime

if len(sys.argv)<2:
    location='jetyak'
else:
    location=sys.argv[1]

print "Location is ",location

# Defaults:
winch_is_real = True
gpio_is_real = True
hummingbird_is_real = True
winch_baud=9600
winch_com_port="COM1"

# and choose settings based on that    
if location=='lab':
    # windows-based laptop in the lab, winch only.
    winch_com_port="COM1"
    hummingbird_is_real = False # triggers testing setup
    gpio_is_real = False
elif location=='thistle':
    # nothing is real.
    winch_is_real = False
    gpio_is_real= False
    hummingbird_is_real=False
elif location=='workmac':
    winch_com_port="/dev/cu.usbserial-FTGUK02I"
    gpio_is_real=False
    hummingbird_is_real=False
elif location=='jetyak':
    winch_com_port="COM4" # jetyak

    # hardware port is COM1, but if GPSGATE is running,
    # repeats to 6,8,9,10
    hummingbird_com_port='COM6'
    gpio_com_port = 'COM10'

#### logging

# For now, send everything to file and stderr
fmt="[%(asctime)-15s|%(levelname)-8s|%(name)s] %(message)s"
logging.basicConfig(filename=os.path.join(os.path.dirname(__file__),'log.txt'),
                    level=logging.INFO,
                    format=fmt)

sh=logging.StreamHandler(sys.stderr)
sh.setLevel(logging.INFO)
# and ignore nmea info messages:
class NmeaFilter(object):
    def filter(self,record):
        if record.name=='nmea' and record.levelno<=logging.INFO:
            return 0
        else:
            return 1

sh.setFormatter(logging.Formatter(fmt))
sh.addFilter(NmeaFilter())

logger=logging.getLogger() 
logger.addHandler(sh)

logging.info('Starting!')

