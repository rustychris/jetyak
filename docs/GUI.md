the GUI
===

To start the gui, remote desktop to the Jetyak PC, then double-click "ctd.py" on the desktop.  You should
get a window like this:

![GUI screenshot](./gui-screenshot.png)

**Left column: Commands**

 * **STOP WINCH** abort any motion commands, stop the winch, engage brake
 * **Manual CTD cast now** based on the current depth, lower and recover the CTD cage, starting immediately
 * **Tow-yo now** repeatedly lower and recover the CTD cage, starting immediately
 * **Set current position as top** set cable out to 0.0, so the current position becomes the new home position
 * **Recover and reset CTD** bring the wire in slowly with constant torque. When the drum stops moving, ease a short distance and call that the new home position.
 * **Recover CTD** bring the CTD back to the home position.  Speed is reduced when the CTD cage is near the surface.
 * **Start GPIO-triggered single-cast mode** listen to Ardupilot and executre a cast when signalled.
 * **Start GPIO-triggered tow-yo** listen to Ardupilot, and tow-yo as long as signal is high.
 * **Force enable autopilot via GPIO** make the PC->Ardupilot signal low, which enables throttle.
 * **Force disable autopilot via GPIO** make the PC->Ardupilot signal high, forcing the throttle to idle.
 * **Stop automated casts** break out of either of the GPIO-triggered modes above
 * **Print status info to console** log some details about motor status to the text console.
 * **Run at speed** the slider is like one axis of a joystick, manually controlling the speed of the winch.
 * **Run at force** similar, but controlling the torque setting

**Center column: status**

 * **Depth** the water depth, as read from the Humminbird NMEA stream
 * **GPS Velocity** velocity as calculated and reported by the Humminbird
 * **Cable out** estimate of how much wire is out, both in linear length and drum revolutions.  The estimate includes the decrease in radius as the wire goes out.
 * **Cable speed** instantaneous wire speed.  This is reported as the wire speed **if** the drum were full.
 * **Winch current** the current draw as reported by the smart motor.  This does not correspond that closely with the measured current draw, but does roughly scale with the power output.
 * **Winch torque** the torque reported by the smart motor. No units, just the value reported by the motor.
 * **Winch action** reports the top-level command being executed at the moment (e.g. 'move to position', 'ctd out', 'ctd in','ctd cast','ctd reset', etc.)
 * **CTD action** reports whether manual tow-yo mode or either of the GPIO-triggered modes are active.
 * **GPIO from APM** the signal sent from the Ardupilot to the PC.  Casts are triggered by a 0-to-1 transition.
 * **GPIO to APM** the signal sent from the PC to the Ardupilot.  When ctd.py starts, this will be 'None,' indicating that the signal is in whatever state it was in before ctd.py started.  A '0' means the ardupilot can throttle up, and '1' signals the ardupilot to stay at idle.
 

 
 
