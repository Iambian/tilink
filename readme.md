TI Graphing Calculator Serial Link Protocol as Implemented on a Raspberry Pi Pico
=================================================================================

Nothing very usable here yet. Might as well put a TODO list here so I can keep
track of progress and remember what needs to happen to reach my end goal.

Also going to condense some of the other documents in this project into something
here to remove the clutter and maybe make it more pretty. It may not necessarily
have anything to do with anyone else or their environment in general.

TODO
----

* ~~Get directory listing from calc and parse its contents~~
* Support silent variable requests
* Think of other protocol doodads that I might need to support
* Rewrite this whole thing in C so I can do the TinyUSB thing to make my RPI into an MTP device
* ???
* PROFIT

3.5mm Breakout Board Pinout
---------------------------

          #===#
    @@@@@@#   #@@@@@@
    @    /# S #     @  S = Sleeve ( Ground )
    @   / #   #     @  R = Ring   ( White  / Line 1 )
    @  /  # R #\    @  T = Tip    (  Red   / Line 0 )
    @ /   #   # |   @
    @ |  /# T # |   @
    @ | | ##### |   @
    @ | |       |   @
    @ | |       |   @
    @ |  \     /    @
    @ |  *******    @
    @ |  *T*S*R*    @
    @ |  *******    @
    @  \___/        @
    @               @
    @@@@@@@@@@@@@@@@@

Special Thanks
--------------

* Tim (Geekboy1011)
* The guy who wrote the TI link guide
* Others

Possibly Useful Instructions To Possibly Use What I Have So Far
---------------------------------------------------------------

0. Have a PC. Or Mac. Whatever it is, it's got to be able to run
Visual Studio Code (VSCode), not to be confused with Visual Studio IDE.

1. Go get a Raspberry Pi Pico (RP2) and make it so that you can
connect devices to it. A breadboard and some jumpers would be awesome.

2. Get one of these things: <https://www.sparkfun.com/products/12009> .
Or you can make your own for each line using either a mosfet or a
transistor+diode for each of the two lines you'll be using. Or use nothing
at all and rely on luck to keep your non-5V-tolerant RP2 from frying.

3. Figure out a way to connect your RP2 to the calculator. I use a 3.5mm jack
soldered to a breakout board with pin headers connected to the relevant pins
on the jack.

4. Connect your RP2 to the computer via USB and install Micropython on it. Do
this by flashing a Micropython image to it. Google "raspberry pi pico how to update firmware" if you don't know how to update the firmware. Google "rp2 micropython uf2" to find an image file.

5. Install VSCode then run it. In VSCode, install the "Pico-Go" extension.
That extension adds stuff to the bottom bar while you have some Python files open
and your RP2 connected to your computer. It lets you send and run stuff on the RP2.

6. Open main.py, wait for VSCode to configure itself, then on the bottom bar,
click "Run" to run the code. **DO NOT CLICK "Upload" OR YOU'LL HAVE A BAD TIME**.
All the action will now be in the Terminal (by default, the bottom window pane),
and some documentation about the program/module should print. This is your cue
to have fun and break everything.

7. Don't forget that Pico-Go includes an FTP server under the "All Commands"
thinger on the bottom bar. And that the ftp link that the console gives you can
be pasted directly in the address bar of Explorer.
