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
