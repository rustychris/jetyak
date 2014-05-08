import sys
import threading, serial, time
import winch_settings

class HumminbirdMonitorReal(object):
    def __init__(self):
        self.maxDepth = 10
        self.velocity = 10
        self.monitor = True
        self.lock = threading.Lock()
        self.open_serial()
        self.thread = threading.Thread(target=self.monitorDepthAndSpeed)
        self.thread.setDaemon(1)
        self.thread.start()
    def open_serial(self):
        print "real serial open"
        self.p = serial.Serial(winch_settings.hummingbird_com_port, baudrate=4800, timeout=5)
    def __del__(self):
        self.close()
    def close(self):
        self.monitor=False
        if self.p:
            self.p.close()
            print "Closed Hummingbird serial"
    def monitorDepthAndSpeed(self):
        #print "top of monitor thread"
        try:
            #print "top of try"
            self.maxDepth = 5
            while self.monitor:
                #print "top of loop"
                l = self.p.readline()
                if l == "":
                    # print "Got empty response hummingbird"
                    pass
                parts = l.split(',')
                #print l
                if parts[0] == '$INDPT':
                    try:
                        maxDepth = float(parts[1])
                        # print 'new max depth %f' % self.maxDepth
                    except:
                        print 'trouble parsing indpt ' + parts[1]
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
                    #print "Unknown nmea packet:"
                    #print l
                    pass
        except Exception,exc:
            if self.monitor:
                print "monitor thread died"
                print exc
            else:
                pass # on our way out.
    def moving(self):
        return self.velocity > 0.5
        
class HumminbirdMonitorTest(HumminbirdMonitorReal):
    """ stand-in for the real hummingbird
    """
    responses =["$INDPT,1.0",
                "$INVTG,one,two,three,four,five,six,2.0"]
    def open_serial(self):
        self.p = self
        self.readline = self.readline_gen().next
    def readline_gen(self):
        while 1:
            # print "Reading fake hummingbird"
            for nmea in self.responses:
                time.sleep(1.0)
                yield nmea
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
        
