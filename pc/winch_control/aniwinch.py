#!/usr/bin/env python

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
            print "[fake] read past end of buffer"
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
                getattr(self,cmd)()
    def close(self):
        print "closing"
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

from async import async,OperationAborted
            
class AnimaticsWinch(object):
    cmd_ver = '523' # or 'old'
    enc_count = 4000 # std. for 17 and 23 sized motors - counts per rev.
    target_velocity = 0.25
    spool_radius = 0.07
    gear_box_ratio = 28.0 # 20.8 for old winch
    slack_current_threshold = -10
    stressed_current_threshold = 70
    # current threshold for slack line when deploying
    # for just the cage, this works:
    # deploy_slack_current = 300
    # deploy_slack_torque = 500
    # for heavy cage:
    deploy_slack_current = 300
    deploy_slack_torque = 15000
    
    # torque mode parameters:
    block_a_block_kg = 9.0

    arm_length = 0.25 # distance from up to instrument barely mated to cage
    cage_length = 0.4 # distance from mated to clear of cage
    ease_from_block_a_block = 0.83 # how far 'up' is from when the winch torques out
    
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

        self.log = logging.getLogger('winch')
        
        self.init_motor(port)

        # parameters to update during polling:
        self.monitor = dict(position_m=None,current_ma=None,volts=None)
        self.abort_async = False


    def init_motor(self,port):
        if winch_settings.winch_is_real:
            self.motor = serial.Serial(port,
                                       winch_settings.winch_baud,
                                       timeout=1)
        else:
            self.motor = FakeAnimatics()
            
        # if SMI has run recently, motor might be in echo mode
        self.msg("ECHO_OFF ")
        # Query sample rate and version
        srate,self.version = self.msg("RSP\r")[0].split('/')
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
        print "Set error limit to ",self.msg("REL\r")
        self.set_max_power_fraction(1.0)
        self.reset_encoder_position()
                        
    def msg(self,out):
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
        nresp = out.count("\r")
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
    
    def velocity_mps_to_winch(self,vel_meters_per_second):
        # the numbers below are from the animatics users guide (5.23, page 22)
        # VT = velocity * ((counts per rev) / (sample rate)) * 65536
        # velocity above is in revolutions per second
        # counts per rev is 4000, sample rate is 8000, so the
        # multiplier is 32768.
        
        circumference = self.spool_radius * 2 * math.pi
        rps = vel_meters_per_second / circumference
        # The 2 is totally empirical.
        return 2 * rps * float(self.enc_count) / self.srate * 65536.0 * self.gear_box_ratio
    def velocity_winch_to_mps(self,vel_winch):
        return vel_winch /self.velocity_mps_to_winch(1.0)

    def position_winch_to_m(self,nondim):
        return nondim/float(self.enc_count) / self.gear_box_ratio \
           * self.spool_radius * 2 *math.pi

    def position_m_to_winch(self,m):
        return m/self.position_winch_to_m(1.0)
        
    accel = 200
    ### synchronous/fast helper functions ###
    def start_velocity_move(self, vel_meters_per_second):
        self.log.info("velocity move = %.3f"%vel_meters_per_second)
        thruster_vel = self.velocity_mps_to_winch(vel_meters_per_second)

        if self.cmd_ver == 'old':
            self.msg("ZS MV AT=%i VT=%i G "%(self.accel,thruster_vel) )
        else:
            self.msg("ZS MV ADT=%i VT=%i G "%(self.accel,thruster_vel) )

    def release_brake(self):
        if self.cmd_ver != 'old':
            self.msg("BRKRLS ")

    def start_force_move(self,kg):
        """ NB: must release brake first! """
        
        # seems this command takes longer??
        # also MT acts immediately.
        # Stop, and get confirmation that it's done:
        # no idea why these commands are touchy, but 
        self.motor_stop()
        T = int(self.force_kg_to_winch(kg))
        self.log.info("Will run force mode with torque of %s"%T)
        print "Force mode, torque=",T
        if self.cmd_ver =='old':
            self.msg('MT ')
            self.msg("TS=65536 ")
            self.msg("T=%i "%T)
        else:
            self.msg('ZS MT ')
            self.msg("T=%i "%T)
            self.msg("TS=250000 G ")
        print "Done initiating force move"
        
    def start_position_move(self, absol_m=None,rel_m=None,velocity=None,direc=0,accel=None):
        """
        direc: if negative only an inward motion will be allowed, similar for positive
        """ 
        # specified in m, relative to current zero, or current
        # position
        velocity = velocity or self.target_velocity
        thruster_vel = self.velocity_mps_to_winch(velocity)
        # newer firmware may want ADT instead of AT
        if rel_m is not None:
            present_m = self.read_cable_out()
            absol_m = present_m + rel_m
        self.log.info("Starting move to cable length %s"%absol_m)
        target_position = self.position_m_to_winch(absol_m) 

        if direc != 0:
            pos = self.read_cable_out()
            if direc < 0 and pos < absol_m:
                return
            if direc > 0 and pos > absol_m:
                return

        accel = accel or 200            
        if self.cmd_ver=='old':
            cmd = "ZS MP AT=%d VT=%i PT=%i G " % (int(aceel),int(thruster_vel), int(target_position))
        else:
            cmd = "ZS MP ADT=%d VT=%i PT=%i G " % (int(accel),int(thruster_vel), int(target_position))    
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

    def read_encoder_position(self):
        if self.cmd_ver =='old':
            line, = self.msg("RP\r") 
        else:
            line, = self.msg("RPA\r")
        return float(line)

    def read_motor_current(self):
        # self.motor.write("RUIA\r")
        line, = self.msg("PRINT(UIA,#13)\r")
        curr = float(line)
        self.log.info("current=%f"%curr)
        return curr

    def read_motor_torque(self):
        line, = self.msg("RTRQ\r")
        trq = float(line)
        self.log.info("torque=%f"%trq)
        return trq
        
    def read_motor_velocity(self,dt=1.0):
        posns = []
        clks = []
        if self.cmd_ver=='old':
            cmd="RP\rRCLK\r"
        else:
            cmd="RPA\rRCLK\r"
            
        for it in range(2):            
            pos,clk_ms = [float(s) for s in self.msg(cmd)]
            posns.append(self.position_winch_to_m(pos))
            clks.append(clk_ms/1000.0)
            if it ==0:
                time.sleep(dt)

        # not sure why the factor of 4 is needed, but it is.
        return 4*(posns[1] - posns[0])/(clks[1] - clks[0])

    def status_report(self,sw0=None):
        if sw0 is None:
            sw0 = int(self.msg("RW(0)\r")[0])
        print "--- Status ---"
        for i,name in enumerate(['ready','motor_off','trajectory',
                                 'bus_volt_fault','peak_overcurrent',
                                 'temp_fault','pos_fault','vel_limit',
                                 'rt_temp','pos_error_limit',
                                 'hw_right_enabled','hw_left_enabled',
                                 'right_fault_hist','left_fault_hist',
                                 'right_fault_now','left_fault_now']):
            print "%15s: %5d"%(name,(1<<i)&sw0)
        if sw0 & 64:
            print "Actual position error: ",self.msg("REA\r")[0]
            print "Or is it",self.msg("PRINT(EA,#13)\r")[0]
            # print " Be: ",self.msg("PRINT(Be,#13)[0]\r")
        print "---"
        
    def read_cable_out(self):
        diff = self.read_encoder_position()
        pos = self.position_winch_to_m(diff)
        if abs(pos) > 0.01:
            self.log.debug('cable_out=%.2f'%pos)
        return pos

    ### Polling ###
    def poll(self):
        """ long-running operations should arrange to call this frequently,
        it updates status information from the motor, and checks self.abort_async
        to see whether the current operation should be aborted.

        Note that on abort, the motor will be stopped.
        """
        #print "winch::poll()"
        if self.abort_async:
            self.abort_async = False # show that it's been received.
            self.log.info("poll(): raising exception")
            if isinstance(self.abort_async,Exception):
                exc = self.abort_async
            else:
                exc = OperationAborted(cleanup=False)
            raise exc
        for k in self.monitor.keys():
            if k=='position_m':
                self.monitor[k] = self.read_cable_out()
                #print "Cable out",self.monitor[k]
            elif k=='current_ma':
                self.monitor[k] = self.read_motor_current()
    def handle_abort(self):
        self.log.info("handle_abort: stopping motor on abort")
        self.motor_stop()
        
    ### Blocking or asynchronous, higher-level operations ###
    @async('move to position')
    def complete_position_move(self, absol_m=None,rel_m=None,
                               velocity=None,direc=0,accel=None,
                               max_current=None):
        self.log.debug("top of complete_position_move")
        self.poll()
        self.start_position_move(absol_m=absol_m,rel_m=rel_m,velocity=velocity,
                                 direc=direc,accel=accel)
        time.sleep(0.5) # give it time to start the move
        velocity = velocity or self.target_velocity
        t_start = time.time()
        
        def stop_cond():
            vel = abs(self.read_motor_velocity(dt=0.1))
            # at higher velocity, takes some time to accelerate
            elapsed = time.time() - t_start
            if (elapsed > 1.0) and (vel < abs(0.01*velocity)):
                print "position move - end on velocity = %f after %f"%(vel,elapsed)
                # to diagnose the stops, grab status words:
                sw0 = int(self.msg("RW(0)\r")[0])
                if sw0 != 3075:
                    self.status_report(sw0=sw0)
                return True
            if max_current is not None and vel > 0.999*velocity:
                # if the CTD is heavier, bobbing up and down
                # will cause a spike in current to keep it from
                # going too fast, but we only care about when
                # the current is higher and torque is positive -
                # it's having to work to push line out.
                current = self.read_motor_current()
                torque = self.read_motor_torque()
                if current > max_current and \
                    torque > self.deploy_slack_torque:
                    # that torque threshold is hopefully going to cancel out
                    # the times that it's bobbing around.
                    print "position move - end on current=%f torq=%f"%(current,
                                                                       torque)
                    return True
            return False
        while not stop_cond():
            self.poll()

    @async('ctd out')
    def ctd_out(self, max_depth):
        self.log.debug("ctd_out start")
        self.complete_position_move(absol_m=self.arm_length+self.cage_length,
                                    velocity=0.3*self.target_velocity,block=True,
                                    direc=1)
        self.log.debug("ctd_out: second move")
        self.complete_position_move(absol_m=max_depth+self.arm_length+self.cage_length,block=True,
                                    direc=1,accel=40,
                                    max_current=self.deploy_slack_current)
        self.log.debug("ctd_out end")
    # pull winch back in, until we're back at the original position.
    @async('ctd in')
    def ctd_in(self):
        self.complete_position_move(absol_m=self.arm_length+self.cage_length,block=True,direc=-1)
        # very slow as CTD meets cage
        self.complete_position_move(absol_m=self.arm_length,
                                    velocity=0.2*self.target_velocity,
                                    block=True,direc=-1)
        # bit faster to bring it in to resting position
        self.complete_position_move(absol_m=0.0,velocity=0.4*self.target_velocity,block=True,
                                    direc=-1)

    @async('ctd cast')
    def ctd_cast(self,max_depth):
        self.ctd_out(max_depth,block=True)
        self.ctd_in(block=True)

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
        #time.sleep(1.0) # new motor is slower to ramp up
        while self.read_motor_velocity(dt=0.1) < -0.005:
            self.poll()
        self.log.info("in_by_force: found stall")
        self.motor_stop()
        if self.cmd_ver != 'old':
            self.msg("BRKTRJ ")
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
        print 'cable out %5.1f, e = %6.0f, i = %4.1f, max = %4.1f' % \
          (self.read_cable_out(), self.read_encoder_position(),
           motor_current, self.stressed_current_threshold)
        self.start_velocity_move(-self.target_velocity * 0.5)
        
        while motor_current < self.stressed_current_threshold:
            time.sleep(0.2)
            motor_current = self.read_motor_current()
            print 'cable out %5.1f, enc = %6.0f, current = %4.1f, max = %4.1f' %\
              (self.read_cable_out(), self.read_encoder_position(),
               motor_current, self.stressed_current_threshold)
        self.stop_motor()
