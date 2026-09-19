-- MAME 0.285 autoboot script for the lockstep trace (docs/mame-oracle.md).
-- lockstep.py substitutes READ_START/READ_LENGTH (the window whose reads the
-- host replays) and WRITE_START/WRITE_LENGTH (the window whose writes it
-- checks), and TRACEFILE.
local dbg = manager.machine.debugger
dbg.visible_cpu = manager.machine.devices[":maincpu"]
dbg:command('wpset READ_START,READ_LENGTH,r,1,{logerror "R %X %X %X\\n",wpaddr,wpsize,wpdata; g}')
dbg:command('wpset WRITE_START,WRITE_LENGTH,w,1,{logerror "W %X %X %X\\n",wpaddr,wpsize,wpdata; g}')
EXTRA
dbg:command('trace TRACEFILE,,noloop,{logerror "%X %X %X %X %X %X %X %X %X %X %X %X %X %X %X %X %X %X %X %X\\n",curpc,sr,d0,d1,d2,d3,d4,d5,d6,d7,a0,a1,a2,a3,a4,a5,a6,usp,sp,totalcycles}')
dbg:command("go")
