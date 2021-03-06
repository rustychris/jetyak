#!/usr/bin/env python

import sys
import math
import serial
import time
import threading
import logging

# functions for talking to animatics smart motors over rs232 in
# python, because we can use it in windows without having to try too
# hard.

# spool out winch until max depth is hit, or until current draw drops
# too much.

import winch_settings


class FakeAnimatics(object):
    """ Simulates a serial port connected to an animatics winch -
    used for testing the code on a desktop rather than the jetyak.
    """ 
    version = '5.0.3.61'
    srate = 8000
    
    def __init__(self):
        self.buff = ""
        self.traj = None
        self.traj_fn = None
        self.time_zero = time.time()
        
        self.state = dict(VT=0,
                          ADT=100,
                          RPA=0,
                          RVA=0,
                          REL=100, # should find the actual default
                          RTRQ=0,  # does nothing...
                          T=10,
                          TS=200000,
                          RMODE=0)
        self.log = logging.getLogger('fakewinch')
        
    def read(self):
        if len(self.buff) == 0:
            # print "[fake] read past end of buffer"
            time.sleep(1)
            return ""
        else:
            char = self.buff[0]
            self.buff = self.buff[1:]
            return char
        
    def write(self,txt):
        for cmd in txt.split():
            if '=' in cmd:
                key,val = cmd.split('=')
                self.state[key] = float(val)
            elif cmd.startswith('PRINT(UIA,#13)'):
                self.buff += "100\r"
            else:
                left_paren=cmd.find('(')
                if left_paren>=0:
                    args=cmd[left_paren+1:cmd.find(')')].split(',')
                    cmd=cmd[:left_paren]
                else:
                    args=[]

                getattr(self,cmd)(*args)
    def close(self):
        pass
    def update_position(self):
        if self.traj_fn is not None:
            self.traj_fn(time.time())        
        
    def RSP(self):
        self.buff += "%i/%s\r"%(self.srate,self.version)
    def ECHO_OFF(self):
        pass
    def RPA(self):
        self.update_position()
        self.buff+="%i\r"%self.state['RPA']
    def REL(self):
        self.buff+="%i\r"%self.state['REL']
    def RTRQ(self):
        self.buff+="%i\r"%self.state['RTRQ']
    def X(self):
        self.traj = None
        self.traj_start = None
    def BRKTRJ(self):
        self.brake_mode = 'BRKTRJ'
    def BRKRLS(self):
        self.brake_mode = 'BRKRLS'
        
    def G(self):
        start_pos = self.state['RPA']
        start_time = time.time()
        VT = self.state['VT']
        
        if self.traj == 'MV':
            # velocity is in counts / sample * 65536
            # so a velocity of 65536 is 1 count per sample,
            # there are 4000 counts/rev, and 8000 samples per second,
            # so that's 2 rev/sec
            def MV_fn(t):
                elapsed = t - start_time
                self.state['RPA'] = start_pos + int(elapsed*self.srate*VT/65536)
            self.traj_fn = MV_fn
        elif self.traj == 'MP':
            PT = self.state['PT']
            if PT < start_pos:
                VT = -abs(VT)
            elif PT == start_pos:
                self.log.debug("empty MP")
                return
                
            def MP_fn(t):
                elapsed = t - start_time
                self.state['RPA'] = start_pos + int(elapsed*self.srate*VT/65536)

                if (VT < 0) == (self.state['RPA']<PT):
                    self.log.debug("MP finished")
                    self.state['RPA'] = PT
                    self.traj_fn = None
            self.traj_fn = MP_fn
        else:
            print "NOT READY FOR ",self.traj

    def MV(self):
        self.traj = 'MV'
    def MT(self):
        self.traj = 'MT'
    def MP(self):
        self.traj = 'MP'
    def ZS(self):
        pass
    def RCLK(self):
        self.buff+= "%d\r"%(1000*(time.time() - self.time_zero))
    def RW(self,arg):
        arg=int(arg)
        if arg==0:
            # Not real...
            # bitmask - 16bits
            self.buff+="127\r"
    def REA(self):
        """ report actual position error """
        self.buff+="0\r"
    def PRINT(self,*args):
        resp=[]
        for arg in args:
            if arg=='VA':
                val="0" # velocity actual
            elif arg=='#13':
                val="\r"
            elif arg=="PA":
                val="0" # position actual
            else:
                val="n/a"
                self.log.warn("Don't know how to take %s"%arg)
            resp.append(val)
        resp="".join(resp)
        self.buff+=resp

from async import async,OperationAborted
            
