import numpy as np
exper_01 = np.array( [
    [    0.0,          0.0],
    [   10.0,         10.11], 
    [   20.0,         20.44], 
    [   30.0,         30.83], 
    [   40.0,         41.31], 
    [   50.0,         51.66], # (some loose windings in there)
    [   60.0,         62.16], 
    [   70.0,         72.54], 
    [   80.0,         83.15], 
    [   90.0,         93.68], 
    [  100.0,        104.31], 
    [  110.0,        115.04], 
    [  115.0,        120.42]])

rev_total_01=410.6

## 

#coeffs=np.polyfit(exper_01[:,0],exper_01[:,1],1)

# back out the number of revolutions from current settings:
revs=np.array( [a.position_winch_to_revs(a.position_m_to_winch(m)) for m in exper_01[:,1]] )

# and then the forward calc, but we'll tune these:
# don't tune wire_area, since it is a calculated quantity.
spool_revolutions_full=415  # 415.4 # tuning this doesn't do enough
spool_width = 0.031 # spool width cancels out
spool_radius_outer = 0.154/2-0.01 - 0.002
spool_radius_inner = 0.054/2.     - 0.0023 
wire_area=spool_width*(spool_radius_outer-spool_radius_inner) / spool_revolutions_full
m_refine=2*np.pi*revs*spool_radius_outer - 2*np.pi*revs**2/2*wire_area/spool_width


import matplotlib.pyplot as plt
plt.clf()
plt.subplot(2,1,1)
plt.plot(exper_01[:,0],exper_01[:,1],'r-o')
plt.plot(exper_01[:,0],m_refine,'b-o')
plt.plot(exper_01[:,0],exper_01[:,0],'k-')
plt.subplot(2,1,2)

plt.plot(exper_01[:,0],exper_01[:,0]-m_refine,'b-o')

