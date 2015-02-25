import sys
import threading, serial, time
import winch_settings
import logging
import random        

class HumminbirdMonitorReal(object):
    p=None

    def __init__(self):
        self.maxDepth = 1.0
        self.velocity = 0.0
        self.monitor = True
        self.log=logging.getLogger('humm')

        self.lock = threading.Lock()
        self.open_serial()
        self.thread = threading.Thread(target=self.monitorDepthAndSpeed)
        self.thread.setDaemon(1)
        self.thread.start()
        self.nmealog=logging.getLogger('nmea')
    def open_serial(self):
        self.log.debug("real serial open")
        try:
            self.p = serial.Serial(winch_settings.hummingbird_com_port, baudrate=4800, timeout=5)
        except OSError as exc:
            self.log.critical("Failed to open Humminbird port %s"%(winch_settings.hummingbird_com_port))
            sys.exit(1)

    def __del__(self):
        self.close()
    def close(self):
        self.monitor=False
        if self.p:
            self.p.close()
            self.log.info("Closed Hummingbird serial")
    def monitorDepthAndSpeed(self):
        """ called asynchronously to watch humminbird NMEA string,
        updating maxDepth and velocity as NMEA strings come in.
        """
        try:
            self.maxDepth = 5
            while self.monitor:
                l = self.p.readline()
                if l == "":
                    pass
                self.nmealog.info(l)
                parts = l.split(',')
                if parts[0] == '$INDPT':
                    try:
                        maxDepth = float(parts[1])
                        self.log.debug('new max depth %f' % self.maxDepth)
                    except:
                        self.log.warn('trouble parsing indpt ' + parts[1])
                        maxDepth = 0
                    with self.lock:
                        self.maxDepth = maxDepth
                elif parts[0] == '$INVTG':
                    try:  # field 7 is speed in kilometers per hour
                        # sometimes it's blank
                        velocity = float(parts[7]) * 1000.0 / 3600.0
                    except:
                        if 0:
                            print 'trouble parsing invtg '
                            for i,part in enumerate(parts):
                                print "[%d] %s"%(i,part)
                        velocity = 0
                    with self.lock:
                        self.velocity = velocity
                else:
                    pass
        except Exception as exc:
            if self.monitor:
                self.log.error("monitor thread died")
                self.log.error(str(exc))
            else:
                pass # on our way out.
    def moving(self):
        return self.velocity > 0.5


class HumminbirdMonitorTest(HumminbirdMonitorReal):
    """ stand-in for the real hummingbird
    """
    def open_serial(self):
        self.p = self
        self.readline = self.readline_gen().next
    def readline_gen(self):
        while 1:
            # print "Reading fake hummingbird"
            time.sleep(1.0)
            fake_depth=1 + random.random()*1.0
            yield "$INDPT,9.5,-0.2*64"

            yield "$INDPT,%.1f,-0.2*HH"%fake_depth

            # VTG: not sure how many of these are actually 
            # filled in by the humminbird:
            time.sleep(1.0)
            # This is actually copied from somebody's Humminbird stream,
            # though not sure it's the same model.
            # That's 11.1degT, 24.9deg M 9.9 knots, 18.4 kph
            yield "$INVTG,11.1,T,24.9,M,9.9,N,18.4,K*6D"

            # some other lines:
            for l in ["$INRMC,180048,A,4409.5583,N,07448.3608,W,10.1,12.6,280607,13.8,W*57",
                      "$INGGA,180049,4409.5610,N,07448.3597,W,2,09,0.9,450.1,M,,,,*18"]:
                time.sleep(0.1)
                yield l

    def close(self):
        pass

if winch_settings.hummingbird_is_real:
    HumminbirdMonitor = HumminbirdMonitorReal
else:
    HumminbirdMonitor = HumminbirdMonitorTest


if __name__ == '__main__':
    monitor = HumminbirdMonitor()
    while 1:
        print "depth is",monitor.maxDepth
        time.sleep(1)
        
