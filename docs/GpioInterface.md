*this file is the updated incarnation of pc/winch_control/how-to-use-gpio-thing.txt*

GPIO Interface
===

The players:

 * the Numato GPIO-USB interface board - small red board in the tupperware with the ardupilot
 * USB cable from the Numato to onboard PC, appears as a serial interface
 * ground and two data wires going to the ardupilot
 
The purpose: 

 * ardupilot can signal to the PC that a cast should be performed
 * PC can signal to the ardupilot to idle the engine during a cast
 
How to set this thing up:

Connect the Numato GPIO USB thing to the windows box, and figure out
which COM port it gets assigned to. On Linux, this is /dev/ttyACM0,
and in the present state of things, it is COM10 on the PC in Windows.
[winch_settings.gpio_com_port](../pc/winch_control/winch_settings.py)
is where this is defined.

The APM "relay" is actually output channel A9. For some weird reason,
in the mission planner the relay pin is set to 13 (see the comment in
Mission Planner) Connect the '-' pin (nearest edge) of A9 to the GND terminal of the USBGPIO, 
and connect the 'S' pin (farthest from edge) of A9 to the IO0 terminal of 
the USBGPIO.

Now you can use 'DO_SET_RELAY'
commands in the mission planner to trigger CTD casts, assuming you're
running the ctd.py program on the windows box and have enabled them to
be triggered this way by pressing the "Enable cast on gpio" button. 

A transition from 0 to 1 will trigger a cast.  The PC has to poll the
GPIO, so both the 0 and the 1 should be set for at least a second.
There is also a towyo mode, which will continue tow-yoing until the
pin is set back to 0, and not disable throttle.

To allow the PC to idle the Jetyak engine, 
connect the '-' line of A8 back to the USBGPIO GND terminal, and the 'S' line of
A8 to the USBGPIO IO1 terminal (RH: this used to be on A5, but that
seemed flaky). The ardupilot has to be configured to enable this behavior,
by setting the AUTO_TRIGGER_PIN to 8 in the mission planner. 
Now the throttle will always be set to the minimum value unless the A8 signal
is attached to ground.  To reiterate: setting pin A8 high forces idle, and
pin A8 grounded enables normal throttle control.

In the past, the status of IO1 was indeterminate on bootup (i.e. floating), 
so if you weren't running ctd.py (which would set IO1 high), then the
ardupilot's throttle control was erratic (because it couldn't tell if 
IO1 was high or low).  By adding a 10k pulldown resistor to IO1, it will default
to low (throttle enabled), and this feature can be left enabled in the ardupilot
firmware.

In the absence of this pulldown resistor, you have two options: (a) start up ctd.py and click
"Force enable autopilot via GPIO" button in the UI to make sure the GPIO
is set low (enable throttle), or (b) disable AUTO_TRIGGER_PIN in the ardupilot
settings.

When ctd.py is first started, it doesn't do anything with the GPIO, neither
sending nor receiving signals.  Clicking "Enable cast on gpio" will put
ctd.py into a listening mode, where it waits for the signal from the ardupilot
to transition from 0 to 1.  When this happens, it responds by first idling
the engine (sending a high signal to the ardupilot), performing a cast, and then
changing the GPIO back to low.