class AnimaticsWinch(object):
    cmd_ver = '523' # or 'old'
    enc_count = 4000 # std. for 17 and 23 sized motors - counts per rev.
    target_velocity = 0.4

    # measured with ruler and by circumference
    # 2.3mm is from tuning.
    spool_radius_inner = 0.054/2. - 0.0023
    # spool diam is 15.4cm, and "full" has about 1cm extra.
    # 2mm is from tuning
    spool_radius_outer = 0.154/2-0.01 - 0.002

    # this doesn't really matter, just used to dimensionalize
    # wire_area.
    spool_width = 0.031

    # how many revolutions it takes to pay out all of the line
    # somewhere in the range 410 -- 425, depending on tensions during
    # winding.
    spool_revolutions_full=415.4 # to pay out 112m of line.

    # 90% efficient x pi D^2/4
    # diameter here is backed out the measure revolutions
    # wire_area=0.9*math.pi*0.00205**2/4. # packed cross-sectional area of wire.
    wire_area=spool_width*(spool_radius_outer-spool_radius_inner) / spool_revolutions_full

    # this appears to be the max speed that it can swing.
    vt_max=1102000

    gear_box_ratio = 28.0 # 20.8 for old winch
    slack_current_threshold = -10
    stressed_current_threshold = 70
    # current threshold for slack line when deploying
    # for just the cage, this works:
    # deploy_slack_current = 300
    # deploy_slack_torque = 500
    # for heavy cage:
    # deploy_slack_current = 300
    # deploy_slack_torque = 15000
    # bench testing:
    deploy_slack_current = 220
    deploy_slack_torque = 15000
    
    # torque mode parameters:
    block_a_block_kg = 7.0
    reset_after_cast=False

    arm_length = 0.25 # distance from up to instrument barely mated to cage
    cage_length = 0.4 # distance from mated to clear of cage
    ease_from_block_a_block = 0.83 # how far 'up' is from when the winch torques out

    max_wire_out=105.0 # [m]

    motor=None
    
    def __init__(self,port=None):
        port=port or winch_settings.winch_com_port
        self.async_action = None
        
        # The lock is acquired inside self.msg, to prevent simultaneous
        # access to the winch.  It is also grabbed when updating the
        # asynchronous job status.
        self.lock = threading.Lock()
        # the thread running an asynchronous action.  status-reading
        # threads don't have to register here
        self.thread = None

        self.log = logging.getLogger('wnch')

        self.init_motor(port)

        # parameters to update during polling:
        self.abort_async = False

    def init_motor(self,port):
        if winch_settings.winch_is_real:
            try:
                self.motor = serial.Serial(port,
                                           winch_settings.winch_baud,
                                           timeout=1)
            except OSError as exc:
                self.log.critical("Failed to open serial port to winch")
                sys.exit(1)
        else:
            self.motor = FakeAnimatics()
            
        # if SMI has run recently, motor might be in echo mode
        self.msg("ECHO_OFF ")
        # Query sample rate and version
        rsp=self.msg("RSP\r")
        if len(rsp)==0 or rsp[0]=="":
            self.log.critical("Failed to read sample rate and version - motor disconnected?")
            sys.exit(1)
        srate,self.version = rsp[0].split('/')

        self.srate = int(srate)
        # very simple - expand as needed
        if self.version == '5.0.3.61':
            self.cmd_ver = self.version
        else:
            self.cmd_ver = 'old'
        self.log.info("Sample rate: %s"%self.srate)
        self.log.info("Firmware version: %s"%self.version)
        if self.cmd_ver != 'old':
            # N.B. BRKTRJ doesn't release the
            # break during torque mode - this must be done
            # explicitly
            self.msg('BRKTRJ ')
        # Default seems to be 1000, which has problems
        # with higher winch speeds
        self.msg('EL=-1 ')
        REL=self.msg("REL\r")[0]
        self.log.info("Set error limit to %s"%REL)
        self.set_max_power_fraction(1.0)
        self.reset_encoder_position()

    def msg(self,out,verb=2,nresp=-1):
        """ send the commands in out to the motor.
        since some commands return a value, while others do not,
        there is a special format to out.
        
        first, newlines are replaced with CR for consistency.
        then each CR is interpreted as a value to wait for.
        commands which do not produce a response must have
        a space after them to indicate that no response will come
        back.  the responses will be returned as a list of strings
        with the CR stripped
        """
        out = out.replace("\n","\r")
        
        if out[-1] not in [' ',"\r"]:
            self.log.warning("msg does not end in space or CR - assuming CR")
            out += "\r"
        if nresp<0:
            nresp = out.count("\r")
        if verb<3:
            self.log.debug("=>%s"%(repr(out)))
        with self.lock:
            self.motor.write(out)
            responses = [self.my_readline() for n in range(nresp)]
        return responses
            
    def my_readline(self):
        """ some versions of pyserial don't allow specifying
        a non-NL end of line, but going with the full io.IOBase
        stuff introduces an extra layer, and also forces us to 
        use buffering everywhere.
        
        this reads one character at a time until CR is seen,
        then returns the stripped string
        """
        eol = ["","\r","\n"]
        chars = []
        while 1:
            char = self.motor.read()
            if char in eol:
                return "".join(chars)
            chars.append(char)
            
    def __del__(self):
        """ attempt to automatically close port
        """
        if self.motor:
            self.motor.close()
            self.motor = None
    def close(self):
        if self.motor:
            self.motor.close()
            self.motor=None

    # Configurable values:
    def set_target_velocity(self,vt):
        self.log.info("New vt: %s"%vt)
        self.target_velocity = vt

    def set_max_power_fraction(self,f):
        self.power_fraction = f
        self.msg('AMPS=%d '%( int(self.power_fraction*1023) ))
    
    def abort(self):
        self.log.info("abort()")
        # stop the motor both here, because it's fast, and there might
        # not be a running operation
        self.stop_motor()
        # and in handle_abort, to clean up after the running operation
        # exits
        with self.lock:
            # if self.thread is not None:
            # problem here: if the winch is called synchronously, but
            # from a thread in ctd, then self.thread is None but we still
            # need to abort asynchronously.
            # maybe async_action is better, since it records whether we're in
            # any sort of action.
            # problem will be that abort async may get set when nobody is
            # around to listen for it, and it will cancel some future action.
            if self.async_action is not None:
                # in some cases, even though this exception is meant for
                # the winch, it may propagate out to a ctd method, where
                # we need to make sure it has cleanup=False to avoid ctd
                # scheduling cleanup actions.
                self.abort_async = OperationAborted(cleanup=False)

    def reset_encoder_position(self):
        self.msg("O=0 ")
        
    ### Unit Conversions ###
    def force_kg_to_winch(self,kg):
        # okay - kg not a force, but who knows the weight of
        # their rig in Newtons??
    
        # torque of 35 balances a 5lb weight
        if self.cmd_ver=='old':
            return kg*2.2 * 35./5.
        else:
            # new winch has different range for torque
            return kg*2.2 * 2000./5.
    def force_winch_to_kg(self,nondim):
        return nondim / self.force_kg_to_winch(1.0)
    
    def velocity_mps_to_winch(self,vel_meters_per_second,clip=True,posn_m=0.0):
        """ take a wire speed in m/s to a winch non-dimensional
        velocity setting.  Assumes full spool.

        posn_m: evaluate velocity at the given amount of wire out.  This is NOT 
         implemented!
        """
        # the numbers below are from the animatics users guide (5.23, page 22)
        # VT = velocity * ((counts per rev) / (sample rate)) * 65536
        # velocity above is in revolutions per second
        # counts per rev is 4000, sample rate is 8000, so the
        # multiplier is 32768.
        if posn_m!=0.0:
            raise Exception("Not implemented!")
        
        circumference = self.spool_radius_outer * 2 * math.pi
        rps = vel_meters_per_second / circumference
        # The 2 is totally empirical.
        vel= 2 * rps * float(self.enc_count) / self.srate * 65536.0 * self.gear_box_ratio
        if clip:
            if vel>self.vt_max:
                vel=self.vt_max
            elif vel<-self.vt_max:
                vel=-self.vt_max
        return vel

    def velocity_winch_to_mps(self,vel_winch,posn_m=0.0):
        return float(vel_winch)/self.velocity_mps_to_winch(1.0,posn_m=posn_m)

    def position_winch_to_m(self,nondim):
        # old way:
        # return nondim/float(self.enc_count) / self.gear_box_ratio \
        #    * self.spool_radius * 2 *math.pi
        # new way:
        # get drum revolutions from nondim position:
        revs=self.position_winch_to_revs(nondim)
        m=2*math.pi*revs*self.spool_radius_outer - 2*math.pi*revs**2/2*self.wire_area/self.spool_width
        return m
    def position_winch_to_revs(self,nondim):
        return nondim/float(self.enc_count) / self.gear_box_ratio

    def position_m_to_winch(self,m):
        # old way:
        # return m/self.position_winch_to_m(1.0)

        # new way - account for how much line is on the drum
        # quadratic
        # + 2*math.pi*revs**2/2*self.wire_area/self.spool_width
        # - 2*math.pi*revs*self.spool_radius_full
        # + m
        # = 0

        a=math.pi*self.wire_area/self.spool_width
        b=-2*math.pi*self.spool_radius_outer
        c=m

        # choose the smaller of the roots - the larger root is a greater number of
        # revolutions, corresponding to so much wire out that the radius becomes negative
        # and revolutions out begin to add wire.
        revs=(-b- math.sqrt(b**2-4*a*c)) / (2*a)
        nondim=revs*self.gear_box_ratio*float(self.enc_count)
        return nondim

        
    accel = 200
    ### synchronous/fast helper functions ###
    def start_velocity_move(self, vel_meters_per_second,accel=None):
        self.log.info("velocity move = %.3f"%vel_meters_per_second)
        vel = self.velocity_mps_to_winch(vel_meters_per_second,clip=True)

        accel=accel or self.accel
        self.msg("ZS MV ADT=%i VT=%i G "%(self.accel,vel) )

    def release_brake(self):
        if self.cmd_ver != 'old':
            self.msg("BRKRLS ")

    def enable_brake(self):
        if self.cmd_ver != 'old':
            self.msg("BRKTRJ ")

    def start_force_move(self,kg):
        """ NB: must release brake first! """
        
        # seems this command takes longer??
        # also MT acts immediately.
        # Stop, and get confirmation that it's done:
        # no idea why these commands are touchy, but 
        self.motor_stop()
        T = int(self.force_kg_to_winch(kg))
        self.log.info("Will run force mode with torque of %s"%T)
        if self.cmd_ver =='old':
            self.msg('MT ')
            self.msg("TS=65536 ")
            self.msg("T=%i "%T)
        else:
            self.msg('ZS MT ')
            self.msg("T=%i "%T)
            self.msg("TS=250000 G ")
        self.log.debug("Done initiating force move")
        
    def start_position_move(self, absol_m=None,rel_m=None,velocity=None,direc=0,accel=None,
                            decel=None):
        """
        direc: if negative only an inward motion will be allowed, similar for positive
        """ 
        # specified in m, relative to current zero, or current
        # position
        velocity = velocity or self.target_velocity
        vel = int( self.velocity_mps_to_winch(velocity) )
        # newer firmware may want ADT instead of AT
        if rel_m is not None:
            present_m = self.read_cable_out()
            absol_m = present_m + rel_m
        self.log.info("Starting move to cable length %s"%absol_m)
        target_position = int( self.position_m_to_winch(absol_m) )

        if direc != 0:
            pos = self.read_cable_out()
            if direc < 0 and pos < absol_m:
                return
            if direc > 0 and pos > absol_m:
                return

        if accel is None:
            accel = 100            
        else:
            accel = int(accel)
        if decel is None:
            decel=accel
        else:
            decel = int(decel)

        cmd = "ZS MP AT=%d DT=%d VT=%i PT=%i G "%(accel,decel,vel, target_position)
        self.msg(cmd)

    def stop_motor(self):
        self.log.info("Stopping motor")
        self.msg("X ")
        # And set the mode back to something sane.
        self.msg("ZS MV ADT=800 VT=0 G ")
        
    def motor_stop(self):
        self.stop_motor()
    def stop(self):
        self.stop_motor()

    # state variables which should be cached and when it's not necessary
    # to have precise data:
    # current
    # torque
    # velocity
    # cable_out
    cache_current=(0,0)
    cache_torque=(0,0)
    cache_velocity=(0,0)
    cache_cable_out=(0,0)

    def set_current(self,val):
        self.cache_current=(val,time.time())
    def set_velocity(self,val):
        self.cache_velocity=(val,time.time())
    def set_torque(self,val):
        self.cache_torque=(val,time.time())
    def set_cable_out(self,val):
        if len(val)!=2:
            raise Exception("set_cable_out() should get a tuple!")
        self.cache_cable_out=(val,time.time())

    def get_current(self,age=0.0):
        t=time.time()
        if t-self.cache_current[1] > age:
            self.read_motor_current()
        return self.cache_current[0]
    def get_velocity(self,age=0.0):
        t=time.time()
        if t-self.cache_velocity[1] > age:
            self.read_motor_velocity()
        return self.cache_velocity[0]
    def get_torque(self,age=0.0):
        t=time.time()
        if t-self.cache_torque[1] > age:
            self.read_motor_torque()
        return self.cache_torque[0]
    def get_cable_out(self,age=0.0,extra=False):
        t=time.time()
        if t-self.cache_cable_out[1] > age:
            self.read_cable_out()
        if extra:
            return self.cache_cable_out[0]
        else:
            return self.cache_cable_out[0][0]

    def read_encoder_position(self,verb=5):
        if self.cmd_ver =='old':
            line, = self.msg("RP\r",verb=verb) 
        else:
            line, = self.msg("RPA\r",verb=verb)
        try:
            return float(line)
        except ValueError:
            self.log.warn("Failed to parse encoder position '%s'"%line)
            return None

    def read_motor_current(self,uia=None,verb=5):
        if uia is None:
            uia, = self.msg("PRINT(UIA,#13)\r",verb=verb)
        curr = float(uia)
        self.log.debug("current=%f"%curr)
        self.set_current(curr)
        return curr

    def read_motor_torque(self,rtrq=None,verb=5):
        if rtrq is None:
            rtrq, = self.msg("RTRQ\r",verb=verb)
        trq = float(rtrq)
        self.log.debug("torque=%f"%trq)
        self.set_torque(trq)
        return trq

    def read_motor_velocity(self,dt=1.0,full_spool=True,verb=5):
        if 1: # try builtin measurement:
            VA,counts0=[float(s) for s in self.msg("PRINT(VA,#13,PA,#13)\r",nresp=2,verb=verb)]
            if full_spool:
                # pretend this is the velocity for when the spool is full
                counts0=0

            # that will be in encoder counts per PID sample * 65536
            # pid sample rate
            counts1=counts0 + (VA*self.srate/65536)

            posn0=self.position_winch_to_m(counts0)
            posn1=self.position_winch_to_m(counts1)
            # Not sure where the 0.5 is coming from - but at least this gets it to
            # match the commanded velocity.
            vel=0.5*(posn1 - posn0)
            return vel
        else:
            posns = []
            clks = []
            if self.cmd_ver=='old':
                cmd="RP\rRCLK\r"
            else:
                cmd="RPA\rRCLK\r"

            for it in range(2):            
                pos,clk_ms = [float(s) for s in self.msg(cmd,verb=verb)]
                posns.append(self.position_winch_to_m(pos))
                clks.append(clk_ms/1000.0)
                if it ==0:
                    time.sleep(dt)

            # not sure why the factor of 4 is needed, but it is.
            vel=4*(posns[1] - posns[0])/(clks[1] - clks[0])
        self.set_velocity(vel)
        return vel

    def status_report(self,sw0=None):
        if sw0 is None:
            sw0 = int(self.msg("RW(0)\r")[0])
        self.log.info("--- Status ---")
        for i,name in enumerate(['ready','motor_off','trajectory',
                                 'bus_volt_fault','peak_overcurrent',
                                 'temp_fault','pos_fault','vel_limit',
                                 'rt_temp','pos_error_limit',
                                 'hw_right_enabled','hw_left_enabled',
                                 'right_fault_hist','left_fault_hist',
                                 'right_fault_now','left_fault_now']):
            val=(1<<i)&sw0
            if val==0:
                val=""
            self.log.info("%16s: %s"%(name,val))
        if sw0 & 64:
            self.log.warn("Actual position error: ",self.msg("REA\r")[0])
            self.log.warn("Or is it",self.msg("PRINT(EA,#13)\r")[0])
            # print " Be: ",self.msg("PRINT(Be,#13)[0]\r")
        print "---"

    def read_cable_out(self,rpa=None,extra=False):
        if rpa is None:
            diff = self.read_encoder_position()
        else:
            diff = float(rpa)
        if diff is not None:
            pos = self.position_winch_to_m(diff)
            revs=self.position_winch_to_revs(diff)

            self.set_cable_out( (pos,revs) )
            if abs(pos) > 0.01:
                self.log.debug('cable_out=%.2f'%pos)
            if extra:
                return pos,revs
            else:
                return pos
        else:
            if extra:
                return None,None
            else:
                return None

    ### Polling ###
    def poll(self,rpa=None,uia=None):
        """ long-running operations should arrange to call this frequently,
        it updates status information from the motor, and checks self.abort_async
        to see whether the current operation should be aborted.

        Note that on abort, the motor will be stopped.

        A bit kludgey, but the caller can supply recently read strings
        for monitored values to avoid double querying.
        """
        if self.abort_async:
            self.abort_async = False # show that it's been received.
            self.log.info("poll(): raising exception")
            if isinstance(self.abort_async,Exception):
                exc = self.abort_async
            else:
                exc = OperationAborted(cleanup=False)
            raise exc

    def handle_abort(self):
        self.log.info("handle_abort: stopping motor on abort")
        self.motor_stop()
        
    ### Blocking or asynchronous, higher-level operations ###
    @async('move to position')
    def complete_position_move(self, 
                               absol_m=None,rel_m=None,
                               velocity=None,direc=0,
                               accel=None,decel=None,
                               monitor_slack=True,max_pause=2.0):
        """ absol_m: the target, ending cable out in meter
        rel_m: or targert cable out relative to current position
        velocity: a speed in m/s. N.B. this is calculated based on the 
           full spool radius.
           This can also be a function which takes the cable out in m and returns a velocity
           in m/s.

        direc: +1 only move if target is farther out, -1 only move if target is closer in.
                0 move regardless
        accel: override default accel/decel

        monitor_slack: if True and the move is outwards, then make sure there
         is always tension in the line.  This is accomplished by 
         free-wheeling at the beginning, and whenever the drive torque and current
         suggest that the motor is overhauling the line, revert to freewheel mode.
        max_pause: when free-wheeling, if it doesn't free-wheel up to half the speed
         in this time, then give up.
        """
        self.log.debug("top of complete_position_move")
        self.poll()
        velocity = velocity or self.target_velocity

        if not callable(velocity):
            vel_func=lambda x: velocity
        else:
            vel_func=velocity

        # have to wrap it, so that stop_cond() can modify.
        vbox=[vel_func]
        cmd_vel=[vbox[0](self.read_cable_out())]

        #####

        # the start_position_move logic
        # figure out 
        if rel_m is not None:
            present_m = self.read_cable_out()
            absol_m = present_m + rel_m
            
        if absol_m > self.max_wire_out:
            self.log.warn("Requested wire out %f > max %f"%(absol_m,self.max_wire_out))
            absol_m=self.max_wire_out

        target_position = int( self.position_m_to_winch(absol_m) )
        pos = self.read_cable_out()
        if direc != 0:
            if (direc < 0) == (pos < absol_m):
                self.log.info("No move - direc=%d"%direc)
                return
        else:
            # make direc reflect the way we're going
            if pos<absol_m:
                direc=1
            else:
                direc=-1
        self.log.info("Commanded to move to cable length %s"%absol_m)
        accel=accel or 100
        decel=decel or 100

        #vel = int( self.velocity_mps_to_winch(velocity) )


        if direc<0:
            # only worry about slack when reeling out
            monitor_slack=False
            
        def do_servo(target_velocity=None):
            target_velocity=target_velocity or vbox[0](self.read_cable_out())
            cmd_vel[0] = target_velocity
            vel=self.velocity_mps_to_winch(cmd_vel[0])
            cmd = "MP AT=%d DT=%d VT=%i PT=%i G "%(accel,decel,vel,target_position)
            self.msg(cmd)
        
        try:
            if monitor_slack:
                mode='free'
                self.release_brake()
                self.start_force_move(0.0)
                self.log.info('Start free velocity move')
            else:
                mode='servo'
                do_servo()
                
            # track how long it's been idle:
            t_start=t_idle=time.time()

            while 1:
                self.poll() # check for abort

                # read the current status:
                status=self.msg("RW(0)\rPRINT(VA,#13,UIA,#13,TRQ,#13)\rRPA\r",verb=5,nresp=5)
                sw0,va,uia,rtrq,rpa=[int(s) for s in status]
                in_trajectory=sw0&4

                # update the target velocity based on the new position
                cable_out=self.read_cable_out(rpa=rpa)
                target_velocity=vbox[0](cable_out)

                if mode=='free':
                    # e.g. direc=1, going out, stop if rpa is greater than target_position
                    if direc*(rpa-target_position)>=0:
                        self.log.info("Free-wheeled to target_position.")
                        break

                    # has it free-wheeled up to speed?
                    if rtrq!=0.0:
                        self.log.info('Wait for true free-wheel')
                        continue
                    curr_vel=self.velocity_winch_to_mps(va)
                    if curr_vel>0.25*target_velocity:
                        self.log.info('Free-wheeled up to %.2f, switch to servo'%curr_vel)
                        mode='servo'
                        do_servo(target_velocity=target_velocity)
                        continue
                    elif time.time() - t_idle > max_pause:
                        self.log.info('Idle too long.')
                        break
                    else:
                        self.log.info("Free-wheeling at %f [%d], compared to %.2f"%(curr_vel,va,target_velocity))
                elif mode=='servo':
                    if not in_trajectory:
                        elapsed=time.time() - t_start
                        self.log.info("position move - end on no trajectory flag after %fs"%(elapsed))
                        # to diagnose the stops, grab status words:
                        # clean this up
                        if sw0 not in (3073,3075,1,3): # this is status ready, motor off, limits enabled/disabled
                            self.log.info("SW(0) is ",repr(sw0))
                            self.status_report(sw0=sw0)
                        break

                    thresh=self.torque_thresh(spd_winch=va)
                    # if it's working to go this fast, then revert to free-wheel
                    # to avoid overhauling the line.
                    if uia>self.slack_current_threshold and rtrq>thresh:
                        self.log.info('Line appears slack')
                        mode='free'
                        self.msg('MT T=0 G ')
                        t_idle=time.time()
                        continue
                    elif target_velocity != cmd_vel[0]:
                        # update the commanded velocity
                        do_servo(target_velocity=target_velocity)
                    else:
                        self.log.debug("VA: %7d  UIA: %7d [%d]  TRQ: %7d [%d]"%(va,uia,
                                                                                self.slack_current_threshold,
                                                                                rtrq,thresh))

        finally:
            self.stop()
            self.enable_brake()
                                       

        #######
        

        #  def stop_cond():
        #      elapsed = time.time() - t_start
        #  
        #      # sw0 = int(self.msg("RW(0)\r",verb=5)[0])
        #  
        #      # Read everything at once - too much overhead in individual calls
        #      sw0,uia,rtrq,rpa=self.msg("RW(0)\rPRINT(UIA,#13)\rRTRQ\rRPA\r",verb=5)
        #      sw0=int(sw0)
        #  
        #      in_trajectory=sw0&4
        #  
        #      if not in_trajectory:
        #          self.log.info("position move - end on no trajectory flag after %fs"%(elapsed))
        #          # to diagnose the stops, grab status words:
        #          # clean this up
        #          if sw0 not in (3073,3075,1,3): # this is status ready, motor off, limits enabled/disabled
        #              self.log.info("SW(0) is ",repr(sw0))
        #              self.status_report(sw0=sw0)
        #          return True
        #      if max_current is not None and (elapsed > 2.0) and (cmd_vel[0]>0):
        #          # if the CTD is heavier, bobbing up and down
        #          # will cause a spike in current to keep it from
        #          # going too fast, but we only care about when
        #          # the current is higher and torque is positive -
        #          # it's having to work to push line out.
        #          current = self.read_motor_current(uia=uia)
        #          torque = self.read_motor_torque(rtrq=rtrq)
        #          self.log.info("curr=%f    torq=%f"%(current,torque))
        #          if current > max_current and \
        #              torque > self.deploy_slack_torque:
        #              # that torque threshold is hopefully going to cancel out
        #              # the times that it's bobbing around.
        #              self.log.warn("position move - abort on current=%f torq=%f"%(current,
        #                                                                           torque))
        #              if 0: # Try stopping more explicitly:
        #                  self.stop_motor()
        #                  # I don't think we have to wait here...
        #                  return True
        #              else: # freewheel and resume?
        #                  # not entirely sure how much of this incantation is
        #                  # required - 
        #                  self.release_brake()
        #                  self.msg("OFF") # redundant??
        #  
        #                  # seems we need to be in torque mode in order
        #                  # to make a smooth transition to velocity mode.
        #                  self.msg("MT T=0 TS=250000 G ")
        #  
        #                  self.log.info("Free-wheeling for 3 seconds...")
        #                  t_wait=3.0
        #                  dt=0.1
        #                  for i in range(int(t_wait/dt)):
        #                      time.sleep(dt)
        #                      vel=self.read_motor_velocity()
        #                      # TODO: should also see if we've reached
        #                      # the intended position while free-wheeling.
        #                      self.log.info("Free-wheel velocity is %.2f, commanded=%.2f"%(vel,cmd_vel[0]))
        #                      
        #                      if vel>0.25*cmd_vel[0]:
        #                          self.log.inf("Will try resuming down cast")
        #                          
        #                          self.start_position_move(absol_m=absol_m,rel_m=rel_m,
        #                                                   velocity=cmd_vel[0],
        #                                                   accel=100,decel=100)
        #                          # doesn't brake, just sets the brake-on-no-trajectory
        #                          # flag.
        #                          self.enable_brake()
        #                          
        #                          # This was no good - it needs to be a position
        #                          # move.  
        #                          # vel_winch=int(self.velocity_mps_to_winch(cmd_vel[0]))
        #                          # self.msg("MV AT=50 VT=%d G"%vel_winch)
        #                          break
        #                  else: 
        #                      # override requested velocity to 0,
        #                      # but drop back out to regular loop
        #                      # to wait for end of trajectory.
        #                      self.log.info("Slow shift to vel mode")
        #                      self.msg("MV VT=0 ADT=30 DT=30 G")
        #                      vbox[0]=lambda x: 0
        #                      cmd_vel[0]=0
        #                      # go back to brake on no trajectory
        #                      self.enable_brake()
        #  
        #      # variable speed tests:
        #      new_vel=vbox[0](self.read_cable_out(rpa=rpa))
        #      if cmd_vel[0] != new_vel:
        #          self.log.debug("Updating velocity")
        #          cmd_vel[0]=new_vel
        #          vel_winch=int(self.velocity_mps_to_winch(new_vel))
        #          self.msg("VT=%d G"%vel_winch)
        #      
        #      return False
        #  while not stop_cond():
        #      self.poll()

    def torque_thresh(self,spd_winch):
        wire_out_coeffs=[  2.84593843e-02,   1.06744338e+03]
        calc=wire_out_coeffs[0]*spd_winch + wire_out_coeffs[1]
        return max(500,calc)

    @async('ctd out')
    def ctd_out(self, max_depth):
        self.log.debug("ctd_out start")
        def vfunc(cable_out):
            if cable_out<self.arm_length+self.cage_length:
                return 0.3*self.target_velocity
            else:
                return self.target_velocity
        self.complete_position_move(absol_m=max_depth+self.arm_length+self.cage_length,
                                    block=True,
                                    direc=1,accel=80,
                                    monitor_slack=True,
                                    velocity=vfunc)
    # pull winch back in, until we're back at the original position.
    @async('ctd in')
    def ctd_in(self):
        if 0: # old way, with separate moves
            self.complete_position_move(absol_m=self.arm_length+self.cage_length,block=True,direc=-1)
            # very slow as CTD meets cage
            self.complete_position_move(absol_m=self.arm_length,
                                        velocity=0.2*self.target_velocity,
                                        block=True,direc=-1)
            # bit faster to bring it in to resting position
            self.complete_position_move(absol_m=0.0,velocity=0.4*self.target_velocity,block=True,
                                        direc=-1)
        else:
            def vfunc(cable_out):
                if cable_out>self.arm_length+self.cage_length:
                    return self.target_velocity
                elif cable_out>self.arm_length:
                    return 0.2*self.target_velocity
                else:
                    return 0.4*self.target_velocity
            self.complete_position_move(absol_m=0.0,
                                        velocity=vfunc,
                                        block=True,
                                        accel=80,
                                        decel=80,
                                        direc=-1)

    @async('ctd cast')
    def ctd_cast(self,max_depth):
        self.ctd_out(max_depth,block=True)
        self.ctd_in(block=True)
        if self.reset_after_cast:
            # TODO: might want to have ctd_in not quite bring it
            # in all the way?
            self.ctd_in_reset(block=True)

    reset_strategy = 'force' # 'current'
    @async('ctd in reset')
    def ctd_in_reset(self):
        if self.reset_strategy == 'current':
            self.ctd_in_by_current(block=True)
        elif self.reset_strategy=='force':
            self.ctd_in_by_force(block=True)
        self.reset_encoder_position()

    @async('ctd in by force')
    def ctd_in_by_force(self):
        self.release_brake()
        self.start_force_move(-self.block_a_block_kg)
        time.sleep(1.0) # new motor is slower to ramp up
        while self.read_motor_velocity() < -0.005:
            self.poll()
        self.log.info("in_by_force: found stall")
        self.motor_stop()
        self.enable_brake()
        self.log.info("stopped motor")
        # relieves tension to reduce power by servoing in place
        self.complete_position_move(rel_m=self.ease_from_block_a_block,block=True)

    @async('ctd in by current')
    def ctd_in_by_current(self):
        """
        DEPRECATED - sometimes it takes too long to detect a high current
        condition and the motor will stall and freewheel.  This is less
        of an issue with a motor with a brake, but still this code hasn't
        been used in a little while.
        """
        motor_current = self.read_motor_current()
        self.log.info('cable out %5.1f, e = %6.0f, i = %4.1f, max = %4.1f' % \
                      (self.read_cable_out(), self.read_encoder_position(),
                       motor_current, self.stressed_current_threshold))
        self.start_velocity_move(-self.target_velocity * 0.5)
        
        while motor_current < self.stressed_current_threshold:
            time.sleep(0.2)
            motor_current = self.read_motor_current()
            self.log.info('cable out %5.1f, enc = %6.0f, current = %4.1f, max = %4.1f' %\
                          (self.read_cable_out(), self.read_encoder_position(),
                           motor_current, self.stressed_current_threshold))
        self.stop_motor()
