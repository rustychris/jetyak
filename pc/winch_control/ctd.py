#!/usr/bin/env python
import Tkinter
tk=Tkinter
import aniwinch
import threading
from datetime import datetime
import time
import serial
import sys

import winch_settings

from humminbird import HumminbirdMonitor
from gpio_wrapper import SerialGPIO

from async import async,OperationAborted

import logging

class CTD(object):
    towyo_factor=1.5
    depth_override=None

    def __init__(self):
        self.log = logging.getLogger('main')

        self.lock = threading.Lock()
        self.thread = None
        self.abort_async = False
        self.async_action = None
        
        self.monitor = HumminbirdMonitor()
        self.winch = aniwinch.AnimaticsWinch()
        
    @async('cast on gpio')
    def cast_on_gpio(self):
        self.last_cast_time = datetime.now()
        gpio = self.gpio()

        try:
            self.log.info("Begin GPIO single cast loop")
            while 1:
                gpio.wait_for_cast_signal(poll=self.poll)
                self.log.info("Received cast signal")
                gpio.signal_cast_in_progress()
                self.do_synchronous_cast()
                gpio.signal_cast_complete()
                self.last_cast_time = datetime.now()
        except OperationAborted:
            raise
        except Exception,exc:
            self.log.error("while gpio casting:" + str(exc))

    def depth_for_cast(self):
        if self.depth_override is not None:
            return self.depth_override
        else:
            return self.monitor.maxDepth
    def towyo_depth(self):
        return self.depth_for_cast() * self.towyo_factor 
            
    @async('tow-yo on gpio')
    def towyo_on_gpio(self):
        # tow-yo the CTD as long as the GPIO input is
        # enabled - should it wait for a off/on transition
        # before starting??
        
        gpio = self.gpio()

        try:
            self.log.info("Begin GPIO/tow-yo loop")
            
            # TODO: better logic for interrupted actions
            #  there are probably some issues right now
            #  i.e. when the winch is already doing something, none of the
            #  calls are graceful about knowing that and cancelling an existing
            #  action.

            while 1:
                self.log.info("Waiting for GPIO signal")
                gpio.wait_for_cast_signal(poll=self.poll)
                while gpio.cast_signal():
                    self.log.info("Tow-yo beginning next tow-yo drop")
                    self.winch.ctd_out(self.towyo_depth(), block=True)
                    # only bring it in most of the way
                    self.winch.complete_position_move(absol_m=self.winch.arm_length+self.winch.cage_length+0.05,
                                                      block=True,direc=-1)
                self.log.info("Tow-yo disabled - recovering CTD")
                self.winch.ctd_in(block=True)
        except OperationAborted as exc:
            # go ahead and have the winch start bringing it in, but don't wait.
            if exc.cleanup:
                self.winch.ctd_in(block=False)
            raise
        except Exception as exc:
            print self.log.error("while gpio casting:"+str(exc))

    @async('tow-yo')
    def towyo(self):
        """
        Towyo until auto action is cancelled
        """
        try:
            while 1:
                self.poll()
                self.log.debug("Tow-yo beginning next tow-yo drop")
                self.winch.ctd_out(self.towyo_depth(),
                                   block=True)
                self.log.debug("ctd::towyo::return from ctd_out")
                # only bring it in most of the way
                self.poll()
                self.log.debug("ctd::towyo::about to bring in towyo")
                self.winch.complete_position_move(absol_m=self.winch.arm_length+self.winch.cage_length+0.05,
                                                  block=True,direc=-1)
        except OperationAborted as exc:
            # go ahead and have the winch start bringing it in, but don't wait.
            # the logic is a bit wrong - on cancel of automated casts, want to
            # bring it back in, but on cancel of winch action, should exit
            # without queueing more actions
            self.log.info("ctd::towyo:received abort with cleanup=%s"%exc.cleanup)
            if exc.cleanup:
                self.winch.ctd_in(block=False)
            raise
        
    def stop_auto(self,cleanup=True):
        self.log.debug("stop_auto top, cleanup=%s"%cleanup)

        # probably a race condition here!
        # 1. there's a thread running
        # 2. stop_auto() is called - abort_async=True
        # 3. The thread exits
        # END: abort_async is left True

        # so async makes sure that the last thing that happens
        # in the thread is clearing abort_async
        with self.lock:
            if self.async_action is not None:
                self.log.info("ctd::stop_auto setting exception with cleanup=%s"%cleanup)
                self.abort_async = OperationAborted(cleanup=cleanup)

    def handle_abort(self):
        self.log.info("async action was aborted")

    # would be nice to do this with simple lexical scope,
    # but doesn't appear to work.
    waiting = 0
    def do_synchronous_cast(self):
        self.waiting=1
        def on_complete(arg):
            self.waiting -= 1
            
        self.winch.ctd_cast(self.depth_for_cast(),
                            block=False,callback=on_complete) 
        while self.waiting >0:
            self.poll()
            time.sleep(0.2)
            
    def poll(self):
        # print "ctd::poll()"
        if self.abort_async is not False:
            if isinstance(self.abort_async,OperationAborted):
                exc = self.abort_async
            else:
                exc = OperationAborted(cleanup=True)
            self.abort_async = False # it's been received
            self.log.info("ctd::poll() raising exc with cleanup=%s"%exc.cleanup)
            raise exc

    # Connect to the GPIO on demand
    _gpio = None
    def gpio(self):
        if self._gpio is None:
            self._gpio = SerialGPIO()
        return self._gpio
    
    def force_enable_gpio(self):
        self.gpio().signal_cast_complete()
    def force_disable_gpio(self):
        self.gpio().signal_cast_in_progress()

    # def cast_on_stop():
    #    try:
    #        while 1:
    #            if monitor.moving():
    #                stopped_time = datetime.now()
    #            else:
    #                if (datetime.now() - stopped_time).total_seconds() > 3:
    #                    winch.ctd_out(monitor.maxDepth)
    #                    winch.ctd_in()
    #                while not monitor.moving() and not winch.freak_out:
    #                    time.sleep(1)
    #                stopped_time = datetime.now()
    #    except:
    #        pass
    # def enable():
    #     print 'enable'
    #     global ctdThread
    #     ctdThread = threading.Thread(target = cast_on_stop)
    #     ctdThread.start()

    def enable_hw_trig_cast(self):
        def done(arg):
            self.log.info("GPIO exited")
        self.cast_on_gpio(block=False,callback=done)

    def enable_hw_trig_towyo(self):
        def done(arg):
            self.log.info("GPIO exited")
        self.towyo_on_gpio(block=False,callback=done)

    def enable_towyo(self):
        self.towyo(block=False)
        
    def start_cast(self):
        d=self.depth_for_cast()
        self.log.info('manual cast out %s' % d)
        self.winch.ctd_cast(d)

    def manual_cast(self):
        self.log.info('manual cast')
        self.winch.ctd_cast(self.depth_for_cast(),block=False,callback=self.manual_cast_complete)

    def manual_cast_complete(self,*args):
        self.log.info("Manual cast is complete")

    def recover(self):
        self.log.info('recover')
        # Note that if the CTD is already in, this will ease it
        # out and bring it back in.  Not sure if that's good
        # or bad.
        self.winch.ctd_in(block=False)

    def recover_reset(self):
        self.log.info('recover and reset')
        self.winch.ctd_in_reset(block=False)
    def reset_here(self):
        self.winch.reset_encoder_position()        

    def stop_now(self):
        self.log.info('ctd::stop_now')
        self.stop_auto(cleanup=False) # signal that no cleanup actions should be taken
        self.winch.abort()
        self.winch.stop_motor()

    def print_status(self):
        self.winch.status_report()

    update_rate_ms = 200
    
    def periodic_update(self):
        for text,thunk,str_var in self.state_values:
            try:
                str_var.set(thunk())
            except Exception as exc:
                print exc
        
        self.top.after(self.update_rate_ms,self.periodic_update)
        
    def gui_init_actions(self):
        buttons = []
        for text,cmd in [ ('STOP WINCH',self.stop_now),
                          ('Manual CTD cast now',self.manual_cast),
                          ('Tow-yo now',self.enable_towyo),
                          ('Set current position as top',self.reset_here),
                          ('Recover and reset CTD',self.recover_reset),
                          ('Recover CTD',self.recover),

                          ('Start GPIO-triggered single-cast mode',self.enable_hw_trig_cast),
                          ('Start GPIO-triggered tow-yo',self.enable_hw_trig_towyo),
                          # ('Enable Speed-based CTD mode', self.enable),
                          ('Force enable autopilot via GPIO',self.force_enable_gpio),
                          ('Force disable autopilot via GPIO',self.force_disable_gpio),
                          ('Stop automated casts',self.stop_auto),
                          ('Print status info to console',self.print_status) ]:
            buttons.append( Tkinter.Button(self.actions,text=text,command=cmd) )
        for btn in buttons:
            btn.pack(side=Tkinter.TOP,fill='x')

        # And the slider
        self.scale_var = Tkinter.DoubleVar()
        self.scale = Tkinter.Scale(self.actions,command=self.scale_changed,
                                   from_=-.450, to=0.45, resolution=0.01,
                                   orient=Tkinter.HORIZONTAL,
                                   variable = self.scale_var,
                                   label="Run at speed:")
        # go back to zero on mouse up
        # self.scale.bind('<ButtonRelease>',lambda *x: (self.scale_var.set(0.0),self.scale_changed(0.0)) )
        self.scale.bind('<Shift-ButtonRelease>',self.slider_nostop)
        self.scale.bind('<ButtonRelease>',self.slider_stop)
        self.scale.pack(side=Tkinter.TOP,fill='x')

        # And a torque slider
        self.tq_scale_var =Tkinter.DoubleVar()
        self.tq_scale = Tkinter.Scale(self.actions,command=self.tq_scale_changed,
                                      from_=-10, to=10, resolution=0.05,
                                      orient=Tkinter.HORIZONTAL,
                                      variable = self.tq_scale_var,
                                      label="Run at force:")
        self.tq_scale.bind('<ButtonRelease>',self.tq_stop)
        self.tq_scale.bind('<ButtonPress>',self.tq_start)
        self.tq_scale.pack(side=Tkinter.TOP,fill='x')

    def scale_changed(self,new_value):
        self.winch.start_velocity_move(self.scale_var.get())

    def slider_nostop(self,evt):
        print "NOT STOPPING!"
    def slider_stop(self,evt):
        self.scale_var.set(0.0)
        self.scale_changed(0.0)

    def tq_start(self,evt):
        print "Releasing brake"
        self.winch.release_brake()
        self.tq_scale_changed(0.0)
    def tq_stop(self,evt):
        print "End torque mode"
        self.winch.motor_stop()
        self.tq_scale_var.set(0.0)
        self.winch.enable_brake()

    def tq_scale_changed(self,new_value):
        force_kg=self.tq_scale_var.get()
        self.winch.start_force_move(force_kg)
        
    def gui_init_state(self):
        # a list of parameters to update periodically
        self.state_values = [ ['Depth',lambda: "%.2f m"%self.monitor.maxDepth],
                              ['GPS velocity',lambda: "%.2f m/s"%self.monitor.velocity],
                              ['Cable out',lambda: "%.2f m/%.2frev"%self.winch.read_cable_out(extra=True) ],
                              ['Cable speed',lambda: "%.2f m/s"%self.winch.read_motor_velocity() ],
                              ['Winch current',lambda: "%.0f mA?"%self.winch.read_motor_current()],
                              ['Winch torque',lambda: "%.0f"%self.winch.read_motor_torque()],
                              ['Winch action',lambda: self.winch.async_action],
                              ['CTD action',lambda: self.async_action],
                              ['GPIO from APM',lambda: self.gpio().cast_signal()],
                              ['GPIO to APM',lambda: self.gpio().last_signal_out ]]

        hdr_font = ('Helvetica','13','bold')
        hdr_key = Tkinter.Label(self.state,text="Variable",font=hdr_font,justify=tk.LEFT)
        hdr_val = Tkinter.Label(self.state,text="Value",font=hdr_font)
        hdr_key.grid(row=0,column=0,sticky=tk.N+tk.W+tk.S,ipadx=20)
        hdr_val.grid(row=0,column=1,sticky=tk.N+tk.W+tk.S,ipadx=20)
        
        for i in range(len(self.state_values)):
            text,thunk = self.state_values[i]
            
            lab = Tkinter.Label(self.state,text=text)
            str_var = Tkinter.StringVar()
            if 0:
                val = Tkinter.Entry(self.state,textvariable=str_var,
                                    state=Tkinter.DISABLED)
            else:
                val = Tkinter.Label(self.state,textvariable=str_var,
                                    justify=Tkinter.LEFT)
            str_var.set(thunk())
            lab.grid(row=i+1,column=0,sticky=tk.N+tk.W+tk.S)
            val.grid(row=i+1,column=1,sticky=tk.N+tk.W+tk.S)

            self.state_values[i].append(str_var)

    def gui_init_config(self):
        # a list of values
        self.config_values = []

        def add_gen_config(text,setter,getter):
            lab = Tkinter.Label(self.config,text=text)
            svar = Tkinter.StringVar()
            val = Tkinter.Entry(self.config,textvariable=svar,
                                state=Tkinter.NORMAL)
            svar.set( getter() )
            def real_setter(*args):
                v = svar.get()
                setter(v)
            svar.trace('w', real_setter )
            lab.grid(row=len(self.config_values),column=0)
            val.grid(row=len(self.config_values),column=1)
            self.config_values.append(svar)
            
        def add_float_config(text,obj,attr,fmt):
            def getter():
                return fmt%getattr(obj,attr)
            def setter(v):
                try:
                    setattr(obj,attr,float(v))
                except ValueError:
                    pass
            add_gen_config(text,setter,getter)

        add_float_config("Target velocity [m/s]", self.winch, "target_velocity", "%.2f")
        add_float_config('Inner radius [m]', self.winch,"spool_radius_inner", "%.4f")
        add_float_config('Outer radius [m]', self.winch,"spool_radius_outer", "%.4f")
        add_float_config('Full-in force [kg]',self.winch,"block_a_block_kg","%.2f")
        add_float_config('Zero tension current',self.winch,"deploy_slack_current","%.0f")
        add_float_config('Deploy slack torque',self.winch,"deploy_slack_torque","%.0f")
        add_float_config('Arm length [m]',self.winch,"arm_length","%.2f")
        add_float_config('Cage length [m]',self.winch,"cage_length","%.2f")
        add_float_config('Towyo factor [-]',self,"towyo_factor","%.2f")
        add_float_config('Ease from block-a-block [m]',self.winch,"ease_from_block_a_block","%.2f")
        add_gen_config('Max power fraction',
                       lambda v: self.winch.set_max_power_fraction(float(v)),
                       lambda: "%.2f"%self.winch.power_fraction)
        add_gen_config('Override depth',
                       self.set_depth_override_str,
                       self.get_depth_override_str)

    def set_depth_override_str(self,v):
        v=v.strip()
        if v=="":
            self.depth_override=None
        else:
            try:
                self.depth_override=float(v)
            except ValueError:
                pass
    def get_depth_override_str(self):
        if self.depth_override is None:
            return ""
        else:
            return "%.2f"%self.depth_override
        
    def gui(self):
        self.top = top = Tkinter.Tk()

        self.actions = Tkinter.LabelFrame(top,text="Actions")
        self.state  =  Tkinter.LabelFrame(top,text="State")
        self.config =  Tkinter.LabelFrame(top,text="Config")

        self.gui_init_actions()
        self.gui_init_state()
        self.gui_init_config()
        
        self.actions.pack(side=Tkinter.LEFT,fill='both')
        self.state.pack(side=Tkinter.LEFT,fill='both')
        self.config.pack(side=Tkinter.LEFT,fill='both')

        top.after(self.update_rate_ms,self.periodic_update)
        
        top.mainloop()
        self.log.info("exiting mainloop")
        
        self.winch.close()
        if self._gpio is not None:
            self._gpio.close()
        self.monitor.close()
        
        sys.exit()
    

if __name__ == '__main__':
    ctd = CTD()
    ctd.gui()
    

