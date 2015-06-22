###SmartMotor interaction and control strategies###

The SmartMotor is smart.  Sometimes too smart, sometimes not quite smart enough.  

#### Down cast ####

The main action which requires some finesse is the downcast, where a hang-up or a shallow bottom might cause the package
to stop going down even as the winch pays out more line.  The solution is a mix of letting the winch freewheel and monitoring the torque and drive current when spooling out line.  

 1. A move command is issued, like clicking on "Manual CTD cast now"
 2. The brake is released
 3. Assuming the CTD has enough mass, the drum will start rotating just from the tension on the line
 4. If the target position is reached, stop.
 5. If it has been freewheeling for more than a few seconds (currently 2 seconds - might be too short!), then abort.
 4. If/when the drum has freewheeled up to 25% of the target velocity, the motor is turned on and accelerates the line up to the target velocity.
 5. While the motor is running, the torque and current are monitored (something like twice a second).  If both are above their respective thresholds (and the sign of the torque shows that it's having to work to force the line out), then the line is probably slack.  Stop driving the motor, and revert to freewheeling mode.

This approach is a bit of a pain, but at least in the bench tests it's reasonably fast at detecting a slack line and not overrunning the line.

#### Targeet speeds throughout the cast ####

A cast is broken up into three segments, based on the settings `arm length` and `cage length`, and the depth (whether from the Humminbird, or from `Override depth`).  In terms of line out, there are 4 'waypoints':
 * A: home position, wire out=0, CTD cage all the way up, ready for transiting.
 * B: wire out=arm length.  CTD cage is barely mated with basket
 * C: wire out=arm length+cage length.  CTD cage is at the water's surface
 * D: wire out=arm length+cage length+depth.  CTD cage at bottom of cast.

On the downcast, the speed is reduced (30% of target velocity) between A and C, and runs at the target velocity between C and D.  During the upcast D to to C runs at the target velocity.  C to B runs at 20% speed, presumably while the cage mates with the basket. B to A runs at 40% speed, raising the mated CTD cage up, clear of the water.

Note that for all parts of the downcast, these velocities are just targets, and the winch still goes through the freewheeling acceleration steps described above.

#### Faults ####

Faults happen, particularly at higher speeds and heavier loads.  When a motion command stops and the status shows that a fault occured, ctd.py will read the status data and report which flags are set.  There is currently no fault recovery code in place, though the next command move will clear the fault and proceed as if it hadn't happened.  
More experience with the dominant failure modes is needed to figure out which scenarios can be recovered from (i.e. temporary extra tension on the line), vs. scenarios which should cause a true abort (cage is stuck on something, line is fouled, etc.).



