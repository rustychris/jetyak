import serial, sys, threading, time
import winch_settings

import logging

class SerialGPIOReal(object):
    gpio_recv=0 # for AP to signal to PC to cast
    gpio_xmit=1 # for PC to signal to AP to stop
    def __init__(self):
        self.last_signal_out = None
        self.open_serial()
        self.log = logging.getLogger('gpio')
        
    def open_serial(self):
        try:
            self.ser = serial.Serial(winch_settings.gpio_com_port, timeout=1)
        except Exception,exc:
            self.log.error("Failed to open serial")
            self.log.error(str(exc))
            self.ser = None

    def cast_signal(self):
        """ return boolean whether Ardupilot has signalled for a cast.
        """
        return self.read(self.gpio_recv) == 1
    def wait_for_cast_signal(self,poll=None):
        # assume we're called before the cast is signalled
        # for, but in case the output was left high, stall
        # until it's low.
        while self.cast_signal(): # wait for clean start
            self.log.info("Cast signal hasn't transitioned yet")
            if poll:
                poll()
            time.sleep(0.5)
        while not self.cast_signal(): # wait for the real signal
            self.log.info("Cast signal is low - waiting")
            if poll:
                poll()
            # this is where it should wait for a while
            time.sleep(0.5)

    def signal_cast_in_progress(self):
        self.write(self.gpio_xmit,1)
        self.last_signal_out = 1
        # pass
    def signal_cast_complete(self):
        self.write(1,0)
        self.last_signal_out = 0
    def read(self, chan):
        self.ser.flushInput()
        self.ser.write('gpio read %d\r' % chan)
        l = self.ser.readline()
        if l.startswith('\r'): l = l[1:]
        # print l
        while l.startswith('>') or l.startswith('g'):
            l = self.ser.readline()
            if l.startswith('\r'): l = l[1:]
        try:
            val = int(l)
            #print 'read val %d' % val
            return val
        except:
            #print 'gpio read fail'
            return 0

    def write(self, chan, val):
        if val:
            self.ser.write('gpio set %d\r' % chan)
        else:
            self.ser.write('gpio clear %d\r' % chan)
    def __del__(self):
        if self.ser:
            self.ser.close()
            print "GPIO closing serial port"
    def close(self):
        if self.ser:
            self.ser.close()
            self.ser = None

class SerialGPIOTest(SerialGPIOReal):
    """ sneaky dual purpose class - overrides basic logic
    as needed for the SerialGPIOReal class, but also submits
    itself as the serial connection so that where possible
    we only have to fake the serial responses
    """
    def open_serial(self):
        self.ser = self
    def flushInput(self):
        pass
    def write(self,chan,val):
        print "Sending gpio message:",chan,val
    def read(self,chan):
        t = time.time()
        if t % 15 < 13:
            return 1
        else:
            return 0
    def close(self):
        pass


if winch_settings.gpio_is_real:
    SerialGPIO = SerialGPIOReal
else:
    SerialGPIO = SerialGPIOTest
    
if __name__ == '__main__':
    gpio = SerialGPIO()
    while 1:
        print gpio.read(0)
        time.sleep(0.5)
